"""RAG 检索管道的可选模型重排序工具。

项目已有一个基于规则的重排序器。本模块添加了两个小型、独立的构建块：

1. ``cross_encoder_rerank``：
   交叉编码器（Cross-Encoder）将 ``[查询, 文档]`` 一起读入并预测相关性分数。
   它比比较两个单独编码的向量更准确，但计算成本也更高，因此仅应在召回/粗排后
   的小型候选列表上运行。

2. ``reciprocal_rank_fusion``：
   倒数排名融合（RRF）在不假设原始分数含义相同的前提下合并多个排序列表。
   这对于向量搜索、BM25 以及其他分数范围不可直接比较的检索路径非常有用。

模型依赖被刻意设置为可选。当 ``RAG_CROSS_ENCODER_RERANK_ENABLED`` 未设置或为
 false 时，调用者将获得原始的规则排序列表，且无需安装 ``sentence-transformers``。

示例：

    RAG_CROSS_ENCODER_RERANK_ENABLED=1
    RAG_CROSS_ENCODER_MODEL=BAAI/bge-reranker-base

快速本地实验：

    from core.service.reranker import cross_encoder_rerank

    class FakeModel:
        def predict(self, pairs, batch_size=16):
            return [0.2, 0.9][:len(pairs)]

    results = cross_encoder_rerank(
        "如何连接 WiFi",
        candidates,
        text_getter=lambda item: item.content,
        rule_score_getter=lambda item: item.final_score,
        score_setter=lambda item, score: replace(item, final_score=score),
        top_k=5,
        model=FakeModel(),
    )
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from functools import lru_cache
from typing import Any, Callable, Hashable, Sequence, TypeVar


# 泛型类型变量：表示任意类型的文档块（chunk）对象，保持函数对调用方数据结构的通用性
T = TypeVar("T")
# 分数设置器的函数类型签名：接收一个文档块对象和新分数，返回更新后的文档块对象
# 使用 Callable 而非直接在参数中写复杂类型，提升可读性并便于复用
ScoreSetter = Callable[[T, float], T]


@dataclass(frozen=True)
class RerankerConfig:
    """可选交叉编码器阶段的运行时配置。

    数据类被标记为 frozen（不可变），确保配置加载后不会被意外修改，
    避免在多线程或多阶段处理中出现难以排查的配置不一致问题。

    ``candidate_top_n`` 是发送给模型的最大文本块数量。
    值越大可以提高召回率，但会增加延迟和内存占用。
    ``model_weight`` 和 ``rule_weight`` 用于混合归一化后的模型分数和规则分数。
    """

    # 交叉编码器重排功能的总开关：False 时完全跳过模型推理，直接返回规则排序结果
    enabled: bool = False
    # HuggingFace 模型名称或本地模型目录路径，默认使用中文场景效果较好的 bge-reranker-base
    model_name: str = "BAAI/bge-reranker-base"
    # 送入模型进行精排的候选数量上限：只对粗排结果的前 N 个做模型打分，平衡效果与性能
    candidate_top_n: int = 30
    # 模型推理时的批处理大小：越大吞吐量越高，但占用显存/内存也越大
    batch_size: int = 16
    # 模型预测分数在最终融合分数中的权重占比（会被归一化，不需要手动加和为1）
    model_weight: float = 0.65
    # 原有规则分数在最终融合分数中的权重占比
    rule_weight: float = 0.35

    @classmethod
    def from_environment(cls) -> "RerankerConfig":
        """从环境变量构建配置实例。

        使用环境变量而非配置文件的好处：
        - 便于容器化部署（Docker/K8s 通过环境变量注入配置）
        - 无需修改代码即可切换不同环境的行为
        - 与主流机器学习项目的配置惯例保持一致

        支持的环境变量：

        - ``RAG_CROSS_ENCODER_RERANK_ENABLED``：设为 ``1/true/yes/on`` 启用。
        - ``RAG_CROSS_ENCODER_MODEL``：Hugging Face 模型名称或本地路径。
        - ``RAG_CROSS_ENCODER_CANDIDATE_TOP_N``：待重排的粗排候选数量。
        - ``RAG_CROSS_ENCODER_BATCH_SIZE``：交叉编码器推理批次大小。
        - ``RAG_CROSS_ENCODER_MODEL_WEIGHT``：模型分数权重。
        - ``RAG_CROSS_ENCODER_RULE_WEIGHT``：现有规则分数权重。
        """

        return cls(
            # 读取开关变量：未设置时默认关闭，保证向后兼容
            enabled=_env_bool("RAG_CROSS_ENCODER_RERANK_ENABLED"),
            # 读取模型名：strip() 去除用户误输入的首尾空格，避免模型加载失败
            model_name=os.getenv(
                "RAG_CROSS_ENCODER_MODEL",
                "BAAI/bge-reranker-base",
            ).strip(),
            # 候选数：max(1, ...) 防止用户误设为0或负数导致候选列表为空
            candidate_top_n=max(
                1,
                _env_int("RAG_CROSS_ENCODER_CANDIDATE_TOP_N", 30),
            ),
            # 批次大小：同理，至少为1，避免 batch_size=0 导致推理报错
            batch_size=max(
                1,
                _env_int("RAG_CROSS_ENCODER_BATCH_SIZE", 16),
            ),
            # 模型权重：使用 _bounded_float 限制在 [0, 1] 区间，防止极端配置
            model_weight=_bounded_float(
                "RAG_CROSS_ENCODER_MODEL_WEIGHT",
                0.65,
            ),
            # 规则权重：同上
            rule_weight=_bounded_float(
                "RAG_CROSS_ENCODER_RULE_WEIGHT",
                0.35,
            ),
        ).normalized_weights()  # 构造完成后立即归一化权重，确保比例有效

    def normalized_weights(self) -> "RerankerConfig":
        """将 model_weight 和 rule_weight 归一化，使两者之和等于 1。

        归一化的必要性：
        1. 用户可能将两个权重分别设为 0.8 和 0.4，它们的比例是 2:1 但总和不为1
        2. 直接使用原始权重会让融合分数的绝对值偏大或偏小，影响后续阈值判断
        3. 若两者均为0或负数，回退到默认的 0.65:0.35 比例，避免全零权重

        注意：由于 dataclass 是 frozen 的，此方法返回新实例而非修改自身。
        """
        # 计算权重总和，用于比例归一化
        total = self.model_weight + self.rule_weight
        # 总和无效（零或负）：回退到内置的安全默认比例
        if total <= 0:
            return RerankerConfig(
                enabled=self.enabled,
                model_name=self.model_name,
                candidate_top_n=self.candidate_top_n,
                batch_size=self.batch_size,
                model_weight=0.65,
                rule_weight=0.35,
            )

        # 正常情况：按比例缩放，使权重之和严格为 1
        return RerankerConfig(
            enabled=self.enabled,
            model_name=self.model_name,
            candidate_top_n=self.candidate_top_n,
            batch_size=self.batch_size,
            model_weight=self.model_weight / total,
            rule_weight=self.rule_weight / total,
        )


def reciprocal_rank_fusion(
    ranked_lists: Sequence[Sequence[T]],
    *,
    key: Callable[[T], Hashable] | None = None,
    k: int = 60,
) -> dict[Hashable, float]:
    """返回多个排序列表的 RRF（倒数排名融合）分数。

    RRF 是信息检索领域经典的「分数不敏感」融合算法，核心思想是：
    - 不信任不同检索器返回的原始分数（向量相似度、BM25、TF-IDF 量纲完全不同）
    - 只利用「排名位置」信息：一个文档在多个列表中排名越靠前，融合分越高
    - 这避免了对不同检索器做分数校准/归一化的麻烦

    分数计算公式为 ``sum(1 / (k + rank))``，其中 ``rank`` 从 1 开始。
    参数 k 的作用是平滑排名靠前的文档的优势：k 越大，前几名之间的分差越小。
    信息检索学界经验值通常在 20~100 之间，默认 60 是常见的稳健选择。
    原始的向量/BM25 分数值会被有意忽略。

    示例：

        vector = ["A", "B", "C"]
        bm25 = ["B", "A", "D"]
        scores = reciprocal_rank_fusion([vector, bm25])
        # B 和 A 都获得两个列表的支持，排名高于 C/D。
    """

    # 参数合法性校验：k 为负数会导致公式分母可能为 0 或产生负分，语义不合理
    if k < 0:
        raise ValueError("k 必须为非负数")

    # 若调用方未提供 key 函数，则将元素自身作为唯一标识（要求元素可哈希）
    item_key = key or (lambda item: item)
    # 累积每个文档的融合得分的字典：key = 文档标识，value = 累计 RRF 分
    scores: dict[Hashable, float] = {}

    # 遍历每一条检索路径的排序结果
    for ranked_items in ranked_lists:
        # enumerate(..., start=1) 确保排名从 1 开始，符合 RRF 公式定义
        for rank, item in enumerate(ranked_items, start=1):
            # 提取文档的唯一标识（处理对象类型时，key 函数通常取 id 或 url 字段）
            item_id = item_key(item)
            # 累加：当前排名下的贡献值 = 1 / (k + rank)
            # 排名越靠前，rank 越小，该值越大；排名第1的文档贡献最大
            scores[item_id] = scores.get(item_id, 0.0) + 1.0 / (k + rank)

    return scores


@lru_cache(maxsize=2)
def _load_cross_encoder(model_name: str) -> Any | None:
    """延迟加载 CrossEncoder 模型并按模型名称缓存。

    为什么需要「延迟加载 + LRU 缓存」：
    1. **可选依赖**：sentence-transformers 依赖 PyTorch，非常重（数GB）。
       如果用户没启用重排功能，在模块 import 时就导入会导致启动慢、测试慢、
       甚至在没有 GPU/大内存的环境直接失败。延迟加载确保只有真正调用时才尝试导入。
    2. **缓存机制**：CrossEncoder 初始化会加载权重到内存/显存，非常耗时。
       使用 LRU 缓存（maxsize=2）可以缓存最近使用的 2 个模型实例，避免：
       - 同一次进程中多次调用 cross_encoder_rerank 时重复加载同一模型
       - 在中英文模型间切换时，不需要每次都重新下载和反序列化

    返回值说明：
    - 成功：返回 CrossEncoder 模型实例（类型标注为 Any，避免在未安装依赖时类型检查失败）
    - 失败（缺依赖/下载错/路径错）：返回 None，交由调用方走降级逻辑
    """

    # 第一层 try：尝试导入 sentence-transformers 包
    # 注意：import 写在函数内部而非文件顶部，实现真正的延迟加载
    try:
        from sentence_transformers import CrossEncoder
    except Exception:
        # 未安装依赖、版本冲突、CUDA 不可用等任何异常 → 加载失败
        return None

    # 第二层 try：尝试实例化模型（可能触发 HuggingFace 下载，或读取本地路径）
    try:
        return CrossEncoder(model_name)
    except Exception:
        # 典型失败场景：
        # - 网络不通无法下载模型
        # - 本地路径不存在或文件损坏
        # - 模型格式与当前 sentence-transformers 版本不兼容
        return None


def cross_encoder_rerank(
    query_text: str,
    chunks: Sequence[T],
    *,
    text_getter: Callable[[T], str],
    rule_score_getter: Callable[[T], float],
    score_setter: ScoreSetter[T],
    top_k: int,
    config: RerankerConfig | None = None,
    model: Any | None = None,
) -> list[T]:
    """启用时使用交叉编码器对规则排序后的候选结果进行重排序。

    这是 RAG 管道中「精排（rerank）」阶段的核心函数。完整流程通常是：
    1. 召回：向量搜索 + BM25 快速返回 ~100 个候选
    2. 粗排：基于关键词匹配、命中密度、文档新鲜度等规则打分排序
    3. 精排（本函数）：对粗排前 N 个用 CrossEncoder 模型做相关性打分 + 分数融合 + 最终排序

    为什么用 Callable 参数（text_getter / rule_score_getter / score_setter）？
    - 本模块不依赖上层的 chunk 数据结构定义（可能是 dataclass、ORM model、dict 等）
    - 通过注入 getter/setter 函数实现解耦，任何类型的文档块都能使用本函数
    - 这是典型的「依赖倒置」设计，保持 reranker 模块的独立性和可复用性

    ``model`` 参数可注入用于测试。生产环境调用者通常不设置此参数，
    以便延迟加载配置的 Hugging Face 模型。

    本函数采用安全失败策略（fail-safe）：缺少依赖、模型下载错误、无效预测结果
    以及推理错误都会返回原始排序。这一点很重要，因为重排序应当提升质量，
    而非导致 RAG 不可用——重排是锦上添花，不是不可缺少的一环。
    """

    # 将输入的 Sequence 转换为 list，确保支持切片和索引操作
    # （输入可能是 tuple、生成器包装的 Sequence 等不可切片类型）
    original = list(chunks)
    # 快速失败路径：不需要返回任何结果，或输入本身为空 → 直接返回空列表
    if top_k <= 0 or not original:
        return []

    # 确定本次使用的配置：
    # - 若调用方显式传入 config 则使用之（便于单测注入特定配置）
    # - 否则从环境变量读取构建
    # 并立即调用 normalized_weights() 再次确保权重有效（防止调用方构造的配置未归一化）
    active_config = (config or RerankerConfig.from_environment()).normalized_weights()
    # 降级路径 1：功能未启用 → 不做任何模型推理，直接按原始顺序返回前 top_k 个
    if not active_config.enabled:
        return original[:top_k]

    # 获取模型实例：
    # - 优先使用调用方注入的 model（测试场景：传入 FakeModel / Mock 对象）
    # - 否则走延迟加载逻辑（生产环境）
    active_model = model or _load_cross_encoder(active_config.model_name)
    # 降级路径 2：模型加载失败（缺依赖、下载失败等）→ 返回原始排序
    if active_model is None:
        return original[:top_k]

    # 计算实际送入模型的候选数量：
    # - 不能超过粗排结果总数（len(original)）
    # - 至少要达到 top_k（否则重排完也不够返回的数量）
    # - 不超过配置的 candidate_top_n（性能保护上限）
    # 即：取「候选总数」和「max(top_k, 配置候选上限)」中的较小值
    candidate_count = min(
        len(original),
        max(top_k, active_config.candidate_top_n),
    )
    # 截取前 candidate_count 个作为精排候选。注意：假设输入 chunks 已经是粗排后的有序列表
    candidates = original[:candidate_count]

    # 构造 CrossEncoder 的输入对：[[查询, 文档1], [查询, 文档2], ...]
    # CrossEncoder 的标准输入格式就是这种成对的文本列表，模型会对每一对输出一个 [0,1] 的相关度分
    pairs = [
        [query_text, text_getter(chunk).strip()]  # strip() 去除首尾空白，减少无效 token 占用
        for chunk in candidates
    ]
    # 降级路径 3：如果有任何一个文档的文本为空（可能是脏数据、解析失败的 chunk）
    # 模型可能报错或输出无意义结果，稳妥起见跳过本次重排
    if any(not pair[1] for pair in pairs):
        return original[:top_k]

    # 模型推理阶段，全面包裹 try-except 确保任何异常都不中断主流程
    try:
        # 优先尝试带 batch_size 参数的调用（标准 sentence-transformers API）
        try:
            raw_model_scores = active_model.predict(
                pairs,
                batch_size=active_config.batch_size,
            )
        except TypeError:
            # 兼容路径：某些自定义/旧版本的 predict 签名不接受 batch_size 参数
            # 此时回退到无参调用，让模型使用默认批大小
            raw_model_scores = active_model.predict(pairs)

        # 将模型输出统一转换为 Python float 列表
        # 模型可能返回 numpy.ndarray、torch.Tensor、list 等，统一成原生 float 便于后续运算
        model_scores = [float(value) for value in raw_model_scores]
    except Exception:
        # 降级路径 4：推理过程中发生任何异常（OOM、输入过长、类型错误等）
        # → 静默返回原始排序，不向上抛出异常
        return original[:top_k]

    # 降级路径 5：结果长度校验
    # 正常情况下模型应该对 N 个候选返回 N 个分数。如果长度不一致，
    # 说明 predict 返回结果异常（如批处理截断、形状不对），此时放弃使用模型结果
    if len(model_scores) != len(candidates):
        return original[:top_k]

    # --- 分数归一化与融合阶段 ---
    # 将模型分数（通常在 [-∞, +∞] 或 [0, 1] 之间）线性缩放到 [0, 1] 区间
    normalized_model_scores = _normalize_score_list(model_scores)
    # 将原有规则分数（可能是多种规则加权求和，范围不定）同样缩放到 [0, 1]
    # 这样两种分数处于同一量纲，加权融合才有意义
    normalized_rule_scores = _normalize_score_list(
        [float(rule_score_getter(chunk)) for chunk in candidates]
    )

    # 构造重排后的候选列表，逐个融合分数
    reranked_candidates: list[T] = []
    for chunk, model_score, rule_score in zip(
        candidates,
        normalized_model_scores,
        normalized_rule_scores,
    ):
        # 加权线性融合：最终分 = 模型权重×归一化模型分 + 规则权重×归一化规则分
        # 这样既能利用模型对语义相关性的精准判断，又能保留规则系统中的人工经验
        # （例如某些内部文档、FAQ 的强制提权、时间衰减因子等模型无法感知的信号）
        fused_score = (
            active_config.model_weight * model_score
            + active_config.rule_weight * rule_score
        )
        # 通过调用方注入的 setter 将融合分数写回 chunk 对象
        # round(..., 6) 将分数保留 6 位小数，减少浮点噪声对排序稳定性的影响
        reranked_candidates.append(score_setter(chunk, round(fused_score, 6)))

    # --- 双排序确保稳定性 ---
    # 第一轮排序：以原始规则分数降序排
    # 这是为了让「final_score 相同」的候选之间，保持与规则排序一致的相对顺序
    # （Python 的 sort 是稳定排序，先排的字段在后续排序相同时会保留原有顺序）
    reranked_candidates.sort(
        key=lambda chunk: float(rule_score_getter(chunk)),
        reverse=True,
    )
    # 第二轮排序：以融合后的 final_score 降序排（主排序）
    # 使用 getattr(chunk, "final_score", 0.0) 而非直接从 fused_score 读取，
    # 是为了依赖 score_setter 的实际写入行为，避免 getter/setter 逻辑不一致
    reranked_candidates.sort(
        key=lambda chunk: getattr(chunk, "final_score", 0.0),
        reverse=True,
    )

    # 拼接与截断：
    # - 前半部分是已经精排好的 candidate_count 个高质量候选
    # - 后半部分补充原始列表中未参与精排的剩余部分（按粗排顺序保留）
    # - 最后统一截断到 top_k 个结果返回
    # 这样设计保证即使 candidate_top_n > top_k，返回的全都是精排过的；
    # 而如果 top_k > candidate_top_n（极端配置），不足的部分也能用粗排结果补齐
    return (reranked_candidates + original[candidate_count:])[:top_k]


def _normalize_score_list(scores: Sequence[float]) -> list[float]:
    """对一组分数做最小-最大归一化（Min-Max Normalization），线性缩放到 [0, 1] 区间。

    归一化公式：new_score = (score - min) / (max - min)

    处理边界情况：
    - 空列表：直接返回空列表
    - 所有分数相同（max <= min）：此时分母为 0，公式无法计算
      → 全部赋值为 0.5（中点值），表示它们在归一化视角下没有差别，
        避免融合时因某个分数维度完全相同而导致另一维权重被放大。
    """
    # 空列表直接返回，避免后续 min()/max() 报错
    if not scores:
        return []

    # 求最小值和最大值，确定原始分数的范围
    minimum = min(scores)
    maximum = max(scores)
    # 边界情况：所有分数相同（或异常的 max < min）→ 返回全 0.5
    if maximum <= minimum:
        return [0.5 for _ in scores]

    # 标准线性缩放到 [0, 1]：最小值映射到 0，最大值映射到 1，中间线性插值
    return [
        (score - minimum) / (maximum - minimum)
        for score in scores
    ]


def _env_bool(name: str) -> bool:
    """读取布尔型环境变量的辅助函数。

    支持常见的「真值」写法（大小写不敏感）：'1', 'true', 'yes', 'on'
    其他任何值（包括未设置时的默认 '0'）都视为 False。

    这种宽松的解析方式避免了用户因大小写或写法不同（TRUE vs True vs true）
    导致配置不生效的常见坑。
    """
    return os.getenv(name, "0").strip().lower() in {
        "1",
        "true",
        "yes",
        "on",
    }


def _env_int(name: str, default: int) -> int:
    """读取整型环境变量的辅助函数。

    - 未设置环境变量时返回 default
    - 设置了但解析失败（非数字字符串）时同样返回 default（而不是抛出异常）
      → 遵循 fail-soft 原则，单个配置错误不至于让整个系统启动失败
    """
    try:
        return int(os.getenv(name, str(default)))
    except (TypeError, ValueError):
        # TypeError：os.getenv 极少数情况返回 None（虽然文档是 str|None）
        # ValueError：环境变量值不是合法的整数（如 "abc"、空字符串）
        return default


def _bounded_float(name: str, default: float) -> float:
    """读取有界浮点型环境变量的辅助函数（结果限制在 [0.0, 1.0] 区间内）。

    专门用于读取权重类配置：
    1. 同 _env_int，解析失败返回默认值
    2. 额外裁剪到 [0, 1] 范围，防止用户配置超出合理区间的权重（如 2.0、-0.5）
       - 小于 0 → 钳制为 0
       - 大于 1 → 钳制为 1
    这是「防御式编程」的体现：不信任外部输入，即使配置错误也能产生合理行为。
    """
    try:
        value = float(os.getenv(name, str(default)))
    except (TypeError, ValueError):
        # 解析失败 → 回退到默认值
        return default

    # 使用 min(max(...)) 经典模式做区间裁剪
    return min(1.0, max(0.0, value))