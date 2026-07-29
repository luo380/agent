import json
import math
import re
from dataclasses import dataclass
from collections import Counter
from sqlalchemy import Sequence
from sqlalchemy.orm import Session

from core.db.models import (
    KnowledgeChunks,
    KnowledgeDocuments,
    KNOWLEDGE_CHUNK_ROLE_LEAF,
    KNOWLEDGE_CHUNK_ROLE_PARENT,
)
from core.service.vector_index import rebuild_user_faiss_index, search_user_faiss_index
from core.service.rag_grounding import evidence_match_score


"""
它是 RAG 的“检索中间层”负责把“用户问题”变成“可用的知识块候选”，不负责生成答案。
简单说它做这几件事：
读知识库 chunk 和 embedding
做向量召回 / 关键词召回 / 混合召回
计算分数、去重、重排
返回 RetrievedChunk 给 rag.py 去拼上下文
所以它的位置是：embed_text 之后，LLM 之前
"""
# 简单分词：中英文数字都保留
LATIN_TOKEN_RE = re.compile(r"[A-Za-z0-9]+")
CJK_TOKEN_RE = re.compile(r"[\u4e00-\u9fff]+")

@dataclass
class RetrievedChunk:
    # ===== 一、核心标识字段（文档与块的基本信息）=====
    # 所属文档的ID，关联知识库中的具体文档
    document_id: int
    # 所属文档的名称/标题
    document_name: str
    # 知识块自身的唯一ID
    chunk_id: int
    # 该块在文档中的顺序索引（第几个块）
    chunk_index: int
    # 知识块的实际文本内容
    content: str
    # 来源页码（PDF等文档可能有页码，纯文本可能为None）
    source_page: int | None
    # 来源章节/标题，用于溯源到文档的具体章节
    source_section: str

    # ===== 二、检索与向量化相关字段 ======
    # 向量嵌入的JSON序列化字符串，用于存储向量数据
    embedding_json: str = ""
    # 检索时使用的内容（可能与原始content不同，如经过清洗、摘要或增强处理）
    retrieval_content: str = ""

    # ===== 三、层级结构字段（父子块关系，支持分层检索策略）=====
    # 块的角色：叶子节点(LEAF最小块)或父节点(PARENT大块)，默认是叶子块
    chunk_role: str = KNOWLEDGE_CHUNK_ROLE_LEAF
    # 父块的ID，用于关联到更大的上下文块
    parent_chunk_id: int | None = None
    # 父块的标题/名称
    parent_title: str = ""
    # 块类型：如文本(text)、表格(table)、图片等，默认是文本
    block_type: str = "text"
    # 在父块中的子块索引位置
    child_index: int = 0
    # 如果是表格块：起始行号
    table_row_from: int | None = None
    # 如果是表格块：结束行号
    table_row_to: int | None = None

    # ===== 四、评分字段（多路召回融合）=====
    # 向量检索得分：基于语义相似度的分数（FAISS等向量库返回）
    vector_score: float = 0.0
    # 关键词检索得分：基于BM25/TF-IDF等关键词匹配的分数
    keyword_score: float = 0.0
    # 最终得分：向量分+关键词分加权融合后的总分，用于最终排序
    final_score: float = 0.0

    # ===== 五、临时辅助字段（不落库，仅检索阶段使用）=====
    # 用来记录当前parent context是由哪个leaf命中的，
    # 方便rerank重排序时保留小块命中的精确信号，避免合并父块后丢失原始命中位置
    matched_child_content: str = ""



def _recall_text(chunk: RetrievedChunk) -> str:
    """
    检索阶段实际使用的文本。

    原则：
    - 如果有 retrieval_content，就优先用它
    - 否则退回 content
    """
    return (chunk.retrieval_content or chunk.content or "").strip()



# 参数 raw 可以是三种类型之一：字符串、浮点数列表，或 None
def parse_embedding(raw: str | list[float] | None) -> list[float]:
    # 数据库里通常存 JSON 字符串，这里转回 list[float]
    if raw is None:
        return []
    # 判断输入参数 raw 是否是一个 list（列表）类型
    if isinstance(raw, list):
        return [float(value) for value in raw]
    # 转成字符串并清理首尾空白
    text = str(raw).strip()
    if not text:
        return []

    try:
        # 使用 json.loads() 将字符串 text 解析为 Python 对象（如列表或字典）
        data = json.loads(text)
    except json.JSONDecodeError:
        return []
    if not isinstance(data, list):
        return []

    return [float(value) for value in data]


# 计算余弦相似度
def cosine_similarity(a: list[float], b: list[float]) -> float:
    # 最基础的向量相似度
    if not a or not b or len(a) != len(b):
        return 0.0

    dot_product = sum(x * y for x, y in zip(a, b))
    norm_a = math.sqrt(sum(x * x for x in a))
    norm_b = math.sqrt(sum(y * y for y in b))
    if not norm_a or not norm_b:
        return 0.0

    return dot_product / (norm_a * norm_b)


# 简单分词：中英文数字都保留
def _generate_cjk_ngrams(text: str, *, min_size: int = 2, max_size: int = 4) -> set[str]:
    clean_text = (text or "").strip()
    if not clean_text:
        return set()

    max_window = min(max_size, len(clean_text))
    if max_window < min_size:
        return {clean_text} if clean_text else set()

    ngrams: set[str] = set()
    for window_size in range(min_size, max_window + 1):
        for start in range(0, len(clean_text) - window_size + 1):
            ngrams.add(clean_text[start:start + window_size])
    return ngrams


def tokenize(text: str) -> set[str]:
    # Used by rerank for mixed Chinese and English queries
    normalized_text = (text or "").lower()
    tokens = {token for token in LATIN_TOKEN_RE.findall(normalized_text) if token}

    for token in CJK_TOKEN_RE.findall(normalized_text):
        clean_token = token.strip()
        if not clean_token:
            continue
        tokens.add(clean_token)
        tokens.update(_generate_cjk_ngrams(clean_token))

    return tokens


#
def _tokenize_for_bm25(text: str) -> list[str]:
    # 先转换为小写
    normalized_text  = (text or "").lower()
    # 声明变量名字为tokens 他的数据类型是list数组，值为空列表
    tokens: list[str] = []
    tokens.extend(token for token in LATIN_TOKEN_RE.findall(normalized_text) if token)
    for token in CJK_TOKEN_RE.findall(normalized_text):
        clean_token = token.strip()
        if not clean_token:
            continue
        tokens.append(clean_token)
        tokens.extend(sorted(_generate_cjk_ngrams(clean_token)))

    return tokens


# 归一化得分映射
def _normalize_score_map(score_map: dict[int, float]) -> dict[int, float]:
    if not score_map:
        return score_map

    max_score = max(score_map.values())
    if max_score <= 0:
        return {key: 0.0 for key in score_map}

    return {
        key: round(value / max_score, 6)
        for key, value in score_map.items()
    }


def bm25_search(
    # SQLAlchemy数据库会话对象，用于查询知识块数据
    db: Session,
    # 独立参数分隔符：强制后续参数必须以关键字形式传递
    *,
    # 用户ID：限定只在该用户的知识库中搜索（数据权限）
    user_id: int,
    # 用户的查询文本（问题），用于BM25关键词匹配评分
    query_text: str,
    # 可选：限定只搜索某些文档（None表示搜索用户所有文档）
    document_ids: Sequence[int] | None = None,
    # 最终返回的结果数量上限（Top K）
    top_k: int = 10,
    # BM25超参数k1：控制词频饱和度（通常取1.2~2.0，越大词频权重越高）
    k1: float = 1.5,
    # BM25超参数b：文档长度归一化强度（0~1，b=0完全不归一化，b=1完全归一化）
    b: float = 0.75,
) -> list[RetrievedChunk]:
    """
    【BM25关键词检索】使用经典的Okapi BM25算法对用户知识库进行纯关键词检索。

    算法简介：
        BM25是信息检索领域最经典的排序算法之一，是TF-IDF的进化版，核心改进点：
        1. 词频饱和度（k1参数）：词出现10次≠10倍权重，达到阈值后收益递减
        2. 文档长度归一化（b参数）：长文档词多但不代表更相关，会按平均文档长度惩罚
        3. IDF逆文档频率：稀有词匹配权重 >> 常见词匹配权重

    评分公式（每个查询词累加）：
        score = Σ IDF(qᵢ) × [ f(qᵢ,D) × (k1+1) ] / [ f(qᵢ,D) + k1 × (1 - b + b × |D|/avgdl) ]
        其中：
        - IDF(qᵢ)   = log(1 + (N - n(qᵢ) + 0.5) / (n(qᵢ) + 0.5))
        - f(qᵢ,D)    = 查询词qᵢ在文档D中的出现次数（TF词频）
        - |D|        = 当前文档D的长度（token数）
        - avgdl      = 所有候选文档的平均长度
        - N          = 候选文档总数
        - n(qᵢ)      = 包含查询词qᵢ的文档数（DF文档频率）

    【与向量检索的区别】
        ┌──────────────┬──────────────────────────┬──────────────────────────┐
        │ 检索方式      │ BM25关键词检索            │ FAISS向量检索            │
        ├──────────────┼──────────────────────────┼──────────────────────────┤
        │ 匹配方式      │ 字面量精确匹配（必须出现） │ 语义相似匹配（同义可匹配）│
        │ 擅长场景      │ 专有名词、型号、精确术语  │ 自然语言问题、模糊描述    │
        │ 典型缺点      │ 同义词/近义词无法匹配     │ 精确关键词匹配弱         │
        └──────────────┴──────────────────────────┴──────────────────────────┘
        → 实际生产中通常使用「BM25 + 向量」混合检索（多路召回融合），效果最好！

    【例子】搜索「小爱同学连接WiFi」
    假设用户知识库有3个候选chunk：
    ┌────────┬────────────────────────────────────────────────────┬────────┐
    │chunk_id│ content                                            │ 长度   │
    ├────────┼────────────────────────────────────────────────────┼────────┤
    │ A(101) │ 小爱同学是小米的智能音箱，可以连接WiFi蓝牙。小爱…  │ 120词 │
    │ B(102) │ WiFi连接常见问题：路由器重启、检查密码、重置…     │ 200词 │
    │ C(103) │ 天猫精灵如何接入蓝牙音箱播放音乐…                 │ 90词  │
    └────────┴────────────────────────────────────────────────────┴────────┘
    查询分词query_tokens = ["小爱", "同学", "连接", "wifi"]

    第一步：统计全局数据（遍历所有chunk）
        total_docs = 3（共3篇文档）
        avgdl = (120+200+90)/3 ≈ 136.7（平均文档长度）
        doc_freq（每个词出现在多少篇文档中）：
            "小爱"   → 出现在A → df=1
            "同学"   → 出现在A → df=1
            "连接"   → 出现在A,B → df=2
            "wifi"   → 出现在A,B → df=2

    第二步：逐文档计算BM25分
    ┌─────────────────────────────────────────────────────────────────────┐
    │ 文档A(101)：长度=120，词频：小爱×2，同学×2，连接×1，wifi×1        │
    ├─────────────────────────────────────────────────────────────────────┤
    │  IDF("小爱")  = log(1+(3-1+0.5)/(1+0.5)) = log(1+2.5/1.5) ≈ 0.9808│
    │  词频部分 = [2×2.5] / [2+1.5×(1-0.75+0.75×120/136.7)]
    │           = 5.0 / [2+1.5×(0.25+0.6584)] = 5.0 / [2+1.3626] ≈ 1.487│
    │  → 小爱贡献：0.9808 × 1.487 ≈ 1.459
    │  同理：同学贡献≈1.459，连接贡献≈0.378，wifi贡献≈0.378
    │  A总分 ≈ 1.459 + 1.459 + 0.378 + 0.378 = 3.674 ←【最高】          │
    └─────────────────────────────────────────────────────────────────────┘
    ┌─────────────────────────────────────────────────────────────────────┐
    │ 文档B(102)：长度=200，只有「连接」「wifi」各出现1次                │
    ├─────────────────────────────────────────────────────────────────────┤
    │  小爱/同学 → TF=0，贡献0分
    │  连接：IDF≈0.405，词频部分≈0.458 → 贡献≈0.186
    │  wifi：IDF≈0.405，词频部分≈0.458 → 贡献≈0.186
    │  B总分 ≈ 0.372
    └─────────────────────────────────────────────────────────────────────┘
    文档C(103)：无任何查询词 → 0分，过滤

    第三步：排序并取Top K=2
        返回 [chunkA(keyword_score=3.674), chunkB(keyword_score=0.372)]
    """

    # ===== 步骤1：加载用户所有候选叶子块（通过load_user_chunks，限定user_id和可选document_ids）=====
    candidates = load_user_chunks(db, user_id=user_id, document_ids=document_ids)
    # ===== 步骤2：对用户查询文本分词 =====
    # _tokenize_for_bm25(query_text) 会把查询文本分词成token列表（支持中英混合+CJK n-gram）
    # dict.fromkeys(...) 的作用：按原始顺序去除重复的token（因为BM25里查询词重复不增加分数）
    # 例如：查询"小爱小爱同学" → 分词["小爱","小爱","同学"] → 去重后["小爱","同学"]
    query_tokens = list(dict.fromkeys(_tokenize_for_bm25(query_text)))
    # 快速通道：没有候选文档 或 查询分词为空 → 直接返回空列表
    if not candidates or not query_tokens:
        return []

    # ===== 步骤3：预处理所有候选文档，构建3个关键统计量 =====
    """
    prepared_docs 列表中每个元素是一个三元组：
    list[tuple[RetrievedChunk, list[str], Counter[str]]]
     ↑      ↑               ↑            ↑
     │      │               │            └── 词频统计Counter：每个token在文档中出现的次数
     │      │               └─────────────── 分词后的token列表
     │      └─────────────────────────────── 原始知识块对象RetrievedChunk
     └────────────────────────────────────── 外层是列表，装所有候选文档
    """
    # 预处理后的候选文档列表：每个元素=(chunk对象, 分词tokens, 词频Counter)
    prepared_docs: list[tuple[RetrievedChunk, list[str], Counter[str]]] = []
    # doc_freq：文档频率计数器，记录「每个词出现在多少个不同文档中」（用于计算IDF）
    doc_freq: Counter[str] = Counter()
    # total_doc_len：所有候选文档的token总数，用于计算平均文档长度avgdl
    total_doc_len = 0

    # 遍历每个候选chunk，完成3件事：分词、统计词频、累加全局统计
    for chunk in candidates:
        # 对当前文档的检索文本进行分词
        doc_tokens = _tokenize_for_bm25(_recall_text(chunk))
        # 文档分词后为空（可能是图片块或空内容）→ 跳过不参与评分
        if not doc_tokens:
            continue

        # tf_counter：当前文档内部的词频统计（每个词在本文档出现多少次）
        tf_counter = Counter(doc_tokens)
        # 将「块对象+tokens+词频」打包加入预处理列表
        prepared_docs.append((chunk, doc_tokens, tf_counter))
        # 累加总文档长度（用于计算avgdl）
        total_doc_len += len(doc_tokens)
        # doc_freq更新：使用set(doc_tokens)去重后再update，保证「一个词在同一文档不管出现多少次，DF只+1」
        # 这很关键！因为DF表示「有多少篇文档包含该词」，与单篇内出现次数无关
        doc_freq.update(set(doc_tokens))

    # 所有候选文档分词后都是空 → 直接返回空
    if not prepared_docs:
        return []

    # ===== 步骤4：计算BM25需要的全局参数 =====
    # total_docs：参与评分的文档总数
    total_docs = len(prepared_docs)
    # avgdl：平均文档长度（所有文档token总数 ÷ 文档数），用于长度归一化
    # 这里加了安全除法，防止total_docs=0时分母为0（虽然前面已检查过）
    avg_doc_len = total_doc_len / total_docs if total_docs else 0.0
    # 平均文档长度非正数（异常情况）→ 返回空
    if avg_doc_len <= 0:
        return []

    # 保存评分结果
    results: list[RetrievedChunk] = []


    # ===== 步骤5：逐文档计算BM25最终得分 =====
    # 遍历每个预处理好的文档三元组：(块对象, 分词tokens, 词频Counter)
    for chunk, doc_tokens, tf_counter in prepared_docs:
        # 当前文档的长度（token数）
        doc_len = len(doc_tokens)
        # 当前文档的BM25得分，初始为0，累加每个查询词的贡献
        score = 0.0

        # 遍历每个去重后的查询词，累加每个词对本文档的BM25贡献分
        for term in query_tokens:
            # tf：该查询词在【当前文档】中的出现次数（词频），不存在则为0
            tf = tf_counter.get(term, 0)
            # 词频为0 → 该查询词不在本文档中 → 跳过不贡献分数
            if tf <= 0:
                continue

            # df：该查询词在【所有候选文档】中出现的文档数（文档频率），不存在则为0
            df = doc_freq.get(term, 0)
            # ─────────────────────────────────────────────────
            # IDF计算：逆文档频率（稀有词 → IDF大，常见词 → IDF小）
            # 公式：log(1 + (N - df + 0.5) / (df + 0.5))
            # 其中+0.5是Laplace平滑项，防止df=0时分母为0或出现极端值
            # ─────────────────────────────────────────────────
            idf = math.log(1 + ((total_docs - df + 0.5) / (df + 0.5)))
            # ─────────────────────────────────────────────────
            # BM25分母部分：融合词频饱和度+文档长度归一化
            # denom = tf + k1 × (1 - b + b × (doc_len/avgdl))
            #   - 文档越长 → (doc_len/avgdl) > 1 → 分母变大 → 惩罚长文档
            #   - 文档越短 → (doc_len/avgdl) < 1 → 分母变小 → 奖励短文档
            #   - k1控制词频饱和度，b控制长度归一化强度
            # ─────────────────────────────────────────────────
            denom = tf + k1 * (1 - b + b * (doc_len / avg_doc_len))
            # ─────────────────────────────────────────────────
            # 累加该查询词的贡献分：IDF × [ tf×(k1+1) / denom ]
            # 分子 tf×(k1+1) 保证分子比分母中tf项大一些，配合分母实现「词频饱和度」效果：
            # tf从1→2时提升明显，tf从10→11时几乎无提升（类似log曲线）
            # ─────────────────────────────────────────────────
            score += idf * ((tf * (k1 + 1)) / denom)

        # 得分≤0（没有任何查询词命中）→ 不加入结果，相当于过滤完全不相关的文档
        if score <= 0:
            continue


        # 构造带有BM25 keyword_score的RetrievedChunk，加入结果列表
        results.append(
            RetrievedChunk(
                # —— 基础标识字段（直接拷贝原chunk）——
                document_id=chunk.document_id,
                document_name=chunk.document_name,
                chunk_id=chunk.chunk_id,
                chunk_index=chunk.chunk_index,
                content=chunk.content,
                source_page=chunk.source_page,
                source_section=chunk.source_section,
                # —— 检索&向量字段 ——
                embedding_json=chunk.embedding_json,
                retrieval_content=chunk.retrieval_content,
                # —— 层级结构字段 ——
                chunk_role=chunk.chunk_role,
                parent_chunk_id=chunk.parent_chunk_id,
                parent_title=chunk.parent_title,
                block_type=chunk.block_type,
                child_index=chunk.child_index,
                table_row_from=chunk.table_row_from,
                table_row_to=chunk.table_row_to,
                # ⭐关键字段：BM25算法计算出的关键词得分，四舍五入保留6位小数
                keyword_score=round(score, 6),
            )
        )
    # ===== 步骤6：按keyword_score降序排序，取Top K返回 =====
    # 排序优先级：
    #   1. keyword_score（BM25关键词分，越高越好）→ 最优先
    #   2. chunk_index（文档内块序号，越小越靠前）→ 分数相同时，文档靠前的块优先（保证排序稳定性）
    results.sort(
        key=lambda item: (item.keyword_score, item.chunk_index),
        reverse=True,
    )
    # 取Top K结果返回；如果结果数不足top_k，Python切片自动取全部，不会报错
    return results[:top_k]


# ============================================================
# 混合搜索 (Hybrid Search)
# 将 FAISS 向量检索（语义相似度）与 BM25 关键词检索（符号匹配）
# 进行加权融合，兼顾"含义相近"和"关键词命中"，获得更好的检索效果
# ============================================================
def hybrid_search(
    # SQLAlchemy数据库会话对象，用于所有DB操作
    db: Session,
    # 独立参数分隔符：强制后续参数必须以关键字形式传递
    *,
    # 用户ID：数据权限过滤，只在该用户的知识库中检索
    user_id: int,
    # 用户的原始查询文本（问题），用于BM25关键词检索+关键词奖励分计算
    query_text: str,
    # 查询文本的embedding向量（调用方已计算好），用于FAISS向量语义检索
    query_embedding: list[float],
    # 可选：限定只搜索指定文档，None表示搜索用户全部知识库文档
    document_ids: Sequence[int] | None = None,
    # 最终期望返回的结果数量（Top K）
    top_k: int = 10,
    # 向量相似度分的权重（混合融合时，语义分占比，默认65%）
    vector_weight: float = 0.65,
    # BM25关键词分的权重（混合融合时，字面匹配分占比，默认35%）
    bm25_weight: float = 0.35,
) -> list[RetrievedChunk]:
    """
    【混合检索核心入口】RAG系统的主检索函数，向量检索 + BM25关键词检索 双路召回融合。

    整体架构（两层Pipeline）：
    第一层：Leaf层混合召回（精搜小块）
      FAISS向量检索 -> 失败时降级为暴力余弦计算   （语义相似匹配）
      BM25关键词检索                                  （字面精确匹配）
      两路分数归一化（统一到[0,1]区间）-> 加权求和融合 （权重默认 65%:35%）
      按final_score降序 -> 粗排后取 Top 3K 个leaf
    第二层：Small-to-Big 父块扩展（补全上下文）
      调用 _expand_leaf_hits_to_parent_context，把leaf命中扩展为parent大块上下文
      返回 Top 2K 个父块结果给RAG（给LLM的是完整大块上下文，不是零碎小块）

    为什么召回阶段取「4倍放大」再逐层缩减？（漏斗策略）
        Leaf召回取4K -> 融合后粗排截3K -> 扩展parent后截2K -> 最终调用方再截top_k
        目的：(1) 保证召回率（第一阶段多捞，别漏好结果）
              (2) 后续rerank精排阶段有足够候选可以择优
              (3) 逐层收敛，计算量可控

    【完整例子】用户搜索「怎么用Python读取PDF内容？」，top_k=5，默认权重65%:35%
    步骤0：参数计算：top_k=5 -> leaf_recall_top_k = max(5x4, 5) = 20（leaf层召20条）

    步骤1：两路并行召回（各取20条，这里只展示前几条示例）
    (1) FAISS向量召回（语义匹配）vector_hits前4条：
      chunk_id=1  content="Python用PyPDF2读取PDF：import PyPDF2"  vector_score=0.91
      chunk_id=2  content="使用pdfplumber库解析PDF表格内容..."    vector_score=0.85
      chunk_id=3  content="Java使用iText库操作PDF..."              vector_score=0.62  <- Java非Python，语义弱相关
      chunk_id=4  content="Python的open函数读txt文件..."          vector_score=0.55  <- txt不是PDF，弱相关
    （假设FAISS正常，不走暴力降级分支）

    (2) BM25关键词召回（字面匹配）bm25_hits前4条：
      chunk_id=1  keyword_score=4.52  <- "Python""读取""PDF""内容" 全命中，满分！
      chunk_id=5  keyword_score=3.18  <- "Python批量处理PDF附件..." 命中3个关键词
      chunk_id=6  keyword_score=1.20  <- "PDF文件太大怎么压缩？" 只命中"PDF"
      chunk_id=3  keyword_score=0.85  <- 只有"PDF"命中，"Java"不命中"Python"
    （注意：chunk_id=3 两路都命中了，后面要融合去重）

    步骤2：构建分数字典 + 归一化到[0,1]区间
    vector_score_map = {1:0.91, 2:0.85, 3:0.62, 4:0.55, ...}
    bm25_score_map   = {1:4.52, 5:3.18, 6:1.20, 3:0.85, ...}

    为什么要归一化？-> 向量分范围(0~1) vs BM25分范围(0~10+) 量纲完全不同！
      不归一化的话，BM25随便一条4分的就能碾压所有向量分，混合权重完全失效。
      归一化后两路分都在[0,1]，权重配比才有意义。

    归一化（min-max归一化，假设min=0时直接除max）：
    vector_norm_map：
      chunk1=0.91/0.91=1.000  chunk2=0.85/0.91=0.934
      chunk3=0.62/0.91=0.681  chunk4=0.55/0.91=0.604
    bm25_norm_map：
      chunk1=4.52/4.52=1.000  chunk5=3.18/4.52=0.704
      chunk6=1.20/4.52=0.265  chunk3=0.85/4.52=0.188

    步骤3：两路结果取并集去重 + 加权融合计算final_score
    合并后共有6个不同的chunk：{1,2,3,4,5,6}
    融合公式：final_score = 向量归一化分 x 0.65 + BM25归一化分 x 0.35

    chunk_id 1: vector=1.000, bm25=1.000 -> 1x0.65 + 1x0.35 = 1.000 <- 最高！双命中
    chunk_id 2: vector=0.934, bm25=0     -> 0.934x0.65 + 0 = 0.607
    chunk_id 3: vector=0.681, bm25=0.188 -> 0.681x0.65 + 0.188x0.35 = 0.508
    chunk_id 4: vector=0.604, bm25=0     -> 0.393
    chunk_id 5: vector=0    , bm25=0.704 -> 0.704x0.35 = 0.246
    chunk_id 6: vector=0    , bm25=0.265 -> 0.093 (>0，保留)

    步骤4：排序 + 粗排截选 Top 3K 个leaf（top_k=5 -> max(15,5)=15）
    排序优先级：(final_score, vector_score, keyword_score, -chunk_index) 降序
    排序后：chunk1(1.000) -> chunk2(0.607) -> chunk3(0.508) -> chunk4(0.393) -> chunk5(0.246) -> chunk6(0.093)
    取前15条（只有6条就全取）-> leaf_hits = [chunk1,chunk2,chunk3,chunk4,chunk5,chunk6]

    步骤5：Small-to-Big 扩展为父块上下文（返回给RAG的最终结果）
    调用 _expand_leaf_hits_to_parent_context(leaf_hits=上面6条, top_k = max(5x2,5)=10)
    -> 把6个leaf（小块）按parent_id分组，加载对应PARENT大块（大块完整上下文），
      同组多leaf聚合取max分数，最终返回parent大块列表（最多10条，给LLM的都是大块内容）

    融合效果对比：
        只用向量检索：chunk5（Python批量PDF）没捞到（纯关键词精确匹配的漏了）
        只用BM25检索：chunk2（pdfplumber语义相关）没捞到（关键词弱但语义强的漏了）
        混合检索65%:35% -> chunk1（双命中）排第一，语义强的chunk2跟上，关键词命中的chunk5也捞到了
        这就是「混合检索」的威力：兼顾语义相似度 + 关键词精确匹配！
    """
    # 漏斗策略第一级放大：Leaf层召回数量 = top_k x 4
    # 为什么x4？第一层召回要「宁滥勿缺」，多捞候选保证召回率，
    # 后续融合、排序、扩展parent时再层层筛选收敛。max(top_kx4, top_k) 保证 top_k=1 时也至少取1条。
    leaf_recall_top_k = max(top_k * 4, top_k)

    # ===== 第一步：向量检索（语义相似度召回） =====
    # 优先走 FAISS 高效向量索引检索（O(logN) 复杂度，适合大规模知识库）
    vector_hits = _search_similar_chunks_by_faiss(
        db,
        user_id=user_id,
        query_embedding=query_embedding,  # 用户查询的embedding向量
        query_text=query_text,            # 原始查询文本（内部还要算关键词奖励分）
        document_ids=document_ids,
        top_k=leaf_recall_top_k,          # 召回放大后的leaf数量
    )
    # 降级分支：FAISS索引不存在/损坏/加载失败时，回退到暴力余弦计算
    # 这是生产环境的高可用设计：索引坏了也能用，只是从O(logN)降级到O(N)暴力遍历，慢一点但服务不中断
    if vector_hits is None:
        vector_hits = _search_similar_chunks_by_bruteforce(
            db,
            user_id=user_id,
            query_embedding=query_embedding,
            query_text=query_text,
            document_ids=document_ids,
            top_k=leaf_recall_top_k,
        )

    # ===== 第二步：BM25关键词检索（字面精确匹配召回） =====
    # 与向量检索形成互补：向量检索擅长「同义词/语义近似」，BM25擅长「专有名词/精确术语/型号」
    bm25_hits = bm25_search(
        db,
        user_id=user_id,
        query_text=query_text,            # 原始查询文本（用于分词+BM25评分）
        document_ids=document_ids,
        top_k=leaf_recall_top_k,
    )

    # ===== 第三步：构建两路原始分数字典（key=chunk_id，方便O(1)查找） =====
    # 向量分来自 vector_hits，每个命中chunk对应的原始vector_score
    vector_score_map = {chunk.chunk_id: float(chunk.vector_score) for chunk in vector_hits}
    # 关键词分来自 bm25_hits，每个命中chunk对应的原始BM25 keyword_score
    bm25_score_map = {chunk.chunk_id: float(chunk.keyword_score) for chunk in bm25_hits}

    # ===== 第四步：两路分数分别归一化到 [0, 1] 区间 =====
    # 为什么必须归一化？
    #   向量分范围通常是 [0,1]（余弦相似度），而 BM25 分范围通常是 [0, 10+]（取决于文档库大小）
    #   量纲完全不同，如果直接加权，BM25 5分的权重x0.35=1.75 会完全碾压向量分最大才0.65的贡献，
    #   导致「vector_weight/bm25_weight」两个参数完全失效，混合权重配比失去意义。
    #   归一化后两路都在 [0,1]，权重配比才真正按预期生效。
    vector_norm_map = _normalize_score_map(vector_score_map)
    bm25_norm_map = _normalize_score_map(bm25_score_map)

    # ===== 第五步：两路结果取并集去重（按chunk_id合并） =====
    # merged_map: key=chunk_id, value=RetrievedChunk对象（优先保留vector_hits中的，因为有embedding等全量字段）
    merged_map: dict[int, RetrievedChunk] = {}
    # 先塞向量检索的结果（vector检索有完整字段，优先级高）
    for chunk in vector_hits:
        merged_map[chunk.chunk_id] = chunk
    # 再塞BM25的结果：setdefault表示「只有该chunk_id不在字典里时才塞」，
    # 即：同一个chunk如果两路都命中，保留vector版本（字段更全，vector_score有值），BM25版本不覆盖
    for chunk in bm25_hits:
        merged_map.setdefault(chunk.chunk_id, chunk)

    # 保存融合后、带有final_score的leaf命中结果列表
    merged_leaf_hits: list[RetrievedChunk] = []

    # ===== 第六步：遍历去重后的每个chunk，计算加权融合final_score =====
    for chunk_id, chunk in merged_map.items():
        # 取该chunk在向量检索中的归一化分（如果向量没捞到，默认0分）
        normalized_vector_score = vector_norm_map.get(chunk_id, 0.0)
        # 取该chunk在BM25检索中的归一化分（如果BM25没捞到，默认0分）
        normalized_bm25_score = bm25_norm_map.get(chunk_id, 0.0)
        # 加权融合：向量分 x 向量权重 + BM25分 x BM25权重
        # 默认权重 65% 向量 + 35% BM25：兼顾语义（向量）和精确匹配（BM25），是业界常用黄金比例
        hybrid_score = round(
            (normalized_vector_score * vector_weight)
            + (normalized_bm25_score * bm25_weight),
            6,  # 保留6位小数，避免浮点精度问题导致排序抖动
        )

        # 融合分<=0 -> 两路都完全没命中（理论上不会发生，因为merged_map里的元素至少命中一路），安全跳过
        if hybrid_score <= 0:
            continue

        # 构造融合后的RetrievedChunk对象：保留所有字段，关键3个评分字段替换为「归一化后的值+融合分」
        merged_leaf_hits.append(
            RetrievedChunk(
                # 基础标识/检索/层级字段：原封不动拷贝
                document_id=chunk.document_id,
                document_name=chunk.document_name,
                chunk_id=chunk.chunk_id,
                chunk_index=chunk.chunk_index,
                content=chunk.content,
                source_page=chunk.source_page,
                source_section=chunk.source_section,
                embedding_json=chunk.embedding_json,
                retrieval_content=chunk.retrieval_content,
                chunk_role=chunk.chunk_role,
                parent_chunk_id=chunk.parent_chunk_id,
                parent_title=chunk.parent_title,
                block_type=chunk.block_type,
                child_index=chunk.child_index,
                table_row_from=chunk.table_row_from,
                table_row_to=chunk.table_row_to,
                # 以下3个评分字段是本函数的核心输出
                # 归一化后的向量分 [0,1]
                vector_score=normalized_vector_score,
                # 归一化后的BM25关键词分 [0,1]
                keyword_score=normalized_bm25_score,
                # 加权融合后的最终分 final_score = 向量分x0.65 + BM25分x0.35
                final_score=hybrid_score,
            )
        )

    # ===== 第七步：按final_score降序排序 =====
    # 排序优先级（4级，从高到低）：
    #   1. final_score        -> 加权融合分（最核心的排序依据）
    #   2. vector_score       -> 融合分相同时，语义相似度高的优先（向量检索比BM25更稳定可靠）
    #   3. keyword_score      -> 前两项都相同时，关键词匹配强的优先
    #   4. -chunk_index       -> 前三项都相同时，文档内越靠后的chunk优先（tie-breaker，保证排序确定性）
    merged_leaf_hits.sort(
        key=lambda item: (
            item.final_score,
            item.vector_score,
            item.keyword_score,
            -item.chunk_index,
        ),
        reverse=True,  # 整体降序排列（分数越高越靠前）
    )

    # ===== 漏斗策略第二级收敛：粗排截断取 Top 3K 个leaf =====
    # 第一级召回了4K条，融合排序后这里截3K，丢弃末尾的长尾弱相关候选，
    # 减少下一步「Small-to-Big扩展parent」时需要加载的父块数量（减少DB查询量）
    leaf_hits = merged_leaf_hits[: max(top_k * 3, top_k)]

    # ===== 第八步：Small-to-Big 扩展为父块上下文（第二层Pipeline） =====
    # 漏斗策略第三级收敛：传给扩展函数的top_k = top_k x 2（再收一级）
    # 扩展函数内部会：leaf按parent_id分组 -> 加载PARENT大块 -> 同组多leaf聚合分数取max
    # -> 重新排序 -> 取Top 2K条返回给调用方（最终top_k条由调用方/rerank再筛选）
    return _expand_leaf_hits_to_parent_context(
        db,
        user_id=user_id,
        leaf_hits=leaf_hits,
        top_k=max(top_k * 2, top_k),  # top_kx2，给rerank阶段多留一些候选择优
    )




def _phrase_terms(text: str) -> set[str]:
    terms: set[str] = set(LATIN_TOKEN_RE.findall(text))
    for token in CJK_TOKEN_RE.findall(text):
        terms.update(_generate_cjk_ngrams(token, min_size=2, max_size=6))
    return {term for term in terms if len(term) >= 2}


def _phrase_query_forms(normalized_query: str) -> list[str]:
    forms = [normalized_query]
    for anchor_text in QUERY_FOCUS_ANCHORS:
        anchor_index = normalized_query.find(anchor_text)
        if anchor_index > 0:
            focused_query = normalized_query[anchor_index:]
            if len(focused_query) >= max(len(anchor_text) + 2, 4):
                forms.append(focused_query)
            break
    return forms


def _evidence_score(query_text: str | None, chunk_text: str) -> float:
    return evidence_match_score(query_text or "", chunk_text)


def _phrase_overlap_once(normalized_query: str, normalized_chunk: str) -> float:
    if normalized_query in normalized_chunk:
        return 1.0

    query_terms = _phrase_terms(normalized_query)
    if not query_terms:
        return 0.0

    query_to_chunk_match = len({term for term in query_terms if term in normalized_chunk}) / len(query_terms)

    chunk_terms = _phrase_terms(normalized_chunk)
    if not chunk_terms:
        return query_to_chunk_match

    # For yes/no entity questions, the answer chunk may contain the entity while
    # the full question contains extra words such as "support" or "does it".
    entity_terms = {term for term in chunk_terms if term in normalized_query}
    chunk_to_query_match = len(entity_terms) / len(chunk_terms)

    return max(query_to_chunk_match, chunk_to_query_match * 0.8)


def phrase_overlap_score(query_text: str, chunk_text: str) -> float:
    normalized_query = re.sub(r"\s+", "", (query_text or "").lower())
    normalized_chunk = re.sub(r"\s+", "", (chunk_text or "").lower())
    if not normalized_query or not normalized_chunk:
        return 0.0

    return max(
        _phrase_overlap_once(query_form, normalized_chunk)
        for query_form in _phrase_query_forms(normalized_query)
    )



# 计算关键词重合度
# 查询："Python 编程 教程" → 分词结果：{"python", "编程", "教程"}（共3个词元）
#
# 文本块A："Python 编程 基础教程" → 分词结果：{"python", "编程", "基础教程"}
#
# 交集：{"python", "编程"} → 2个匹配
# 得分：2 / 3 ≈ 0.667 ✅
# 文本块B："Python 编程 进阶教程" → 分词结果：{"python", "编程", "进阶", "教程"}
#
# 交集：{"python", "编程", "教程"} → 3个匹配
# 得分：3 / 3 = 1.0 🏆
# 文本块C："Java 开发 指南" → 分词结果：{"java", "开发", "指南"}
#
# 交集：{} → 0个匹配
# 得分：0 / 3 = 0.0 ❌

QUERY_FOCUS_ANCHORS = (
    "\u652f\u6301",    # 支持
    "\u5982\u4f55",    # 如何
    "\u600e\u4e48",    # 怎么
    "\u600e\u6837",    # 怎样
    "\u662f\u5426",    # 是否
    "\u53ef\u4ee5",    # 可以
    "\u80fd\u5426",    # 能否
    "\u6709\u54ea\u4e9b",# 有哪些
    "\u6709\u4ec0\u4e48",# 有什么
    "\u54ea\u79cd",    # 哪种
    "\u54ea\u51e0\u79cd",# 哪几种
    "\u4ec0\u4e48",    # 什么
)



# 作用：安全地将查询形式添加到列表中，避免重复。
def _append_query_form(forms: list[str], seen: set[str], value: str) -> None:
    clean_value = re.sub(r"\s+", "", (value or "").lower())   # 去空格、转小写
    if not clean_value or clean_value in seen:      # 空值或已存在则跳过 避免无效或重复的查询形式
        return
    seen.add(clean_value)
    forms.append(clean_value)


# 作用：为用户问题生成多种查询形式，用于后续检索时提高召回率。
def build_recall_query_forms(query_text: str) -> list[str]:
    # 1. 添加原始查询（标准化后）
    normalized_text = re.sub(r"\s+", "", (query_text or "").lower())
    if not normalized_text:
        return []

    forms: list[str] = []
    seen: set[str] = set()
    _append_query_form(forms, seen, normalized_text)
    # 2. 提取焦点查询（基于 QUERY_FOCUS_ANCHORS）
    focused_query = normalized_text
    for anchor_text in QUERY_FOCUS_ANCHORS:
        anchor_index = normalized_text.find(anchor_text)
        if anchor_index > 0:
            candidate = normalized_text[anchor_index:]   # 提取锚点后的内容
            if len(candidate) >= max(len(anchor_text) + 2, 4):
                focused_query = candidate
                _append_query_form(forms, seen, focused_query)
            break

    # 3. 添加长关键词（长度≥4的分词结果）
    for token in sorted(tokenize(focused_query), key=len, reverse=True):
        if len(token) >= 4:
            _append_query_form(forms, seen, token)
        if len(forms) >= 5:   # 最多生成5种形式
            break

    return forms
# 原始问题：扫地机器人是否可以水洗
#        │
#        ├─ 找到锚点："是否"
#        │
#        └─ 提取焦点："是否可以水洗"
#
# 最终查询形式：
# 1. "扫地机器人是否可以水洗"（原问题）
# 2. "是否可以水洗"          （焦点查询）

def coarse_recall_score(query_text: str | None, chunk_text: str, vector_score: float) -> float:
    query_forms = build_recall_query_forms(query_text or "")    # 生成查询的多种形式
    if not query_forms:
        return round(vector_score, 6)

    primary_form = query_forms[0]  # 主要查询形式（原问题）
    focused_forms = query_forms[1:] or [primary_form]   # 扩展查询形式

    # 主查询的奖励分
    primary_bonus = (
        (keyword_overlap_score(primary_form, chunk_text) * 0.03)
        + (phrase_overlap_score(primary_form, chunk_text) * 0.05)
    )
    # 扩展查询的奖励分（权重更高）
    focused_bonus = max(
        (
            (keyword_overlap_score(form, chunk_text) * 0.22)
            + (phrase_overlap_score(form, chunk_text) * 0.30)
        )
        for form in focused_forms
    )
    # 最终分数 = 向量相似度 + 主查询奖励 + 扩展查询奖励
    #          = vector_score + (keyword×0.03 + phrase×0.05) + max(keyword×0.22 + phrase×0.30)

    evidence_bonus = _evidence_score(query_text, chunk_text) * 0.45

    return round(vector_score + primary_bonus + focused_bonus + evidence_bonus, 6)

def keyword_overlap_score(query_text: str, chunk_text: str) -> float:
    # 关键词重合度，作为 rerank 的补充信号
    query_tokens = tokenize(query_text)
    if not query_tokens:
        return 0.0

    chunk_tokens = tokenize(chunk_text)
    if not chunk_tokens:
        return 0.0

    return len(query_tokens & chunk_tokens) / len(query_tokens)


# * 之后的所有参数必须使用关键字（keyword）方式传递，不能使用位置（positional）方式。
def load_user_chunks(
    # SQLAlchemy数据库会话对象，用于执行数据库查询
    db: Session,
    # 独立参数分隔符：强制后续参数必须以关键字形式传递
    *,
    # 用户ID：限定只加载该用户的知识块数据
    user_id: int,
    # 可选：文档ID列表，用于限定只检索特定文档（None表示加载用户所有文档）
    document_ids: Sequence[int] | None = None,
) -> list[RetrievedChunk]:
    """
    从数据库加载用户知识库的所有叶子知识块（leaf chunks）。

    【父子块检索体系说明：
    - leaf（叶子块）：小块，负责【召回阶段】使用——体积小、精度高，便于精准匹配用户问题
    - parent（父块）：大块，负责【上下文扩展阶段】使用——给LLM提供更完整的上下文
    因此本函数【只加载leaf，不把parent混进召回候选池，避免召回阶段干扰。
    """
    # ===== 步骤1：构造SQLAlchemy查询对象，指定需要查询的字段
    query = (
        db.query(
            # 知识块唯一ID，使用label重命名为chunk_id，与RetrievedChunk字段名对应
            KnowledgeChunks.id.label("chunk_id"),
            # 所属文档ID
            KnowledgeChunks.document_id,
            # 块在文档中的顺序索引
            KnowledgeChunks.chunk_index,
            # 知识块的实际文本内容
            KnowledgeChunks.content,
            # 检索专用内容（可能与content不同，如清洗/增强后的文本）
            KnowledgeChunks.retrieval_content,
            # 来源页码（PDF等分页文档才有）
            KnowledgeChunks.source_page,
            # 来源章节标题
            KnowledgeChunks.source_section,
            # 向量嵌入JSON字符串
            KnowledgeChunks.embedding_json,
            # 块角色：叶子块/父块
            KnowledgeChunks.chunk_role,
            # 父块ID（用于父子块关联）
            KnowledgeChunks.parent_chunk_id,
            # 父块标题
            KnowledgeChunks.parent_title,
            # 块类型：text/table/image等
            KnowledgeChunks.block_type,
            # 在父块中的子块序号
            KnowledgeChunks.child_index,
            # 表格起始行（仅表格块有值）
            KnowledgeChunks.table_row_from,
            # 表格结束行（仅表格块有值）
            KnowledgeChunks.table_row_to,
            # 关联文档表，获取文档名称，label重命名为document_name
            KnowledgeDocuments.name.label("document_name"),
        )
        # ===== 步骤2：JOIN关联文档表，通过document_id外键关联
        .join(KnowledgeDocuments, KnowledgeDocuments.id == KnowledgeChunks.document_id)
        # ===== 步骤3：添加基础过滤条件
        .filter(
            # 条件1：知识块属于当前用户
            KnowledgeChunks.user_id == user_id,
            # 条件2：文档也属于当前用户（双重校验数据一致性）
            KnowledgeDocuments.user_id == user_id,
            # 条件3：【关键条件】只加载叶子块LEAF，不加载父块PARENT
            KnowledgeChunks.chunk_role == KNOWLEDGE_CHUNK_ROLE_LEAF,
        )
    )

    # ===== 步骤4：如果指定了文档ID列表，追加过滤条件——只检索指定文档
    if document_ids:
        # 使用IN子句限定document_id在传入的列表范围内
        query = query.filter(KnowledgeChunks.document_id.in_(list(document_ids)))

    # ===== 步骤5：执行查询并排序
    rows = (
        # 排序规则：先按文档ID升序 → 再按块在文档内的索引升序 → 保证结果有序
        query.order_by(KnowledgeChunks.document_id.asc(), KnowledgeChunks.chunk_index.asc())
        # 触发SQL执行，获取所有结果行
        .all()
    )

    # ===== 步骤6：将数据库行对象转换为RetrievedChunk数据类列表
    chunks: list[RetrievedChunk] = []
    for row in rows:
        chunks.append(
            RetrievedChunk(
                # 所属文档ID
                document_id=row.document_id,
                # 所属文档名称（来自JOIN的KnowledgeDocuments表）
                document_name=row.document_name,
                # 知识块ID
                chunk_id=row.chunk_id,
                # 块在文档中的顺序索引
                chunk_index=row.chunk_index,
                # 块的实际内容
                content=row.content,
                # 来源页码，数据库可能为NULL
                source_page=row.source_page,
                # 来源章节，NULL时转为空字符串
                source_section=row.source_section or "",
                # 向量嵌入JSON，NULL时转为空字符串
                embedding_json=row.embedding_json or "",
                # 检索用内容：优先取retrieval_content，否则降级为content，再否则空字符串
                retrieval_content=row.retrieval_content or row.content or "",
                # 块角色，默认LEAF
                chunk_role=row.chunk_role or KNOWLEDGE_CHUNK_ROLE_LEAF,
                # 父块ID，可能为None（叶子块不一定都有父块）
                parent_chunk_id=row.parent_chunk_id,
                # 父块标题，NULL转空字符串
                parent_title=row.parent_title or "",
                # 块类型，默认text文本
                block_type=row.block_type or "text",
                # 子块在父块中序号，默认0
                child_index=row.child_index or 0,
                # 表格起始行
                table_row_from=row.table_row_from,
                # 表格结束行
                table_row_to=row.table_row_to,
            )
        )

    # ===== 步骤7：返回转换好的知识块列表
    return chunks

def load_chunks_by_ids(
    # SQLAlchemy数据库会话对象，用于执行查询
    db: Session,
    # 独立参数分隔符：强制后续参数必须以关键字形式传递
    *,
    # 用户ID：数据权限校验，确保只能加载该用户自己的知识块
    user_id: int,
    # 要加载的知识块ID列表（来自FAISS等向量库检索返回的命中结果）
    chunk_ids: Sequence[int],
) -> list[RetrievedChunk]:
    """
    【按ID批量加载知识块】根据传入的chunk_ids列表，从数据库加载对应知识块。

    核心特性：
    1. 顺序保证：返回结果的顺序严格按照传入chunk_ids的顺序（SQL的IN不保证顺序，本函数会修复）
    2. 容错处理：数据库中不存在的ID会被自动跳过，不会报错也不会返回None占位
    3. 权限校验：双重校验知识块和所属文档都属于当前user_id，防止越权访问

    【典型调用场景】
        FAISS向量库检索 → 返回按相似度排序好的 chunk_ids列表
                       → 调用本函数从数据库加载完整的chunk数据
                       → 返回保持原相似度排序的RetrievedChunk对象列表

    【例子】FAISS检索后加载知识块
    ┌─────────────────────────────────────────────────────────────────────┐
    │ 场景：用户搜索「如何用Python处理PDF」，FAISS返回3个命中结果       │
    │ chunk_ids = [205, 108, 317]  （按向量相似度从高到低排好序）       │
    │ 其中 chunk_id=108 已被用户从知识库中删除（数据库不存在）          │
    └─────────────────────────────────────────────────────────────────────┘

    调用：
        chunks = load_chunks_by_ids(
            db,                          # SQLAlchemy会话
            user_id=123,                 # 当前用户ID
            chunk_ids=[205, 108, 317],   # FAISS返回的ID列表（按相似度排序）
        )

    步骤1：快速通道检查 → chunk_ids非空，跳过

    步骤2：执行SQL查询（IN子句）
        SELECT ... FROM knowledge_chunks c
        JOIN knowledge_documents d ON d.id = c.document_id
        WHERE c.user_id = 123
          AND d.user_id = 123
          AND c.id IN (205, 108, 317)   ← 注意：SQL IN返回顺序不确定！

        【数据库返回rows的实际顺序（随机的，可能是）】：
        row0: chunk_id=317, content="PDF转Word的方法...", document_name="办公技巧.pdf"
        row1: chunk_id=205, content="Python使用PyPDF2读取PDF...", document_name="Python实战.pdf"
        （注意：chunk_id=108已被删除，所以数据库只返回2条）

    步骤3：构造字典 chunk_map（key=chunk_id，方便O(1)查找）
        chunk_map = {
            317: RetrievedChunk(chunk_id=317, ...),  ← 对应row0
            205: RetrievedChunk(chunk_id=205, ...),  ← 对应row1
        }

    步骤4：【关键】按传入chunk_ids的原始顺序重排结果，过滤不存在的ID
        遍历传入顺序：[205, 108, 317]
          205 → 在字典中，取出chunk205（第1名结果）
          108 → 不在字典中（已被删除），自动跳过
          317 → 在字典中，取出chunk317（第2名结果）

    步骤5：最终返回结果（2条，严格保持传入时的相似度排序）：
        [
            RetrievedChunk(chunk_id=205, content="Python使用PyPDF2读取PDF...", ...),  # 相似度第1
            RetrievedChunk(chunk_id=317, content="PDF转Word的方法...", ...),          # 相似度第2
        ]

    【注意】如果不重排会怎样？
        直接返回SQL的rows顺序 → chunk317会排在chunk205前面，
        把「相似度低的结果」放在「相似度高的结果」前面，导致检索质量下降！
        这就是为什么必须用字典+按原始顺序重排的原因。
    """
    # ===== 快速通道：空列表直接返回，避免无意义的数据库查询
    if not chunk_ids:
        return []

    # ===== 步骤1：从数据库批量查询指定ID的知识块
    rows = (
        db.query(
            # 知识块唯一ID，label重命名为chunk_id与数据类字段对应
            KnowledgeChunks.id.label("chunk_id"),
            # 所属文档ID
            KnowledgeChunks.document_id,
            # 块在文档中的顺序索引
            KnowledgeChunks.chunk_index,
            # 知识块实际文本内容
            KnowledgeChunks.content,
            # 检索专用内容（可能经过清洗/增强处理）
            KnowledgeChunks.retrieval_content,
            # 来源页码（PDF等分页文档才有值）
            KnowledgeChunks.source_page,
            # 来源章节标题
            KnowledgeChunks.source_section,
            # 向量嵌入JSON字符串
            KnowledgeChunks.embedding_json,
            # 块角色：叶子块LEAF / 父块PARENT
            KnowledgeChunks.chunk_role,
            # 父块ID（用于父子块层级关联）
            KnowledgeChunks.parent_chunk_id,
            # 父块标题
            KnowledgeChunks.parent_title,
            # 块类型：text文本/table表格/image图片等
            KnowledgeChunks.block_type,
            # 在父块中的子块序号
            KnowledgeChunks.child_index,
            # 表格起始行号（仅表格块有值）
            KnowledgeChunks.table_row_from,
            # 表格结束行号（仅表格块有值）
            KnowledgeChunks.table_row_to,
            # JOIN文档表获取文档名称，label重命名为document_name
            KnowledgeDocuments.name.label("document_name"),
        )
        # JOIN关联文档表：通过document_id外键关联
        .join(KnowledgeDocuments, KnowledgeDocuments.id == KnowledgeChunks.document_id)
        # 过滤条件
        .filter(
            # 条件1：知识块属于当前用户（数据权限）
            KnowledgeChunks.user_id == user_id,
            # 条件2：文档也属于当前用户（双重校验防越权）
            KnowledgeDocuments.user_id == user_id,
            # 条件3：【核心条件】知识块ID必须在传入的chunk_ids列表中（IN子句）
            KnowledgeChunks.id.in_(list(chunk_ids)),
        )
        # 触发SQL执行，获取所有匹配的行
        .all()
    )

    # ===== 步骤2：将数据库结果转换为字典，key=chunk_id，方便O(1)查找
    # 为什么要转字典？因为后面需要「按传入的chunk_ids顺序」返回结果，而SQL的IN子句不保证顺序
    chunk_map: dict[int, RetrievedChunk] = {}
    for row in rows:
        # 以chunk_id为key存入字典，同时构造RetrievedChunk对象
        chunk_map[int(row.chunk_id)] = RetrievedChunk(
            # 所属文档ID
            document_id=row.document_id,
            # 所属文档名称（来自JOIN的文档表）
            document_name=row.document_name,
            # 知识块ID
            chunk_id=row.chunk_id,
            # 块在文档中的顺序索引
            chunk_index=row.chunk_index,
            # 块的实际内容
            content=row.content,
            # 来源页码，数据库可能为NULL
            source_page=row.source_page,
            # 来源章节，NULL时转为空字符串
            source_section=row.source_section or "",
            # 向量嵌入JSON，NULL时转为空字符串
            embedding_json=row.embedding_json or "",
            # 检索用内容：优先级 retrieval_content > content > 空字符串
            retrieval_content=row.retrieval_content or row.content or "",
            # 块角色，默认LEAF叶子块
            chunk_role=row.chunk_role or KNOWLEDGE_CHUNK_ROLE_LEAF,
            # 父块ID，可能为None
            parent_chunk_id=row.parent_chunk_id,
            # 父块标题，NULL转空字符串
            parent_title=row.parent_title or "",
            # 块类型，默认text文本
            block_type=row.block_type or "text",
            # 子块在父块中的序号，默认0
            child_index=row.child_index or 0,
            # 表格起始行号
            table_row_from=row.table_row_from,
            # 表格结束行号
            table_row_to=row.table_row_to,
        )

    # ===== 步骤3：按传入的chunk_ids顺序返回结果，同时自动跳过数据库中不存在的ID
    # 为什么要重新排序？FAISS返回的chunk_ids是「按向量相似度从高到低排好序的」，
    # 但SQL的IN()查询返回结果的顺序是不确定的，所以必须按传入顺序重排，保证相似度高的在前。
    # 使用列表推导式：遍历原始chunk_ids，从字典中取出对应块；用if过滤掉已被删除/不存在的ID
    return [chunk_map[int(chunk_id)] for chunk_id in chunk_ids if int(chunk_id) in chunk_map]


def _score_retrieved_chunks(
    # 用户查询的原始文本，用于计算关键词匹配分数（可能为None，表示只靠向量分排序）
    query_text: str | None,
    # 待评分的候选知识块列表（来自FAISS检索或暴力检索的初步结果）
    chunks: Sequence[RetrievedChunk],
    # 独立参数分隔符：强制后续参数必须以关键字形式传递
    *,
    # 最终返回的结果数量上限（Top K）
    top_k: int,
) -> list[RetrievedChunk]:
    """
    【粗排阶段】对检索到的候选知识块进行评分和排序，返回Top K个最优结果。

    评分逻辑（调用coarse_recall_score）：
        综合分 = 向量相似度分 + 关键词匹配奖励分 + 证据匹配奖励分
    排序优先级（从高到低）：
        1. recall_score（综合分）→ 最优先
        2. vector_score（向量分）→ 综合分相同时，语义相似度高的排前
        3. chunk_index（文档内序号）→ 分数都相同时，文档靠前的块排前

    【实际调用场景】：
        _search_similar_chunks_by_bruteforce() / _search_similar_chunks_by_faiss()
            → 拿到初步候选chunks
            → 调用本函数做粗排
            → 返回粗排Top K结果
            → 后续再由rerank_chunks()做精排（如果开启的话）

    【例子】
    假设用户查询：query_text = "如何用Python读取PDF文件？"
    候选chunks共3条（top_k=2）：
    ┌──────────┬─────────────────────────────────────────────┬─────────────┐
    │ chunk_id │ content                                     │ vector_score│
    ├──────────┼─────────────────────────────────────────────┼─────────────┤
    │ 101      │ Python可以用open函数读取txt文件...         │ 0.72        │
    │ 102      │ 使用PyPDF2库读取PDF：import PyPDF2...      │ 0.81        │
    │ 103      │ Java使用iText操作PDF文档...               │ 0.65        │
    └──────────┴─────────────────────────────────────────────┴─────────────┘

    步骤1：过滤vector_score<=0的chunk → 3条都保留

    步骤2：计算每条的recall_score（综合分）
    chunk101: 关键词"Python"匹配，但"PDF"不匹配 → 综合分 ≈ 0.72 + 0.05奖励 = 0.77
    chunk102: 关键词"Python"和"PDF"都匹配，短语"读取PDF"也命中 → 综合分 ≈ 0.81 + 0.25奖励 = 1.06
    chunk103: 只有"PDF"匹配，"Python"不匹配 → 综合分 ≈ 0.65 + 0.08奖励 = 0.73

    步骤3：按 (recall_score, vector_score, chunk_index) 降序排序
    排序后顺序：chunk102(1.06) → chunk101(0.77) → chunk103(0.73)

    步骤4：取Top K=2 → 返回 [chunk102, chunk101]
    """
    # scored 是一个元组列表：每个元素是 (综合评分, 知识块对象)
    # 为什么存元组？因为排序时要同时使用「综合分」和「知识块内部字段」作为排序key
    scored: list[tuple[float, RetrievedChunk]] = []

    # 遍历每个候选chunk，逐一计算综合评分
    for chunk in chunks:
        # 过滤无效结果：向量分<=0说明完全不相关，直接跳过
        # （可能是embedding解析失败、或余弦相似度计算异常的边界情况）
        if chunk.vector_score <= 0:
            continue

        # ===== 核心：计算综合召回评分 =====
        # coarse_recall_score参数说明：
        #   query_text       → 用户原始问题，用于关键词/短语匹配
        #   _recall_text(chunk) → 取chunk的检索用文本（优先retrieval_content，其次content）
        #   chunk.vector_score → 向量检索的语义相似度分（作为基础分）
        # 返回值：综合分 = 向量基础分 + 关键词匹配奖励 + 短语匹配奖励 + 证据匹配奖励
        recall_score = coarse_recall_score(query_text, _recall_text(chunk), chunk.vector_score)
        # 将 (综合评分, 新构造的RetrievedChunk对象) 加入待排序列表
        # 为什么要重新构造RetrievedChunk？因为要把当前的vector_score、keyword_score等状态保留下来，
        # 供后续的排序和精排阶段使用
        scored.append(
            (
                # 元组第1个元素：综合评分recall_score，作为排序的第一关键字
                recall_score,
                # 元组第2个元素：完整的RetrievedChunk对象（拷贝所有字段）
                RetrievedChunk(
                    # —— 基础标识字段 ——
                    document_id=chunk.document_id,
                    document_name=chunk.document_name,
                    chunk_id=chunk.chunk_id,
                    chunk_index=chunk.chunk_index,
                    content=chunk.content,
                    source_page=chunk.source_page,
                    source_section=chunk.source_section,
                    # —— 检索&向量字段 ——
                    embedding_json=chunk.embedding_json,
                    retrieval_content=chunk.retrieval_content,
                    # —— 层级结构字段 ——
                    chunk_role=chunk.chunk_role,
                    parent_chunk_id=chunk.parent_chunk_id,
                    parent_title=chunk.parent_title,
                    block_type=chunk.block_type,
                    child_index=chunk.child_index,
                    table_row_from=chunk.table_row_from,
                    table_row_to=chunk.table_row_to,
                    # —— 评分字段（关键：保留这些分数供后续排序/精排使用）——
                    vector_score=chunk.vector_score,    # 向量相似度分
                    keyword_score=chunk.keyword_score,  # 关键词匹配分
                ),
            )
        )

    # ===== 排序：三级优先级降序排列 =====
    # 排序key是一个三元组，从左到右优先级依次降低：
    #   1. item[0]           → recall_score 综合评分（最重要）
    #   2. item[1].vector_score → 向量相似度分（综合分相同时，语义更相关的排前）
    #   3. item[1].chunk_index  → 文档内块序号（分数都相同时，文档靠前的块排前，保证稳定性）
    # reverse=True 表示整体降序排列（分数越高越靠前）
    scored.sort(
        key=lambda item: (item[0], item[1].vector_score, item[1].chunk_index),
        reverse=True,
    )
    # ===== 返回Top K结果 =====
    # scored[:top_k] 取前top_k个元组，再通过列表推导式提取其中的RetrievedChunk对象（即元组的第2个元素）
    # 如果候选数不足top_k，就有多少返回多少（Python切片越界不会报错）
    return [item[1] for item in scored[:top_k]]


def _search_similar_chunks_by_bruteforce(
    db: Session,
    *,
    user_id: int,
    query_embedding: list[float],
    query_text: str | None = None,
    document_ids: Sequence[int] | None = None,
    top_k: int = 10,
) -> list[RetrievedChunk]:
    candidates = load_user_chunks(db, user_id=user_id, document_ids=document_ids)

    scored_candidates: list[RetrievedChunk] = []
    for chunk in candidates:
        chunk_embedding = parse_embedding(chunk.embedding_json)
        if not chunk_embedding:
            continue

        vector_score = cosine_similarity(query_embedding, chunk_embedding)
        if vector_score <= 0:
            continue

        scored_candidates.append(
            RetrievedChunk(
                document_id=chunk.document_id,
                document_name=chunk.document_name,
                chunk_id=chunk.chunk_id,
                chunk_index=chunk.chunk_index,
                content=chunk.content,
                source_page=chunk.source_page,
                source_section=chunk.source_section,
                embedding_json=chunk.embedding_json,
                vector_score=vector_score,
            )
        )

    return _score_retrieved_chunks(query_text, scored_candidates, top_k=top_k)



# FAISS 检索函数
def _search_similar_chunks_by_faiss(
    db: Session,
    *,
    user_id: int,
    query_embedding: list[float],
    query_text: str | None = None,
    document_ids: Sequence[int] | None = None,
    top_k: int = 10,
) -> list[RetrievedChunk] | None:
    search_hits = search_user_faiss_index(
        user_id=user_id,
        query_embedding=query_embedding,
        top_k=top_k,
        document_ids=list(document_ids or []),
    )
    if search_hits is None:
        rebuild_user_faiss_index(db, user_id=user_id)
        search_hits = search_user_faiss_index(
            user_id=user_id,
            query_embedding=query_embedding,
            top_k=top_k,
            document_ids=list(document_ids or []),
        )
    if search_hits is None:
        return None

    chunk_ids = [hit.chunk_id for hit in search_hits]
    if not chunk_ids:
        return []

    candidates = load_chunks_by_ids(db, user_id=user_id, chunk_ids=chunk_ids)
    if len(candidates) != len(chunk_ids):
        rebuild_user_faiss_index(db, user_id=user_id)
        search_hits = search_user_faiss_index(
            user_id=user_id,
            query_embedding=query_embedding,
            top_k=top_k,
            document_ids=list(document_ids or []),
        )
        if search_hits is None:
            return None
        chunk_ids = [hit.chunk_id for hit in search_hits]
        candidates = load_chunks_by_ids(db, user_id=user_id, chunk_ids=chunk_ids)

    vector_score_map = {hit.chunk_id: hit.score for hit in search_hits}
    scored_candidates: list[RetrievedChunk] = []
    for chunk in candidates:
        vector_score = float(vector_score_map.get(chunk.chunk_id, 0.0))
        if vector_score <= 0:
            continue

        scored_candidates.append(
            RetrievedChunk(
                document_id=chunk.document_id,
                document_name=chunk.document_name,
                chunk_id=chunk.chunk_id,
                chunk_index=chunk.chunk_index,
                content=chunk.content,
                source_page=chunk.source_page,
                source_section=chunk.source_section,
                embedding_json=chunk.embedding_json,
                vector_score=vector_score,
            )
        )

    return _score_retrieved_chunks(query_text, scored_candidates, top_k=top_k)


# 用户查询 → 生成 query_embedding
#                 ↓
#         load_user_chunks() → 获取所有候选 chunks
#                 ↓
#         ┌── 遍历每个 chunk ──┐
#         │   解析 embedding    │
#         │   计算 cosine 相似度 │
#         │   相似度 > 0? → 保留│
#         └────────────────────┘
#                 ↓
#         按 vector_score 降序排序
#                 ↓
#         取前 top_k 条 → 返回结果
def search_similar_chunks_by_embedding(
    db: Session,
    *,
    user_id: int,
    # 查询向量（将用户问题转为的数字列表）
    query_embedding: list[float],
    query_text: str | None = None,
    # 可选：限定搜索哪些文档
    document_ids: Sequence[int] | None = None,
    # 最多返回多少条结果
    top_k: int = 10,
    # 相似度阈值（低于此值的结果被过滤）
    threshold: float = 0.5,
    # 是否对结果重新排序（提高精度）
    rerank: bool = True,
) -> list[RetrievedChunk]:
    # ========== 阶段1：FAISS向量检索 ==========
    # 扩大检索范围（取top_k的2倍），给后续精排更多候选
    faiss_results = _search_similar_chunks_by_faiss(
        db,
        user_id=user_id,
        query_embedding=query_embedding,
        query_text=query_text,
        document_ids=document_ids,
        top_k=top_k * 2,  # 扩大范围：确保有足够候选
    )

    # ========== 阶段2：关键词匹配检查（降级兜底机制） ==========
    # 问题场景：FAISS向量检索可能失败（如"支持小爱同学吗"与"常见的有小爱同学"向量相似度低）
    # 解决方案：检查FAISS结果是否包含关键词匹配，若无则降级到暴力检索
    has_keyword_match = False
    if faiss_results and query_text:
        # 提取用户问题中的关键词
        query_tokens = tokenize(query_text)
        # 检查每个FAISS返回的chunk是否包含关键词
        for chunk in faiss_results:
            chunk_tokens = tokenize(chunk.content)
            # 如果有任何关键词重叠，说明匹配成功
            if query_tokens & chunk_tokens:
                has_keyword_match = True
                break

    # ========== 阶段3：决定返回策略 ==========
    # 条件：FAISS结果为空 或 没有关键词匹配 → 降级到暴力检索
    # 原因：暴力检索虽然慢，但能确保找到包含关键词的chunk
    if faiss_results is None or not faiss_results or not has_keyword_match:
        return _search_similar_chunks_by_bruteforce(
            db,
            user_id=user_id,
            query_embedding=query_embedding,
            query_text=query_text,
            document_ids=document_ids,
            top_k=top_k,
        )

    # FAISS结果有效且有关键词匹配 → 返回FAISS结果
    return faiss_results

# 用户查询 "如何用Python处理PDF"
#         │
#         ├─→ 生成 query_embedding（向量）
#         │
#         ├─→ search_similar_chunks_by_embedding()  ← 第172-227行
#         │       └─ 向量相似度粗检索 → 10条结果
#         │
#         └─→ rerank_chunks(query_text, chunks, top_k=5)  ← 第230-261行
#                 ├─ 计算每条的 keyword_score
#                 ├─ 加权计算 final_score = 0.8v + 0.2k
#                 ├─ 按 final_score 降序排序
#                 └─ 返回 Top 5 → 给 LLM 做 RAG
def rerank_chunks(
    # 用户的原始查询文本（问题），用于计算各种关键词/短语/证据匹配奖励分
    query_text: str,
    # 粗排阶段的候选知识块列表（通常是 hybrid_search 返回的 Top 2K Parent大块结果）
    chunks: Sequence[RetrievedChunk],
    # 精排后最终返回的Top K数量（精排计算量较大，所以top_k通常较小，如5~10）
    top_k: int = 5,
) -> list[RetrievedChunk]:
    """
    【精排阶段（Rerank）】对粗排后的候选chunks做多维度加权精细重排，选出最相关的Top K。

    精排 vs 粗排的区别：
        粗排（hybrid_search / _score_retrieved_chunks）：计算快、维度少，负责从大库里捞Top几百条
        精排（本函数）：计算细、维度多、权重精准调优，负责从粗排Top几十条里挑最相关的Top K给LLM

    Small-to-Big 场景下的特殊优化：
        精排对象通常已经是 Parent大块内容，但真正命中用户问题的往往是小块leaf，
        所以本函数会把 matched_child_content（精准命中的leaf内容）拼进 candidate_text参与评分，
        防止「大块内容很泛，但真正命中的leaf信号被淹没」导致排序错误。

    精排最终加权公式（8个维度，权重之和约等于1.3，允许各维度叠加奖励超过1分）：
      final_score =
        chunk.vector_score                 x 0.35   向量语义相似度（粗排基础分，占比最大）
      + retrieval_keyword_score           x 0.12   粗排阶段BM25关键词分（保留粗排关键词信号）
      + primary_keyword_score             x 0.04   原始查询词的词命中重叠分（低权重补充）
      + primary_phrase_score              x 0.04   原始查询词的短语命中重叠分（低权重补充）
      + keyword_score（所有query_forms取max）x 0.18   扩展查询词的词命中重叠分（较重要）
      + phrase_score （所有query_forms取max）x 0.22   扩展查询词的短语命中重叠分（最关键的关键词匹配维度）
      + evidence_score                    x 0.35   证据匹配分（查询中的重要实体/术语是否在文档中有充分证据支撑）

    【完整例子】用户搜索「Python用PyPDF2读取PDF表格」，粗排返回3个候选chunk，top_k=2
    build_recall_query_forms("Python用PyPDF2读取PDF表格") 返回的查询扩展形式：
      query_forms = [
        "Python用PyPDF2读取PDF表格",  # primary_form 原始形式
        "Python PyPDF2 读取 PDF 表格", # focused_forms[0] 分词后
        "pypdf2 pdf 提取表",            # focused_forms[1] 同义词/缩写扩展
      ]

    3个候选Parent大块：
    ┌────────┬─────────────────────────────────────────────────────┬────────────┬────────────┬──────────────────────────────────────┐
    │chunk_id│ content（Parent大块600字，只展示核心1句）           │vector_score│keyword_score│ matched_child_content（真正命中的leaf）│
    ├────────┼─────────────────────────────────────────────────────┼────────────┼────────────┼──────────────────────────────────────┤
    │ 800    │ 第3章 处理PDF文件...3.1安装 3.2读取页面...         │ 0.82       │ 0.65       │ 3.2.2 用PyPDF2提取PDF表格数据         │
    │ 810    │ 第4章 pdfplumber实战...表格提取...图像识别...      │ 0.78       │ 0.21       │ 4.1 pdfplumber读取表格               │
    │ 900    │ 附录A PDF常见问题...加密...压缩...文件损坏修复       │ 0.55       │ 0.30       │ A.3 PDF打不开怎么办                  │
    └────────┴─────────────────────────────────────────────────────┴────────────┴────────────┴──────────────────────────────────────┘

    ═══════ 逐个chunk精排计算过程 ═══════

    ┌─────────────────────────────────────────────────────────────────────────────┐
    │ chunk800（真正命中的正确答案，PyPDF2提取表）                                 │
    ├─────────────────────────────────────────────────────────────────────────────┤
    │ candidate_text = 大块content + matched_child_content拼接（增加强命中信号）   │
    │ 8个维度打分：                                                                 │
    │   ① vector_score x 0.35 = 0.82 x 0.35 = 0.287                                │
    │   ② retrieval_keyword_score(粗排BM25) x 0.12 = 0.65 x 0.12 = 0.078           │
    │   ③ primary_keyword_score（全命中）= 0.9 x 0.04 = 0.036                      │
    │   ④ primary_phrase_score（短语PyPDF2读取PDF命中）= 0.85 x 0.04 = 0.034      │
    │   ⑤ keyword_score(扩展形式取max) = 1.0 x 0.18 = 0.180                        │
    │   ⑥ phrase_score (扩展形式取max) = 0.95 x 0.22 = 0.209 ←短语命中强，拉分最多 │
    │   ⑦ evidence_score（4个重要术语都有证据）= 0.92 x 0.35 = 0.322               │
    │ 合计 final_score = round(0.287+0.078+0.036+0.034+0.180+0.209+0.322, 6)       │
    │                   = 1.146  ← 排第一！正确答案                                │
    └─────────────────────────────────────────────────────────────────────────────┘

    ┌─────────────────────────────────────────────────────────────────────────────┐
    │ chunk810（pdfplumber方案，语义相关但关键词PyPDF2未命中）                     │
    ├─────────────────────────────────────────────────────────────────────────────┤
    │ candidate_text = 大块content + 4.1 pdfplumber读取表格                        │
    │ 打分：vector分高(0.78*0.35=0.273)，但phrase分/evidence分暴跌（缺PyPDF2）     │
    │ 合计 final_score ≈ 0.612 → 排第二，进入Top 2                                 │
    └─────────────────────────────────────────────────────────────────────────────┘

    ┌─────────────────────────────────────────────────────────────────────────────┐
    │ chunk900（附录常见问题，弱相关只有PDF命中）                                  │
    ├─────────────────────────────────────────────────────────────────────────────┤
    │ candidate_text = 附录内容 + A.3 PDF打不开怎么办                              │
    │ 打分：vector分低(0.55*0.35=0.192)，短语分/证据分几乎为0                      │
    │ 合计 final_score ≈ 0.279 → 排第三，被Top 2淘汰                               │
    └─────────────────────────────────────────────────────────────────────────────┘

    精排排序结果：chunk800(1.146) → chunk810(0.612) → chunk900(0.279)
    return reranked[:top_k=2] → 返回 [chunk800, chunk810]，正确把最相关的排第一！
    """
    # 保存精排后的结果列表（每个元素是重新计算了final_score的RetrievedChunk）
    reranked: list[RetrievedChunk] = []

    # ===== 步骤1：构建查询的多种扩展形式（Query Expansion） =====
    # build_recall_query_forms(query_text) 会返回查询文本的多种变体：
    #   query_forms[0] = 原始查询 primary_form（原样保留）
    #   query_forms[1..n] = focused_forms：分词后、同义词扩展、缩写展开、CJK n-gram等
    # 作用：提高召回率，防止用户说「读取表格」但文档写「提取表」时漏掉匹配
    query_forms = build_recall_query_forms(query_text)
    # primary_form：主查询形式 = 第1个元素（通常是原始查询），如果返回空就用原query_text兜底
    primary_form = query_forms[0] if query_forms else query_text
    # focused_forms：扩展查询形式列表 = 除了第一个的其余元素；如果没有扩展形式，退化用主查询本身（确保不为空）
    focused_forms = query_forms[1:] or [primary_form]

    # ===== 步骤2：遍历每个候选chunk，逐一计算精排final_score =====
    for chunk in chunks:
        # 粗排阶段的BM25关键词分（归一化后的[0,1]分），作为精排公式中的「粗排关键词信号」保留下来
        retrieval_keyword_score = chunk.keyword_score or 0.0

        # ===== Small-to-Big核心优化：拼接 matched_child_content 参与评分 =====
        # 背景：Small-to-Big流程里，现在的chunk往往已经是PARENT大块（600字），但真正命中用户问题的，
        #   常常是某个几十字的leaf小块内容（存储在matched_child_content字段中）。
        # 问题：如果只拿PARENT大块600字去算关键词匹配，真正命中的那句信号会被大量无关文字稀释，导致排序不准。
        # 解决：把matched_child_content拼接到content末尾，一起参与精排评分，
        #   让「精准命中的leaf内容」在keyword_score/phrase_score里权重更高，避免好结果被埋没。
        # 注意：加了 not in 判断，如果matched_child_content本来就包含在大块content里（没被稀释），就不用重复拼接。
        candidate_text = chunk.content
        if chunk.matched_child_content and chunk.matched_child_content not in candidate_text:
            candidate_text = f"{chunk.content}\n\n{chunk.matched_child_content}".strip()

        # ===== 计算5个匹配分维度 =====
        # ① keyword_score：扩展查询词的词级别重叠匹配分（对所有focused_forms取最大值，哪个扩展形式命中最好就算哪个）
        #   计算每个扩展形式的keyword_overlap_score（Jaccard/交集占比），取最大的那个
        keyword_score = max(keyword_overlap_score(form, candidate_text) for form in focused_forms)
        # ② phrase_score：扩展查询词的短语级别重叠匹配分（连续词命中，比单个词更精准，所以权重更高0.22）
        #   计算每个扩展形式的phrase_overlap_score（长连续短语命中奖励高），取最大值
        phrase_score = max(phrase_overlap_score(form, candidate_text) for form in focused_forms)
        # ③ primary_keyword_score：只用原始查询primary_form算的词级别匹配分（低权重0.04，补充信号）
        primary_keyword_score = keyword_overlap_score(primary_form, candidate_text)
        # ④ primary_phrase_score：只用原始查询primary_form算的短语级别匹配分（低权重0.04，补充信号）
        primary_phrase_score = phrase_overlap_score(primary_form, candidate_text)
        # ⑤ evidence_score：证据匹配分（权重最大的关键词维度0.35）
        #   算法思想：从查询中提取「重要实体/核心术语」（如专有名词、型号、技术名词），检查文档中是否有充分证据支撑；
        #   和普通keyword_overlap的区别：evidence_score会对罕见词/核心词加大权重，对停用词（的/了/怎么）不计分。
        evidence_score = _evidence_score(query_text, candidate_text)

        # ===== 精排加权融合：8个维度 x 各自权重 = final_score =====
        # 权重设计思路（凭经验调优+离线评估）：
        #   - 向量分(0.35) + evidence分(0.35) = 70%，这两项是「语义正确性」的压舱石
        #   - phrase分(0.22) + keyword分(0.18) = 40%，这两项是「关键词精确匹配」的保障，防止语义分把完全不相关的东西排前面
        #   - 其余4项(0.12+0.04+0.04) = 20%，是补充信号，防止边界case排序抖动
        # （权重总和=0.35+0.12+0.04+0.04+0.18+0.22+0.35=1.3，允许>1，鼓励多个维度同时命中时分数叠加奖励）
        final_score = round(
            (chunk.vector_score * 0.35)
            + (retrieval_keyword_score * 0.12)
            + (primary_keyword_score * 0.04)
            + (primary_phrase_score * 0.04)
            + (keyword_score * 0.18)
            + (phrase_score * 0.22)
            + (evidence_score * 0.35),
            6,  # 保留6位小数，避免浮点精度导致排序随机
        )

        # ===== 构造精排后的RetrievedChunk对象（保留所有字段，只更新评分） =====
        reranked.append(
            RetrievedChunk(
                # —— 基础标识/检索/层级字段：原封不动拷贝原chunk的 ——
                document_id=chunk.document_id,
                document_name=chunk.document_name,
                chunk_id=chunk.chunk_id,
                chunk_index=chunk.chunk_index,
                content=chunk.content,
                source_page=chunk.source_page,
                source_section=chunk.source_section,
                embedding_json=chunk.embedding_json,
                retrieval_content=chunk.retrieval_content,
                chunk_role=chunk.chunk_role,
                parent_chunk_id=chunk.parent_chunk_id,
                parent_title=chunk.parent_title,
                block_type=chunk.block_type,
                child_index=chunk.child_index,
                table_row_from=chunk.table_row_from,
                table_row_to=chunk.table_row_to,
                # —— 评分字段更新 ——
                vector_score=chunk.vector_score,       # 向量分不变（还是粗排的归一化分）
                keyword_score=retrieval_keyword_score, # keyword_score保留粗排BM25的归一化分
                final_score=final_score,               # ⭐final_score是精排后的加权融合分，作为排序第一关键字
                matched_child_content=chunk.matched_child_content,  # 保留命中leaf溯源内容
            )
        )

    # ===== 步骤3：按精排final_score降序排序，取Top K返回 =====
    # 排序优先级（3级从高到低）：
    #   1. final_score  → 精排加权融合分（最核心的排序依据）
    #   2. vector_score → 向量语义分（精排分相同时，语义更相关的排前，更稳定可靠）
    #   3. chunk_index  → 文档内块序号（前两项相同时，文档靠前的块优先，保证排序确定性tie-breaker）
    reranked.sort(
        key=lambda item: (item.final_score, item.vector_score, item.chunk_index),
        reverse=True,  # 整体降序（分数越高越靠前）
    )
    # 返回Top K条精排结果；如果候选数不足top_k，Python切片自动取全部，不会报错
    return reranked[:top_k]




def load_parent_chunks_by_ids(
    # SQLAlchemy数据库会话对象，用于执行查询
    db: Session,
    # 独立参数分隔符：强制后续参数必须以关键字形式传递
    *,
    # 用户ID：双重权限校验，防止越权加载其他用户的父块数据
    user_id: int,
    # 父块ID列表：来自上一步的命中leaf命中结果中提取的parent_chunk_id（去重后）
    parent_chunk_ids: Sequence[int],
) -> list[RetrievedChunk]:
    """
    【按ID批量加载父块（Parent Chunks）】

    功能说明：
        根据传入的 parent_chunk_ids 列表，从 knowledge_chunks 表中批量查询角色为
        KNOWLEDGE_CHUNK_ROLE_PARENT（父块）的完整数据，并关联 knowledge_documents 表获取文档名称。

    与 load_chunks_by_ids 的核心区别（为什么要有两个不同的加载函数？）：
        ┌────────────────────────┬──────────────────────────────┬──────────────────────────────┐
        │ 对比项                  │ load_chunks_by_ids（加载leaf）│ load_parent_chunks_by_ids    │
        ├────────────────────────┼──────────────────────────────┼──────────────────────────────┤
        │ chunk_role限制          │ 只加载LEAF叶子块              │ 只加载PARENT父块             │
        │ 返回顺序保证            │ ✅ 严格按传入chunk_ids顺序    │ ❌ 不保证顺序（调用方自己转字典）│
        │ 评分数段vector_score等  │ ✅ 有（leaf是直接命中的结果） │ ❌ 无（parent的分数由leaf聚合）│
        │ 典型调用方              │ FAISS向量检索后加载命中块     │ _expand_leaf_hits_to_parent_  │
        │                        │                              │ context（Small-to-Big流程中）│
        └────────────────────────┴──────────────────────────────┴──────────────────────────────┘

    注意：本函数返回结果顺序与传入 parent_chunk_ids 的顺序**不一定一致**，
    调用方需要像 _expand_leaf_hits_to_parent_context 中那样先构建字典
    parent_map = {item.chunk_id: item for item in load_parent_chunks_by_ids(...)} 再使用。

    【例子】Small-to-Big检索流程中加载父块
    场景：
        用户搜索「如何配置小爱同学的WiFi」，经过向量检索后得到3个leaf命中：
          leaf_id=1001, parent_chunk_id=500  （命中√）
          leaf_id=1002, parent_chunk_id=500  （命中√，同一个父块下的另一个leaf）
          leaf_id=2001, parent_chunk_id=600  （命中√，另一篇文档的父块）
        经过去重后：parent_chunk_ids = [500, 600]

    调用：
        parent_chunks = load_parent_chunks_by_ids(
            db,
            user_id=123,
            parent_chunk_ids=[500, 600],
        )

    步骤1：快速通道检查 → 列表非空，继续

    步骤2：执行SQL查询（4个过滤条件）
        SELECT
            c.id              AS chunk_id,
            c.document_id,
            c.chunk_index,
            c.content,              ←【关键：父块的大块完整内容】
            c.retrieval_content,
            c.source_page,
            c.source_section,
            c.embedding_json,
            c.chunk_role,
            c.parent_chunk_id,
            c.parent_title,
            c.block_type,
            c.child_index,
            c.table_row_from,
            c.table_row_to,
            d.name            AS document_name
        FROM knowledge_chunks c
        JOIN knowledge_documents d ON d.id = c.document_id
        WHERE c.user_id = 123                          ← 条件1：父块属于用户123
          AND d.user_id = 123                          ← 条件2：所属文档也属于用户123（双重校验）
          AND c.id IN (500, 600)                       ← 条件3：ID在传入列表中
          AND c.chunk_role = 'PARENT'                  ← 条件4：只取父块角色！⭐核心过滤

    【重要！】为什么第4个过滤条件 chunk_role='PARENT' 必不可少？
        假设数据库中有人不小心把 chunk_id=500 从 PARENT 改成了 LEAF（或数据迁移出错），
        如果不加这个校验，这里会把leaf当成parent加载返回，
        导致_small-to-big流程中返回的内容是小块内容（而不是预期的大块上下文），
        RAG给LLM的上下文严重不足，回答质量骤降！
        这个条件相当于「安全护栏」，保证返回的一定是大块父块内容。

    假设数据库返回rows顺序（SQL IN不保证顺序，可能是乱的）：
        row0（对应chunk_id=600）：
          content = "第四章 智能音箱配置大全（共800字：WiFi/蓝牙/语音唤醒/恢复出厂...）"
          document_name = "智能家居设备手册.pdf", chunk_role="PARENT"
        row1（对应chunk_id=500）：
          content = "2.3 小爱音箱联网步骤（共600字：下载APP→开机→配网→...）"
          document_name = "小爱同学使用指南.pdf", chunk_role="PARENT"
        （注意：chunk_id=700如果在列表中但chunk_role='LEAF' → 会被WHERE过滤掉，不会返回）

    步骤3：逐行转换为RetrievedChunk对象 + 空值降级处理
        - source_section：None → ""（空字符串）
        - embedding_json：None → ""（父块可能没算embedding，因为检索是在leaf层做的）
        - chunk_role：None → KNOWLEDGE_CHUNK_ROLE_PARENT（兜底值，保证下游识别为父块）
        - block_type：None → "text"（默认文本块）
        - child_index：None → 0（父块本身无子索引概念，设为0）

    步骤4：返回结果（2条，顺序=SQL返回顺序：600在前，500在后）
        [
            RetrievedChunk(chunk_id=600, content="第四章 智能音箱配置大全...", chunk_role="PARENT", ...),
            RetrievedChunk(chunk_id=500, content="2.3 小爱音箱联网步骤...", chunk_role="PARENT", ...),
        ]

    【调用方后续处理】_expand_leaf_hits_to_parent_context 中接收到这个乱序结果后，
    会立刻构建字典 parent_map = {500:chunk500, 600:chunk600}，
    后续通过 parent_map.get(group_id) 方式查找，完全不依赖原始返回顺序。
    """
    # 快速通道：parent_chunk_ids为空列表 → 直接返回空，避免执行无效SQL查询
    if not parent_chunk_ids:
        return []

    # ===== 步骤1：SQLAlchemy查询，一次性批量加载所有指定ID的父块 =====
    rows = (
        db.query(
            # —— 从knowledge_chunks表查询的字段（父块本身的字段）——
            KnowledgeChunks.id.label("chunk_id"),     # 块ID → 重命名为chunk_id匹配RetrievedChunk字段
            KnowledgeChunks.document_id,                # 所属文档ID
            KnowledgeChunks.chunk_index,                # 文档内的块序号（第几块）
            KnowledgeChunks.content,                    # ⭐【核心】父块的大块完整内容（给LLM的上下文）
            KnowledgeChunks.retrieval_content,          # 检索用增强内容（可能比content更精简/有额外关键词）
            KnowledgeChunks.source_page,                # 来源页码（PDF等分页文档的页码，可能None）
            KnowledgeChunks.source_section,             # 来源章节标题（可能None）
            KnowledgeChunks.embedding_json,             # 向量embedding（父块可能没算，因为检索在leaf层做）
            KnowledgeChunks.chunk_role,                 # 块角色：确保=PARENT（SQL WHERE中也会过滤，这里取出来用于下游识别）
            KnowledgeChunks.parent_chunk_id,            # 父块的父ID（支持多级嵌套，通常父块自己的parent_chunk_id=None）
            KnowledgeChunks.parent_title,               # 父块标题（章节名等，可能None）
            KnowledgeChunks.block_type,                 # 块类型：text/table/image等，默认text
            KnowledgeChunks.child_index,                # 在父块中的子索引（父块本身通常=0）
            KnowledgeChunks.table_row_from,             # 表格块起始行，非表格为None
            KnowledgeChunks.table_row_to,               # 表格块结束行，非表格为None
            # —— 从knowledge_documents表关联查询的字段（JOIN得到）——
            KnowledgeDocuments.name.label("document_name"),  # 文档名称/标题（JOIN关联，重命名为document_name）
        )
        # ===== JOIN关联文档表：通过外键document_id关联knowledge_documents表 =====
        .join(KnowledgeDocuments, KnowledgeDocuments.id == KnowledgeChunks.document_id)
        # ===== 4个WHERE过滤条件（AND关系） =====
        .filter(
            # 条件1：知识块的所属用户必须是当前user_id（权限校验，防止越权）
            KnowledgeChunks.user_id == user_id,
            # 条件2：关联的文档所属用户也必须是当前user_id（双重权限校验，防跨库越权）
            KnowledgeDocuments.user_id == user_id,
            # 条件3：知识块ID必须在传入的parent_chunk_ids列表中（IN子句批量查询）
            # 注：SQLAlchemy的.in_()要求传入list，所以用list()包装一下Sequence
            KnowledgeChunks.id.in_(list(parent_chunk_ids)),
            # ⭐条件4【核心安全护栏】：只加载chunk_role=PARENT的块
            # 防止数据异常导致把LEAF块当成PARENT返回，避免Small-to-Big上下文不足
            KnowledgeChunks.chunk_role == KNOWLEDGE_CHUNK_ROLE_PARENT,
        )
        # ===== 触发SQL执行，获取所有查询结果行 =====
        .all()
    )

    # ===== 步骤2：将数据库rows转换为RetrievedChunk对象列表 =====
    results: list[RetrievedChunk] = []
    for row in rows:
        results.append(
            RetrievedChunk(
                # —— 基础标识字段 ——
                document_id=row.document_id,
                document_name=row.document_name,
                chunk_id=row.chunk_id,
                chunk_index=row.chunk_index,
                content=row.content,
                source_page=row.source_page,
                # source_section：数据库为NULL/None时降级为空字符串（避免后续拼接时出现NoneType错误）
                source_section=row.source_section or "",
                # embedding_json：父块可能没预计算embedding（检索在leaf层做），NULL降级为空字符串
                embedding_json=row.embedding_json or "",
                # retrieval_content：检索增强内容，NULL降级为空字符串（降级后下游会回退用content）
                retrieval_content=row.retrieval_content or "",
                # chunk_role：数据库值兜底为PARENT（即使数据库该字段为NULL，也强制按父块处理，保证下游Small-to-Big流程稳定）
                chunk_role=row.chunk_role or KNOWLEDGE_CHUNK_ROLE_PARENT,
                parent_chunk_id=row.parent_chunk_id,
                # parent_title：章节/父块标题，NULL→""
                parent_title=row.parent_title or "",
                # block_type：块类型，默认为text（普通文本块），可能还有table表格块、image图片块等
                block_type=row.block_type or "text",
                # child_index：父块的子索引，NULL→0兜底
                child_index=row.child_index or 0,
                table_row_from=row.table_row_from,
                table_row_to=row.table_row_to,
                # ⚠️ 注意：父块本身不填 vector_score / keyword_score / final_score 等评分数段
                # 这些分数会在 _expand_leaf_hits_to_parent_context 中，由命中的leaf子块聚合（取max）后填入
            )
        )

    # ===== 步骤3：返回转换后的父块列表（顺序=SQL返回顺序，不一定等于传入parent_chunk_ids的顺序） =====
    return results


def _expand_leaf_hits_to_parent_context(
    # SQLAlchemy数据库会话对象，用于加载父块数据
    db: Session,
    # 独立参数分隔符：强制后续参数必须以关键字形式传递
    *,
    # 用户ID：数据权限校验，只能加载该用户的父块
    user_id: int,
    # 检索命中的叶子块列表（leaf_hits：小块，已经过排序/评分）
    leaf_hits: Sequence[RetrievedChunk],
    # 最终返回的父块/上下文块数量上限（Top K）
    top_k: int,
) -> list[RetrievedChunk]:
    """
    【Small-to-Big 父子块检索·核心步骤】

    设计思想（业界主流 Parent Document Retriever 模式）：
        「用小块（leaf）精确命中，用大块（parent）提供上下文」
    为什么要这么做？
        - 如果直接检索大块：上下文全，但粒度太粗，容易「块很大但只有一句话相关」→ 精度差
        - 如果直接检索小块：精度高，但上下文不足，LLM看不懂前因后果 → 回答质量差
        - 父子块结合：小块负责「精准找到命中点」，再扩展到父块「给足上下文」→ 精度+上下文两全！

    【完整流程总览】
        ① 收集命中leaf的parent_chunk_id → 去重 → 批量加载所有parent大块
        ② 按「parent_id」对leaf命中结果分组（同一个parent下可能有多个leaf都命中）
        ③ 每组找 best_hit（分最高的那个leaf，记录它的内容做matched_child_content）
        ④ 每组聚合分数：同组多个leaf的向量分/关键词分/最终分 → 都取max
        ⑤ 如果该组有parent：返回【parent的大块内容】+【聚合的分数】+【best_hit的原始命中内容（用于溯源）】
        ⑥ 如果该组没有parent（孤儿leaf，可能是未分块的小文档）：直接返回best_hit本身
        ⑦ 按final_score降序排序 → 取Top K返回

    【完整例子】用户搜索「Python安装PyPDF2」
    ┌─────────────────────────────────────────────────────────────────────────────┐
    │ 知识库结构（文档《Python实战指南》document_id=50）                            │
    │ ┌─ parent_id=800 大块：「第3章 处理PDF文件」（共600字）                     │
    │ │    ├─ leaf_id=801：「3.1 安装依赖：pip install pypdf2」（60字，命中√）    │
    │ │    ├─ leaf_id=802：「3.2 导入库：import PyPDF2」（40字，命中√）           │
    │ │    └─ leaf_id=803：「3.3 打开PDF文件」（50字，没命中）                    │
    │ └─ parent_id=900 大块：「附录A 常见问题」（500字）                          │
    │      ├─ leaf_id=901：「A.1 pip安装失败怎么办」（没命中）                    │
    │      └─ leaf_id=902：「A.2 import报错」（80字，命中√）                      │
    │ 另外有个独立短文档chunk_id=777「pip install 速查表」（无parent，独立leaf）  │
    └─────────────────────────────────────────────────────────────────────────────┘

    输入leaf_hits（已按final_score排好序的5个命中小块）：
    ┌─────────┬──────────────┬──────────────┬──────────────┬─────────────────────┐
    │leaf_id  │parent_chunk_id│ vector_score │ keyword_score│ final_score（排好序）│
    ├─────────┼──────────────┼──────────────┼──────────────┼─────────────────────┤
    │ 801     │ 800          │ 0.88         │ 0.65         │ 0.82  ←最高         │
    │ 802     │ 800          │ 0.72         │ 0.80         │ 0.75  ←同parent     │
    │ 902     │ 900          │ 0.68         │ 0.55         │ 0.63                 │
    │ 777     │ None         │ 0.61         │ 0.50         │ 0.57  ←无parent     │
    │ 804     │ 800          │ 0.50         │ 0.40         │ 0.46  ←同parent(第三个)│
    └─────────┴──────────────┴──────────────┴──────────────┴─────────────────────┘

    ═══════ 执行过程 ═══════

    步骤1：收集parent_ids + 加载parent大块
        从leaf_hits中提取非空的parent_chunk_id → {800, 800, 900, None, 800} → 去重排序 → [800, 900]
        调用load_parent_chunks_by_ids批量加载 → parent_map = {
            800: ParentChunk(id=800, content="第3章 处理PDF文件...600字完整内容..."),
            900: ParentChunk(id=900, content="附录A 常见问题...500字完整内容..."),
        }

    步骤2：按parent_id对leaf分组（group_id = parent_chunk_id or chunk_id自身）
        grouped = {
            800: [leaf801, leaf802, leaf804],  ← parent800下有3个leaf命中
            900: [leaf902],                      ← parent900下只有1个leaf命中
            777: [leaf777],                      ← 孤儿leaf自己一组（parent=None）
        }

    步骤3：逐组处理，每组生成1个expanded结果
    ┌─────────────────────────────────────────────────────────────────────┐
    │ 组A：group_id=800，hits=[leaf801(0.82), leaf802(0.75), leaf804(0.46)]│
    ├─────────────────────────────────────────────────────────────────────┤
    │  best_hit = leaf801（final_score=0.82最高）
    │  聚合分数：
    │    vector_score  = max(0.88, 0.72, 0.50) = 0.88
    │    keyword_score = max(0.65, 0.80, 0.40) = 0.80
    │    final_score   = max(0.82, 0.75, 0.46) = 0.82
    │  parent_map里有800 → 走parent分支：
    │    【content】= parent800的大块内容（「第3章 处理PDF文件...600字...」） ←给LLM完整上下文
    │    【matched_child_content】= leaf801的原始内容（「3.1 安装依赖：pip install pypdf2」）←记录精准命中点，方便rerank溯源
    │    chunk_role = PARENT
    │    final_score = 0.82
    └─────────────────────────────────────────────────────────────────────┘
    ┌─────────────────────────────────────────────────────────────────────┐
    │ 组B：group_id=900，hits=[leaf902(0.63)]                              │
    ├─────────────────────────────────────────────────────────────────────┤
    │  best_hit=leaf902，聚合各分数都等于leaf902自身的分数（只有一个hit）
    │  parent_map有900 → 走parent分支：content=「附录A...500字」
    │  final_score=0.63
    └─────────────────────────────────────────────────────────────────────┘
    ┌─────────────────────────────────────────────────────────────────────┐
    │ 组C：group_id=777，hits=[leaf777(0.57)]（parent=None孤儿leaf）      │
    ├─────────────────────────────────────────────────────────────────────┤
    │  没有parent → 走else分支：直接用best_hit=leaf777自身的小块内容返回
    │  （适用于本身就很短的文档，没必要分父块）
    │  final_score=0.57
    └─────────────────────────────────────────────────────────────────────┘

    步骤4：排序 + Top K（top_k=2）
        expanded 列表现在有3条：
          [ Parent800(final=0.82), Parent900(final=0.63), Leaf777(final=0.57) ]
        按 (final_score, vector_score, keyword_score) 降序排序 → 顺序不变
        expanded[:2] → 返回 [Parent800, Parent900]  ← Top 2

    【最终结果给RAG的好处】
        LLM拿到的是600字的完整章节「第3章 处理PDF文件」，而不是只拿到60字的「pip install pypdf2」，
        能理解前因后果（安装后怎么导入、怎么用），回答质量大幅提升！
    """
    # 快速通道：没有命中的leaf块 → 直接返回空列表
    if not leaf_hits:
        return []

    # ===== 步骤1：收集所有命中leaf对应的parent_chunk_id，去重并排序 =====
    # 使用集合推导式去重：同一个parent下可能有多个leaf命中，只需加载parent一次
    # 过滤条件 if hit.parent_chunk_id is not None：跳过没有parent的「孤儿leaf」
    parent_ids = sorted(
        {
            int(hit.parent_chunk_id)
            for hit in leaf_hits
            if hit.parent_chunk_id is not None
        }
    )
    # ===== 从数据库批量加载所有parent大块，构建字典方便O(1)查找 =====
    # parent_map: key = parent_chunk_id，value = 父块RetrievedChunk对象
    parent_map = {
        item.chunk_id: item
        for item in load_parent_chunks_by_ids(
            db,
            user_id=user_id,
            parent_chunk_ids=parent_ids,
        )
    }

    # ===== 步骤2：按「parent_id」对leaf命中结果进行分组 =====
    # grouped字典：key = group_id（parent_chunk_id如果有，否则用leaf自己的chunk_id）
    #              value = 属于该组的所有命中leaf列表
    grouped: dict[int, list[RetrievedChunk]] = {}
    for hit in leaf_hits:
        # 分组ID选择逻辑：有parent就用parent_id归组，没有就自己单独一组
        # 这样：有parent的多个leaf会被合并到同一组，无parent的leaf各自一组
        group_id = int(hit.parent_chunk_id or hit.chunk_id)
        # setdefault：如果该group_id还没有列表，先初始化空列表，再append当前hit
        grouped.setdefault(group_id, []).append(hit)

    # 保存扩展后的结果列表（每组生成1条结果）
    expanded: list[RetrievedChunk] = []

    # ===== 步骤3：遍历每个分组，每组生成1条扩展后的结果 =====
    for group_id, hits in grouped.items():
        # 从parent_map中尝试获取该组对应的父块对象（可能为None：孤儿leaf）
        parent = parent_map.get(group_id)
        # ===== 找同组内「分数最高」的best_hit =====
        # 三级排序优先级：final_score（最终分，最优先）→ vector_score（向量分）→ keyword_score（关键词分）
        # best_hit 用途：① 记录matched_child_content（精准命中的小块内容）② parent不存在时作为降级返回
        best_hit = max(
            hits,
            key=lambda item: (item.final_score, item.vector_score, item.keyword_score),
        )

        # ===== 聚合该组所有hits的分数：每个维度都取组内最大值 =====
        # 为什么用max而不是平均/求和？
        #   max代表「这个父块区域最强的一个命中信号」，不会因为同组有多个弱命中而虚高分数，更符合直觉
        #   例：同组有1个命中0.9 + 2个命中0.5 → 父块分=0.9（而不是(0.9+0.5+0.5)/3≈0.63）更合理
        vector_score = max(item.vector_score for item in hits)
        keyword_score = max(item.keyword_score for item in hits)
        final_score = max(item.final_score for item in hits)

        # ===== 分支A：该组有对应的parent大块 → 返回大块内容，给足上下文 =====
        if parent is not None:
            expanded.append(
                RetrievedChunk(
                    # —— 基础标识字段：用PARENT的（因为返回的是父块）——
                    document_id=parent.document_id,
                    document_name=parent.document_name,
                    chunk_id=parent.chunk_id,
                    chunk_index=parent.chunk_index,
                    # ⭐【核心】content用PARENT的大块内容（给LLM完整上下文）
                    content=parent.content,
                    source_page=parent.source_page,
                    source_section=parent.source_section,
                    embedding_json=parent.embedding_json,
                    # retrieval_content用best_hit的：保留小块的检索特征（rerank可能用到）
                    retrieval_content=best_hit.retrieval_content or best_hit.content,
                    # 标记角色为PARENT父块
                    chunk_role=KNOWLEDGE_CHUNK_ROLE_PARENT,
                    parent_chunk_id=parent.chunk_id,
                    parent_title=parent.parent_title or best_hit.parent_title,
                    block_type=parent.block_type or best_hit.block_type,
                    child_index=0,
                    table_row_from=parent.table_row_from,
                    table_row_to=parent.table_row_to,
                    # —— 评分字段：用前面聚合的组内max值 ——
                    vector_score=vector_score,
                    keyword_score=keyword_score,
                    final_score=final_score,
                    # ⭐【溯源关键字段】记录精准命中的leaf小块内容
                    # 作用：① rerank重排序时保留精确命中信号 ② Debug时知道「这个父块是因为哪句话被命中的」
                    # （这个字段是不落库的，仅检索阶段临时使用）
                    matched_child_content=best_hit.content,
                )
            )
            # continue跳过后面的else分支，进入下一个组的循环
            continue

        # ===== 分支B：该组没有parent（孤儿leaf，独立小块） → 原样返回best_hit自身 =====
        # 适用场景：本身很短的文档/FAQ问答对，没必要拆分父子块，直接用小块内容即可
        expanded.append(
            RetrievedChunk(
                # —— 基础标识字段：直接用best_hit自身的 ——
                document_id=best_hit.document_id,
                document_name=best_hit.document_name,
                chunk_id=best_hit.chunk_id,
                chunk_index=best_hit.chunk_index,
                content=best_hit.content,
                source_page=best_hit.source_page,
                source_section=best_hit.source_section,
                embedding_json=best_hit.embedding_json,
                retrieval_content=best_hit.retrieval_content,
                chunk_role=best_hit.chunk_role,
                parent_chunk_id=best_hit.parent_chunk_id,
                parent_title=best_hit.parent_title,
                block_type=best_hit.block_type,
                child_index=best_hit.child_index,
                table_row_from=best_hit.table_row_from,
                table_row_to=best_hit.table_row_to,
                # —— 评分字段：聚合的组内max值（虽然孤儿leaf只有1个hit，值等于自身）——
                vector_score=vector_score,
                keyword_score=keyword_score,
                final_score=final_score,
                # 同样记录matched_child_content（等于自身内容，统一结构方便下游处理）
                matched_child_content=best_hit.content,
            )
        )

    # ===== 步骤4：排序 + 返回Top K结果 =====
    # 排序优先级（从高到低）：
    #   1. final_score  → 最终综合分（向量+关键词+精排融合，最优先）
    #   2. vector_score → 向量语义分（综合分相同时，语义相关的排前）
    #   3. keyword_score → 关键词匹配分（前两项相同时，字面命中强的排前）
    # reverse=True → 整体降序排列（分数越高越靠前）
    expanded.sort(
        key=lambda item: (item.final_score, item.vector_score, item.keyword_score),
        reverse=True,
    )
    # 返回Top K条；如果expanded数量不足top_k，Python切片自动取全部不会报错
    return expanded[:top_k]

def search_similar_chunks(
    # SQLAlchemy数据库会话对象，贯穿整个检索流程使用
    db: Session,
    # 独立参数分隔符：强制后续参数必须以关键字形式传递，避免参数顺序混乱
    *,
    # 用户ID：数据权限隔离，只检索该用户私有知识库下的内容
    user_id: int,
    # 查询文本的embedding向量（调用方已通过Embedding模型计算好，形状通常是768/1024/1536维等）
    query_embedding: list[float],
    # 可选：用户原始查询文本（问题字符串）。
    #   - 有值（非空）：走【混合检索】= 向量检索 + BM25关键词检索 双路融合（效果最好，推荐）
    #   - None/空字符串：走【纯向量检索】= 只靠语义相似度匹配（无query_text场景，比如纯图片embedding检索）
    query_text: str | None = None,
    # 可选：限定检索范围为指定文档ID列表，None表示检索当前用户所有文档
    document_ids: Sequence[int] | None = None,
    # 期望返回的结果数量（Top K），最终返回结果数 <= 这个值
    top_k: int = 10,
    # 相似度阈值：低于此分数的结果会被过滤（当前代码段中未显式使用，由调用方或后续过滤处理）
    threshold: float = 0.5,
    # 是否开启rerank精排：True=开启（返回粗排结果后由调用方进一步精排），当前函数本身返回粗排结果
    rerank: bool = True,
) -> list[RetrievedChunk]:
    """
    【检索层对外总入口】RAG系统调用检索时的顶层函数，根据是否有query_text自动选择检索策略。

    整体设计模式：门面模式（Facade Pattern）
        上层调用方（如rag.py、chat_service.py等）只需要调用这一个函数即可，
        不需要关心内部是走混合检索、纯向量检索、FAISS还是暴力计算，以及Small-to-Big扩展等细节，
        本函数内部自动完成路由和所有处理，直接返回给LLM可用的父块上下文列表。

    两个分支策略（核心逻辑）：
    ┌────────────────────────────────────────────────────────────────────────────────────┐
    │ 分支A：query_text 有有效内容（非空非空白） → 调用 hybrid_search() 混合检索            │
    │   流程：FAISS向量 + BM25关键词 → 各自归一化 → 加权融合(65%:35%) → 粗排Top 3K leaf │
    │         → Small-to-Big扩展parent → 返回Top 2K parent大块结果                       │
    │   特点：兼顾语义相似度 + 关键词精确匹配，命中率最高，是绝大多数场景的最优解          │
    ├────────────────────────────────────────────────────────────────────────────────────┤
    │ 分支B：query_text 为 None / 空字符串  → 纯向量检索（无BM25关键词分）                │
    │   流程：FAISS向量检索（失败降级暴力计算）→ 粗排Top 3K leaf → Small-to-Big扩展parent │
    │         → 返回Top 2K parent大块结果                                                 │
    │   适用场景：(1) 纯向量匹配任务（如以图搜文、以文搜向量）                             │
    │            (2) 调用方只拿到了embedding拿不到原始文本（前端未传query_text）          │
    │            (3) 极端追求性能，不想算BM25（场景极少，不推荐）                          │
    └────────────────────────────────────────────────────────────────────────────────────┘

    【完整例子1：常规场景：用户提问，有query_text → 走混合检索分支A】
    调用：
        results = search_similar_chunks(
            db,
            user_id=123,
            query_embedding=[0.12, -0.05, 0.88, ...],  # 768维embedding向量
            query_text="如何用Python批量提取PDF中的表格数据？",  # ← 有文本，走混合检索！
            document_ids=[50, 51],  # 只在这两篇文档里搜
            top_k=5,
            threshold=0.4,
            rerank=True,
        )
    执行路径：
        检查 query_text.strip() 非空 → 为True
        → 直接调用 hybrid_search(db, user_id=123, query_text="如何用Python...", ..., top_k=5)
        → 内部执行：两路召回4K条 → 归一化+65%:35%融合 → 粗排截3K → 扩展parent → 返回Top 10条parent大块
    返回示例（5条RetrievedChunk，都是PARENT大块，给LLM完整上下文）：
        [
          RetrievedChunk(chunk_id=800, chunk_role="PARENT", content="第3章 处理PDF文件...600字...", final_score=0.952, matched_child_content="3.2 pdfplumber提取表格..."),
          RetrievedChunk(chunk_id=810, chunk_role="PARENT", content="附录...500字...", final_score=0.712, matched_child_content="..."),
          ... 共5条 ...
        ]

    【完整例子2：纯向量场景：调用方只拿到embedding，没原始query_text → 走纯向量分支B】
    场景：前端输入一段语音，ASR模块直接返回了语音的embedding向量（或者以图搜文场景），
          没有对应的文本字符串，只能走纯向量检索。
    调用：
        results = search_similar_chunks(
            db,
            user_id=123,
            query_embedding=[0.09, -0.12, 0.76, ...],
            query_text=None,  # ← 没有文本，走纯向量检索！
            document_ids=None,  # 搜用户整个知识库
            top_k=10,
        )
    执行路径：
        检查 if query_text and query_text.strip() → None → False，跳过混合检索分支
        
        步骤1：leaf_hits = _search_similar_chunks_by_faiss(..., top_k = max(10x3,10)=30)
          → FAISS索引正常，返回30条leaf小块（vector_score排序好的）
          → leaf_hits 不是 None，不走暴力降级分支
        
        步骤2：调用 _expand_leaf_hits_to_parent_context(leaf_hits=30条, top_k = max(10x2,10)=20)
          → 30条leaf按parent_id分组 → 加载对应PARENT大块 → 同组多leaf分数取max聚合
          → 排序后返回Top 20条PARENT大块（给RAG/LLM使用的完整上下文）
    返回：20条RetrievedChunk列表，每条的vector_score有值，keyword_score=0（纯向量没算BM25），
          final_score = max组内leaf的分数，content都是PARENT大块完整内容。

    【降级场景：FAISS索引损坏，纯向量分支自动降级】
    执行到 _search_similar_chunks_by_faiss() → 索引不存在/加载失败 → 返回 None
    → if leaf_hits is None: 触发 → 调用 _search_similar_chunks_by_bruteforce() 暴力余弦计算
    → 虽然慢（O(N)遍历所有chunk），但服务不中断，用户感知不到内部降级，只是响应稍慢。
    """
    # ========== 分支A判断：如果query_text有有效内容，走【混合检索】最优路径 ==========
    # query_text and query_text.strip() 两层判断：
    #   1. query_text 为None → 短路不执行strip()，避免NoneType报错
    #   2. query_text 全是空格/换行（如 "   "）→ strip()后为""，布尔值False，也判定为无有效文本，不走混合检索
    if query_text and query_text.strip():
        # 调用 hybrid_search：内部做 FAISS向量 + BM25关键词 → 归一化+加权融合 → 粗排 → 扩展parent块
        # 这是推荐的默认路径，兼顾语义匹配和关键词精确匹配，检索质量最高
        return hybrid_search(
            db,
            user_id=user_id,
            query_text=query_text,            # 用户原始问题（用于BM25分词+关键词奖励）
            query_embedding=query_embedding,  # 预计算好的查询embedding向量
            document_ids=document_ids,
            top_k=top_k,                      # 期望返回Top K
        )

    # ========== 分支B：query_text为None/空 → 退化为【纯向量检索】 ==========
    # 注意：纯向量检索没有BM25关键词分，keyword_score全部为0，检索质量略低于混合检索
    # 漏斗策略第一级放大：leaf层召回数量 = top_k x 3（比混合检索的4倍稍保守，因为只有一路召回）
    leaf_hits = _search_similar_chunks_by_faiss(
        db,
        user_id=user_id,
        query_embedding=query_embedding,  # 只靠embedding做语义相似度匹配
        query_text=query_text,            # 可能为None，传进去让内部计算关键词奖励分（如果有embedding也有文本的话，但这里一般是None）
        document_ids=document_ids,
        top_k=max(top_k * 3, top_k),      # top_k x 3 放大召回，保证召回率，后续再收敛
    )
    # ⭐ 高可用降级：FAISS检索返回None（索引不存在/损坏/加载失败）→ 回退到暴力余弦遍历计算
    # 这是生产环境重要的故障容错机制，保证即使索引坏了，检索服务依然可用（只是变慢）
    if leaf_hits is None:
        leaf_hits = _search_similar_chunks_by_bruteforce(
            db,
            user_id=user_id,
            query_embedding=query_embedding,
            query_text=query_text,
            document_ids=document_ids,
            top_k=max(top_k * 3, top_k),  # 降级后也保持相同的召回放大倍数
        )

    # ========== 两个分支最终都要走：Small-to-Big 扩展为父块上下文 ==========
    # （分支A的混合检索其实已经在内部调用了这一步，分支B纯向量检索在这里显式调用）
    # 漏斗策略第二级收敛：传给扩展函数的top_k = top_k x 2，给后续rerank精排留足候选择优
    return _expand_leaf_hits_to_parent_context(
        db,
        user_id=user_id,
        leaf_hits=leaf_hits,                      # 粗排后的leaf命中列表（3K量级）
        top_k=max(top_k * 2, top_k),              # 扩展后返回Top 2K条parent大块
    )
