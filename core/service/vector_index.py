"""
向量索引服务模块（支持 ANN 近似最近邻索引升级）

该模块提供基于 FAISS（Facebook AI Similarity Search）的向量索引功能，
用于实现高效的文本语义检索。从原来的纯暴力 IndexFlatIP 升级为支持：
  - Flat：暴力精确搜索，O(N)，适合<1万条
  - HNSW：层次化小世界图，O(logN)，推荐默认（精度/速度平衡最好）
  - IVF：倒排文件索引，O(logN)，构建速度比HNSW快
  - IVF_PQ：IVF + 乘积量化压缩，超大规模时内存优化

主要功能：
1. 从数据库加载知识块的嵌入向量并构建 FAISS 索引（4种类型可选）
2. 对用户查询进行语义搜索，返回最相关的知识块
3. 智能降级：数据量小时自动用 Flat（精确搜索，没必要ANN）
4. 元数据兼容：新旧格式索引文件都能加载

索引选型决策树（配置 FAISS_INDEX_TYPE 时参考）：
┌──────────────────────────────────────────────────────────────────────┐
│  单用户 chunk 数 < 1万   →  Flat（精确，ANN开销反而更大）            │
│  单用户 chunk 数 1万~500万 →  HNSW64（推荐默认，Recall@10 ≈ 99%）    │
│  单用户 chunk 数 50万~500万 →  IVF1024（构建快3倍，Recall@10 ≈ 95%） │
│  单用户 chunk 数 > 500万   →  IVF4096,PQ64（压缩94%内存空间）        │
└──────────────────────────────────────────────────────────────────────┘

环境变量配置示例（写入项目根目录的 .env 文件）：
    # 方案A：通用推荐（默认就是这个，不用写也行）
    FAISS_INDEX_TYPE=HNSW
    FAISS_HNSW_M=64

    # 方案B：极速构建（赶时间，索引5分钟内要建完）
    FAISS_INDEX_TYPE=IVF
    FAISS_IVF_NLIST=1024

    # 方案C：内存紧张（服务器内存<8GB，数据又多）
    FAISS_INDEX_TYPE=IVF_PQ
    FAISS_PQ_BYTES=64

依赖说明：
- FAISS：Facebook 开源的高效相似性搜索库
- NumPy：数值计算库
- SQLAlchemy：数据库 ORM
"""

# 启用 Python 3.7+ 的类型注解向后兼容
from __future__ import annotations
from core.db.models import KnowledgeChunks, KNOWLEDGE_CHUNK_ROLE_LEAF
import json
# 用于定义不可变的数据类
from dataclasses import dataclass
from pathlib import Path
from typing import Any
# 用于记录索引创建时间，方便排查新旧索引
from datetime import datetime

# SQLAlchemy 数据库会话
from sqlalchemy.orm import Session

# 导入项目配置和数据库模型
from core.config import settings
from core.db.models import KnowledgeChunks

# 尝试导入 FAISS 和 NumPy，处理导入失败的情况
try:
    import faiss  # type: ignore
    import numpy as np
except ImportError:  # pragma: no cover
    faiss = None
    np = None


#这样声明代表数据类，不可变
@dataclass(frozen=True)
class FaissSearchHit:
    """
    FAISS 搜索结果数据类

    用于存储单次搜索命中的结果信息，包含匹配的知识块元数据和相似度分数。

    属性：
        row_id: 索引中的行ID（FAISS内部索引位置）
        chunk_id: 知识块ID（对应数据库中的 KnowledgeChunks.id）
        document_id: 文档ID（对应数据库中的 document_id）
        score: 相似度分数（内积值，范围通常为[-1, 1]，值越大越相似）
    """
    row_id: int
    chunk_id: int
    document_id: int
    score: float


def faiss_available() -> bool:
    """
    检查 FAISS 和 NumPy 是否可用

    返回：
        bool: 如果 FAISS 和 NumPy 都已正确安装则返回 True，否则返回 False
    """
    return faiss is not None and np is not None


def ensure_faiss_index_dir() -> Path:
    """
    确保 FAISS 索引目录存在

    如果目录不存在，则自动创建（包括所有父目录）。

    返回：
        Path: FAISS 索引目录的路径对象
    """
    index_dir = Path(settings.FAISS_INDEX_DIR)
    index_dir.mkdir(parents=True, exist_ok=True)
    return index_dir


def _index_file_path(user_id: int) -> Path:
    """
    获取指定用户的 FAISS 索引文件路径

    参数：
        user_id: 用户ID

    返回：
        Path: 索引文件路径，格式为 {FAISS_INDEX_DIR}/user_{user_id}.faiss
    """
    return ensure_faiss_index_dir() / f"user_{user_id}.faiss"


def _metadata_file_path(user_id: int) -> Path:
    """
    获取指定用户的索引元数据文件路径

    元数据文件存储了向量索引与数据库记录的映射关系。

    参数：
        user_id: 用户ID

    返回：
        Path: 元数据文件路径，格式为 {FAISS_INDEX_DIR}/user_{user_id}.json
    """
    return ensure_faiss_index_dir() / f"user_{user_id}.json"


def _tmp_path(path: Path) -> Path:
    """
    生成临时文件路径

    在写入索引和元数据时，先写入临时文件，成功后再替换原文件，
    避免写入过程中程序崩溃导致文件损坏。

    参数：
        path: 原始文件路径

    返回：
        Path: 临时文件路径，在原扩展名后添加 .tmp
    """
    return path.with_suffix(path.suffix + ".tmp")


def _parse_embedding_json(raw: str | list[float] | None) -> list[float]:
    """
    解析嵌入向量的 JSON 数据

    支持多种输入格式：
    1. None -> 返回空列表
    2. 已解析的 float 列表 -> 直接返回（转换为 float 类型）
    3. JSON 字符串 -> 解析为列表

    参数：
        raw: 嵌入向量数据，可以是 JSON 字符串、float 列表或 None

    返回：
        list[float]: 解析后的嵌入向量列表，解析失败返回空列表
    """
    if raw is None:
        return []
    # 如果raw为列表，则直接返回（转换为 float 类型）
    if isinstance(raw, list):
        return [float(value) for value in raw]
    # 清理首尾空白字符
    text = str(raw).strip()
    if not text:
        return []

    try:
        # 尝试解析为 JSON 列表
        payload = json.loads(text)
    except json.JSONDecodeError:
        return []

    if not isinstance(payload, list):
        return []

    return [float(value) for value in payload]


def _normalize_matrix(matrix: Any):
    """
    对向量矩阵进行 L2 归一化

    L2 归一化将向量转换为单位向量，使得向量的模长为 1。
    这样可以将内积运算等价于余弦相似度计算。

    参数：
        matrix: NumPy 数组形式的向量矩阵

    返回：
        numpy.ndarray: 归一化后的矩阵，保持 float32 类型和连续内存布局
    """
    # 确保矩阵是连续的 float32 数组
    matrix = np.ascontiguousarray(matrix, dtype="float32")
    if matrix.size == 0:
        return matrix

    # 使用 FAISS 的 L2 归一化函数
    faiss.normalize_L2(matrix)
    return matrix


def _create_faiss_index(dimension: int, num_vectors: int):
    """
    根据配置创建 FAISS 索引对象（ANN 近似最近邻索引工厂函数）

    这是本次升级的核心函数，替代原来硬编码的 `faiss.IndexFlatIP(dimension)`。
    支持 4 种索引类型，并且会根据数据规模自动做智能降级（数据太小没必要用ANN）。

    ┌────────────────────────────────────────────────────────────────────┐
    │                        索引创建流程示意                             │
    ├────────────────────────────────────────────────────────────────────┤
    │                                                                    │
    │   输入: dimension=1536, num_vectors=50000                          │
    │           │                                                        │
    │           ▼                                                        │
    │   ┌─────────────────┐                                              │
    │   │ 读取配置类型     │ → FAISS_INDEX_TYPE (默认 HNSW)              │
    │   └────────┬────────┘                                              │
    │            │                                                       │
    │            ▼                                                       │
    │   ┌─────────────────┐                                              │
    │   │ 智能降级判断？   │ → num_vectors < 10000 ?                      │
    │   │                 │   是 → 强制用 Flat（精确且更快）              │
    │   └────────┬────────┘   否 → 按配置类型走                          │
    │            │                                                       │
    │            ├───────────────────────────────────────┐               │
    │            ▼                                       ▼               │
    │   ┌─────────────────────┐              ┌─────────────────────┐    │
    │   │ 类型=HNSW           │              │ 类型=IVF             │    │
    │   │ IndexHNSWFlat       │              │ IndexIVFFlat         │    │
    │   │ - M=64 邻居数       │              │ - nlist=1024 桶数    │    │
    │   │ - efSearch=128      │              │ - nprobe=16 探查桶   │    │
    │   │ - is_trained=True   │              │ - quantizer=FlatIP   │    │
    │   │ (无需训练，直接add) │              │ - is_trained=False ⚠ │    │
    │   └─────────────────────┘              └──────────┬──────────┘    │
    │                                                    │               │
    │                                                    ▼               │
    │                                              需要先 train()        │
    │                                              K-means 找聚类中心    │
    │                                              然后才能 add()        │
    │                                                    │               │
    │   ┌─────────────────────┐                            │               │
    │   │ 类型=IVF_PQ         │                            │               │
    │   │ IndexIVFPQ          │                            │               │
    │   │ + 乘积量化压缩      │                            │               │
    │   │ 6KB/条 → 64字节/条  │                            │               │
    │   │ is_trained=False ⚠  │                            │               │
    │   └─────────────────────┘                            │               │
    │                                                    │               │
    │   ┌─────────────────────┐                            │               │
    │   │ 类型=Flat           │                            │               │
    │   │ IndexFlatIP         │                            │               │
    │   │ 暴力精确 O(N)       │                            │               │
    │   │ is_trained=True     │                            │               │
    │   └─────────────────────┘                            │               │
    │                                                        │               │
    │            ┌───────────────────────────────────────────┘               │
    │            ▼                                                           │
    │   返回 faiss.Index 对象（可能 trained 或 未trained）                   │
    │   调用方需要检查 index.is_trained，未trained的先 train(matrix) 再 add │
    └────────────────────────────────────────────────────────────────────────┘

    Args:
        dimension: 向量维度（如 768 / 1024 / 1536）
        num_vectors: 待入库的向量总数，用于智能降级和参数自动调优

    Returns:
        faiss.Index: 创建好的 FAISS 索引对象（未添加任何向量）

    ═══════════════════════════════════════════════════════════════════════
    使用示例（单独调用这个函数做测试）：
    ═══════════════════════════════════════════════════════════════════════

    >>> # 示例1：50万条向量，默认HNSW
    >>> index = _create_faiss_index(dimension=1536, num_vectors=500000)
    >>> type(index).__name__
    'IndexHNSWFlat'
    >>> index.hnsw.M
    64

    >>> # 示例2：只有5000条 → 智能降级为Flat（精确搜索）
    >>> index = _create_faiss_index(dimension=1536, num_vectors=5000)
    >>> type(index).__name__
    'IndexFlatIP'

    >>> # 示例3：IVF类型（需要先train）
    >>> import numpy as np
    >>> index = _create_faiss_index(dimension=1536, num_vectors=100000)
    >>> # 假设 settings.FAISS_INDEX_TYPE="IVF"
    >>> index.is_trained  # IVF默认没训练
    False
    >>> # 需要喂一批数据做K-means聚类（找桶中心）
    >>> data = np.random.randn(100000, 1536).astype('float32')
    >>> faiss.normalize_L2(data)
    >>> index.train(data)  # 这步要几秒~几分钟
    >>> index.is_trained
    True
    >>> index.add(data)   # 训练好后才能加向量

    ═══════════════════════════════════════════════════════════════════════
    """
    # 读取配置的索引类型，统一转大写方便比较
    index_type = settings.FAISS_INDEX_TYPE.upper()

    # ─────────────────────────────────────────────────────────
    # 智能降级：数据量太小时，没必要用 ANN，Flat 反而更快且精确
    #   - ANN 索引本身有构建开销（HNSW建图/IVF聚类）
    #   - ANN 搜索也有常数项开销（遍历邻居图/算桶距离）
    #   - 经验阈值：<1万条时，Flat 的 O(N) 暴力扫描反而比 ANN 的 O(logN) 快
    # ─────────────────────────────────────────────────────────
    if num_vectors < 10000:
        index_type = "FLAT"

    # ─────────────────────────────────────────────────────────
    # 分支 1：Flat —— 暴力精确搜索
    #   - 复杂度：O(N)，每条向量都和 query 算一遍内积
    #   - 精度：100% 精确，没有任何召回损失
    #   - 适用：<1万条，或者对 Recall 要求 100% 的场景
    # ─────────────────────────────────────────────────────────
    if index_type == "FLAT":
        # IndexFlatIP = Inner Product（内积）索引
        # 因为我们的向量都做过 L2 归一化，内积 == 余弦相似度
        index = faiss.IndexFlatIP(dimension)
        return index

    # ─────────────────────────────────────────────────────────
    # 分支 2：HNSW —— 层次化小世界图（推荐默认）
    #   - 复杂度：O(log N)，多层贪心导航
    #   - 结构：3~4层图，上层稀疏（枢纽），下层稠密（全量节点）
    #   - 精度：Recall@10 ≈ 98% ~ 99.5%（取决于efSearch）
    #   - 优点：无需训练（is_trained=True），增量更新友好
    #   - 缺点：构建慢（比IVF慢3~5倍），内存比Flat大30%左右
    # ─────────────────────────────────────────────────────────
    if index_type == "HNSW":
        # METRIC_INNER_PRODUCT：用内积度量（L2归一化后=余弦相似度）
        # 注意：FAISS 默认是 METRIC_L2（欧氏距离），必须显式指定内积！
        index = faiss.IndexHNSWFlat(
            dimension,                      # 向量维度
            settings.FAISS_HNSW_M,          # 每个节点的邻居数 M（默认64）
            faiss.METRIC_INNER_PRODUCT      # 度量方式：内积
        )

        # 设置 HNSW 构建参数（影响索引质量）
        # efConstruction：构建每个节点时，搜索候选邻居的宽度
        #   类比：给每个人找朋友时，先大范围看多少个人选再挑最亲近的M个
        index.hnsw.efConstruction = settings.FAISS_HNSW_EF_CONSTRUCTION

        # efSearch：查询时的搜索宽度
        #   类比：找"最像的10个人"时，沿途多看多少个候选再定最终结果
        #   经验：efSearch >= top_k * 1.5 比较稳妥；FAISS内部也会自动提升
        index.hnsw.efSearch = settings.FAISS_HNSW_EF_SEARCH

        # HNSW 不需要 train 步骤（和 Flat 一样）
        # 因为它是增量式建图的，add 的过程就是构建的过程
        return index

    # ─────────────────────────────────────────────────────────
    # 分支 3：IVF —— 倒排文件索引（Inverted File）
    #   - 两阶段搜索：
    #     阶段1：计算 query 到 nlist 个"桶中心"的距离，取最近的 nprobe 个桶
    #     阶段2：只在选中的桶内，做暴力精搜（Flat）
    #   - 精度：Recall@10 ≈ 93% ~ 97%（取决于nprobe）
    #   - 优点：构建速度快（K-means聚类比HNSW建图快3~5倍）
    #   - 缺点：⚠️ 必须先 train() 才能 add()，否则报错
    #           增量添加效果差（新向量可能不属于旧聚类中心）
    # ─────────────────────────────────────────────────────────
    if index_type in ("IVF", "IVF_FLAT"):
        # 根据数据规模自动调优 nlist（用户配置的值可能不合适）
        #   原则：平均每个桶 39~312 条向量（sqrt(N)~4*sqrt(N)个桶）
        nlist = settings.FAISS_IVF_NLIST
        if num_vectors < 50000:
            nlist = min(nlist, 256)       # 5万条以下：最多256个桶
        elif num_vectors < 200000:
            nlist = min(nlist, 1024)      # 20万条以下：最多1024个桶
        # 100万条以上：用配置的默认值（4096左右比较合适）

        # quantizer（粗量化器）：存储桶中心，用于计算"query属于哪个桶"
        # 用 IndexFlatIP 作为粗量化器（内积距离）
        quantizer = faiss.IndexFlatIP(dimension)

        # 创建 IVFFlat 索引（桶内不压缩，还是存储原始向量）
        index = faiss.IndexIVFFlat(
            quantizer,                      # 粗量化器（桶中心）
            dimension,                      # 向量维度
            nlist,                          # 聚类中心数 = 桶的总数
            faiss.METRIC_INNER_PRODUCT      # 度量方式：内积
        )

        # nprobe：查询时探查多少个桶
        #   nprobe=1   → 只查最近的1个桶，最快，漏召回风险高
        #   nprobe=16  → 默认，查最近16个桶，平衡
        #   nprobe=nlist → 查所有桶 = 退化成Flat暴力搜索
        index.nprobe = settings.FAISS_IVF_NPROBE

        # ⚠️ IVF 索引默认 is_trained=False，必须先 index.train(matrix) 才能 add
        return index

    # ─────────────────────────────────────────────────────────
    # 分支 4：IVF_PQ —— IVF + 乘积量化（Product Quantization）
    #   在 IVF 的基础上，对向量本身做有损压缩，大幅节省内存。
    #
    #   压缩原理（1536维，PQ64 示例）：
    #     原始向量 [1536 float32] = 6144 字节 = 6 KB/条
    #       ↓ 切分成 64 个子空间，每个子空间 24 维
    #       ↓ 每个子空间用 K-means 聚类出 256 个"代表中心"
    #       ↓ 每个子空间不用存原始24个float，只存1个字节(0~255)指向中心ID
    #     压缩后 [64 uint8] = 64 字节/条
    #     压缩率 = 64/6144 ≈ 1.04% （节省 98.96% 的存储空间！）
    #
    #   代价：精度损失（Recall@10 再降 5~15%），因为是有损压缩
    #   适用场景：内存实在装不下原始向量，数据量 > 500万条
    # ─────────────────────────────────────────────────────────
    if index_type in ("IVF_PQ", "IVFPQ"):
        nlist = settings.FAISS_IVF_NLIST
        pq_bytes = settings.FAISS_PQ_BYTES

        # 安全校验：PQ 字节数不能超过维度（极端情况的兜底）
        # 每个子空间至少 1 维，所以最多 dim 字节（压缩率最低）
        if pq_bytes > dimension:
            pq_bytes = dimension // 16  # 兜底：每16维压缩成1字节

        quantizer = faiss.IndexFlatIP(dimension)

        # IndexIVFPQ 参数：
        #   - 第4个参数：pq_bytes = 乘积量化的子空间数（每个子空间存1字节）
        #   - 第5个参数：8 = 每个子空间用 8bit 编码（=256个聚类中心，标准值）
        index = faiss.IndexIVFPQ(
            quantizer,
            dimension,
            nlist,
            pq_bytes,
            8,                          # 8bit = 256 中心，一般不需要改
            faiss.METRIC_INNER_PRODUCT
        )
        index.nprobe = settings.FAISS_IVF_NPROBE

        # ⚠️ IVF_PQ 同样需要 train()，且训练时间更长
        #    训练时要同时学"桶中心"和"每个子空间的256个压缩中心"
        return index

    # ─────────────────────────────────────────────────────────
    # 兜底：未知类型字符串 → 安全降级为 Flat（精确搜索不会错）
    # ─────────────────────────────────────────────────────────
    return faiss.IndexFlatIP(dimension)


def _remove_user_index_files(user_id: int) -> None:
    """
    删除指定用户的索引文件和元数据文件

    参数：
        user_id: 用户ID
    """
    for path in (_index_file_path(user_id), _metadata_file_path(user_id)):
        if path.exists():
            path.unlink()


def _load_metadata(user_id: int) -> list[dict[str, int]] | None:
    """
    加载指定用户的索引元数据（兼容新旧两种格式）

    元数据用于将 FAISS 索引的行号（0,1,2...）映射回数据库中的 KnowledgeChunks.id。
    支持两种 JSON 格式：

    【旧格式 v1（纯列表）】—— 升级前已经存在的索引文件
        [
            {"chunk_id": 1001, "document_id": 88},
            {"chunk_id": 1002, "document_id": 88},
            ...
        ]

    【新格式 v2（带索引信息的dict）】—— 升级后新建的索引文件
        {
            "index_type": "HNSW",              # 构建时用的索引类型
            "dimension": 1536,                 # 向量维度
            "num_vectors": 50000,              # 向量总数
            "created_at": "2026-08-12T10:30:00",  # 构建时间（排查问题用）
            "chunks": [                        # ← 原来的映射列表放在这里
                {"chunk_id": 1001, "document_id": 88},
                ...
            ]
        }

    参数：
        user_id: 用户ID

    返回：
        list[dict[str, int]] | None: chunk 映射列表，加载失败返回 None

    ═══════════════════════════════════════════════════════════════
    示例：
    >>> # 假设用户42的索引是升级前建的旧格式
    >>> meta = _load_metadata(42)
    >>> type(meta), len(meta)
    (<class 'list'>, 150)
    >>> meta[0]
    {"chunk_id": 1001, "document_id": 88}

    >>> # 升级后新建的索引，仍然返回同样的 chunks 列表
    >>> # （索引信息对上层透明，兼容已有调用方）
    ═══════════════════════════════════════════════════════════════
    """
    metadata_path = _metadata_file_path(user_id)
    if not metadata_path.exists():
        return None

    try:
        payload = json.loads(metadata_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None

    # 分支 A：旧格式 v1 —— 根结点就是列表
    if isinstance(payload, list):
        return payload

    # 分支 B：新格式 v2 —— 根结点是 dict，chunks 字段才是列表
    if isinstance(payload, dict) and "chunks" in payload:
        chunks = payload.get("chunks")
        if isinstance(chunks, list):
            return chunks

    # 其他情况：格式异常（如被人手动篡改了 JSON）
    return None


def _load_metadata_info(user_id: int) -> dict | None:
    """
    加载索引元数据的「附加信息」（仅 v2 新格式有）。

    用于调试/诊断场景，比如查一下这个索引是哪天建的、当时用了什么类型。
    普通搜索流程不需要调用这个函数。

    参数：
        user_id: 用户ID

    返回：
        dict | None: 索引信息字典，包含 index_type/dimension/num_vectors/created_at
                     旧格式索引或加载失败返回 None

    示例：
    >>> info = _load_metadata_info(user_id=42)
    >>> if info:
    ...     print(f"索引类型: {info['index_type']}")
    ...     print(f"构建时间: {info['created_at']}")
    ...     print(f"向量数量: {info['num_vectors']}")
    """
    metadata_path = _metadata_file_path(user_id)
    if not metadata_path.exists():
        return None

    try:
        payload = json.loads(metadata_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None

    # 只有新格式 v2（dict 带 info 字段）才有这些信息
    if isinstance(payload, dict) and isinstance(payload.get("chunks"), list):
        return {
            "index_type": payload.get("index_type", "Flat"),
            "dimension": payload.get("dimension"),
            "num_vectors": payload.get("num_vectors"),
            "created_at": payload.get("created_at"),
        }
    return None


def _load_index(user_id: int):
    """
    加载指定用户的 FAISS 索引

    参数：
        user_id: 用户ID

    返回：
        faiss.Index | None: FAISS 索引对象，加载失败返回 None
    """
    index_path = _index_file_path(user_id)
    if not index_path.exists():
        return None

    try:
        return faiss.read_index(str(index_path))
    except RuntimeError:
        return None


def rebuild_user_faiss_index(db: Session, *, user_id: int) -> int:
    """
    重建指定用户的 FAISS 向量索引。

    这一版和旧版最大的区别是：
    - 只给 leaf chunk 建索引
    - parent chunk 不进向量索引
    这更符合 parent-child retrieval 的主流设计。

    完整流程：
    ┌──────────────────────────────────────────────────────────────┐
    │ 1. 检查 FAISS 是否可用，不可用则直接返回 0                    │
    └──────────────────────┬───────────────────────────────────────┘
                           │
                           ▼
    ┌──────────────────────────────────────────────────────────────┐
    │ 2. 从数据库查询该用户所有 leaf chunk 的 embedding             │
    │    SELECT chunk_id, document_id, embedding_json              │
    │    FROM knowledge_chunks                                    │
    │    WHERE user_id = {user_id}                                │
    │      AND chunk_role = 'leaf'                                │
    │    ORDER BY document_id ASC, chunk_index ASC                │
    └──────────────────────┬───────────────────────────────────────┘
                           │
                           ▼
    ┌──────────────────────────────────────────────────────────────┐
    │ 3. 逐行解析 embedding，校验维度一致性                          │
    │    - 解析失败（损坏的 JSON）→ 跳过                             │
    │    - 维度不一致（不同模型生成的）→ 跳过                         │
    │    - 有效的向量 → 加入 vectors 列表，同时记录元数据             │
    └──────────────────────┬───────────────────────────────────────┘
                           │
                           ▼
    ┌──────────────────────────────────────────────────────────────┐
    │ 4. 如果没有有效向量 → 删除旧索引文件，返回 0                    │
    └──────────────────────┬───────────────────────────────────────┘
                           │
                           ▼
    ┌──────────────────────────────────────────────────────────────┐
    │ 5. L2 归一化向量矩阵，构建 FAISS 索引                          │
    │    - 使用 IndexFlatIP（内积索引，等价于余弦相似度）             │
    │    - 归一化后内积 = 余弦相似度，速度快且精度高                  │
    └──────────────────────┬───────────────────────────────────────┘
                           │
                           ▼
    ┌──────────────────────────────────────────────────────────────┐
    │ 6. 原子写入：先写临时文件，再替换原文件                         │
    │    - 写 mode.faiss.tmp 和 mode.json.tmp                       │
    │    - 成功后 .replace() 替换原文件                              │
    │    - 避免写入过程中程序崩溃导致文件损坏                         │
    └──────────────────────┬───────────────────────────────────────┘
                           │
                           ▼
    ┌──────────────────────────────────────────────────────────────┐
    │ 7. 返回已索引的 chunk 数量                                     │
    └──────────────────────────────────────────────────────────────┘

    Args:
        db: 数据库会话
        user_id: 用户 ID

    Returns:
        int: 成功索引的 chunk 数量。0 表示没有 chunk 被索引。

    ────────────────────────────────────────────────────────────────
    示例场景：
    ────────────────────────────────────────────────────────────────

    【场景1：用户刚上传了 3 个文档，需要重建索引】
    >>> rebuild_user_faiss_index(db, user_id=42)
    150
    # 用户42有150个 leaf chunk，全部写入 FAISS 索引

    输出文件：
        data/faiss/user_42.faiss   ← FAISS 二进制索引文件
        data/faiss/user_42.json    ← 元数据映射文件

    元数据文件内容示例：
        [
            {"chunk_id": 1001, "document_id": 88},
            {"chunk_id": 1002, "document_id": 88},
            {"chunk_id": 1003, "document_id": 89},
            ...
        ]

    【场景2：用户没有 leaf chunk（所有文档都解析失败）】
    >>> rebuild_user_faiss_index(db, user_id=99)
    0
    # 删除旧索引文件（如果有），返回 0

    【场景3：FAISS 未安装】
    >>> rebuild_user_faiss_index(db, user_id=42)
    0
    # 直接返回 0，不做任何操作

    ────────────────────────────────────────────────────────────────
    设计决策说明：
    ────────────────────────────────────────────────────────────────
    1. 为什么只索引 leaf chunk？
       parent chunk 是"大上下文块"，在 small-to-big 检索策略中，
       先用 leaf chunk 做向量召回，命中后再展开 parent chunk 获取完整上下文。
       把 parent 也放进索引会导致检索结果冗余，且浪费存储空间。

    2. 为什么用 IndexFlatIP（内积）而不是 IndexFlatL2（欧氏距离）？
       对 L2 归一化后的向量，内积 = 余弦相似度。
       余弦相似度比欧氏距离更适合语义搜索（更关注方向而非大小）。

    3. 为什么维度不一致的向量要跳过？
       不同 embedding 模型输出的向量维度不同（如 768、1024、1536）。
       混入不同维度的向量会导致 FAISS 索引构建失败。
       跳过是安全的兜底策略，因为这些向量通常来自旧模型或配置错误。

    4. 为什么用原子写入（tmp → replace）？
       如果直接写入原文件，写入过程中程序崩溃会导致文件损坏。
       先写临时文件，再 replace 是原子操作（POSIX rename），不会产生半成品文件。
    """
    # ========== 1. 检查 FAISS 是否可用 ==========
    if not faiss_available():
        return 0

    # ========== 2. 从数据库查询所有 leaf chunk 的 embedding ==========
    # 只查 leaf chunk（chunk_role == 'leaf'），parent chunk 不参与向量检索
    # 按 document_id + chunk_index 排序，保证索引顺序稳定
    rows = (
        db.query(
            KnowledgeChunks.id.label("chunk_id"),
            KnowledgeChunks.document_id,       # 用于后续追溯 chunk 所属的文档
            KnowledgeChunks.embedding_json,     # 向量数据，通常是 JSON 字符串或 list
        )
        .filter(
            KnowledgeChunks.user_id == user_id,
            KnowledgeChunks.chunk_role == KNOWLEDGE_CHUNK_ROLE_LEAF,  # 只取 leaf
        )
        .order_by(KnowledgeChunks.document_id.asc(), KnowledgeChunks.chunk_index.asc())
        .all()
    )

    # ========== 3. 初始化收集容器 ==========
    vectors: list[list[float]] = []       # 向量列表，每一行对应一个 chunk 的 embedding
    metadata: list[dict[str, int]] = []   # 元数据列表，记录每个向量对应的 chunk_id 和 document_id
    dimension: int | None = None          # 第一个有效向量的维度，用于校验后续向量一致性

    # ========== 4. 逐行解析 embedding ==========
    for row in rows:
        # 解析 embedding：支持 JSON 字符串、list、None 三种格式
        embedding = _parse_embedding_json(row.embedding_json)
        if not embedding:
            continue  # 解析失败或为空，跳过这条记录

        # 用第一个有效向量的维度作为基准
        if dimension is None:
            dimension = len(embedding)
        # 如果后续向量维度不一致（如不同模型生成的），跳过
        if len(embedding) != dimension:
            continue

        vectors.append(embedding)
        # 保存元数据：chunk_id 用于检索后回查数据库，document_id 用于追溯文档
        metadata.append(
            {
                "chunk_id": int(row.chunk_id),
                "document_id": int(row.document_id),
            }
        )

    # ========== 5. 无有效向量时，清理旧索引 ==========
    # 如果用户之前有索引但现在所有 chunk 都被删了，需要把旧文件也删掉
    if not vectors or dimension is None:
        _remove_user_index_files(user_id)
        return 0

    # ========== 6. 构建 FAISS 索引（ANN 近似最近邻索引升级核心步骤）==========
    # 6.1 将向量列表转为 NumPy 矩阵，并做 L2 归一化
    #     归一化后，内积（Inner Product）等价于余弦相似度
    matrix = _normalize_matrix(np.asarray(vectors, dtype="float32"))
    num_vectors = len(vectors)  # 用于 _create_faiss_index 的智能降级判断

    # 6.2 根据配置 + 数据规模，智能选择索引类型（Flat/HNSW/IVF/IVF_PQ）
    #     替代原来的硬编码 faiss.IndexFlatIP(dimension)
    #
    # ╔══════════════════════════════════════════════════════════════════╗
    # ║  新旧索引构建流程对比（关键差异！）                               ║
    # ╠══════════════════════════════════════════════════════════════════╣
    # ║                                                                  ║
    # ║  【旧版 Flat 索引】（只有这一种）                                 ║
    # ║      index = IndexFlatIP(dim)                                    ║
    # ║      index.add(matrix)          ← 直接加，不需要训练             ║
    # ║                                                                  ║
    # ║  【新版 ANN 索引】（分两种情况）                                 ║
    # ║                                                                  ║
    # ║   情况A：Flat / HNSW（不需要训练）                               ║
    # ║      index = _create_faiss_index(dim, N)                         ║
    # ║      └─ index.is_trained → True ✅                               ║
    # ║      index.add(matrix)      ← 直接加数据                         ║
    # ║                                                                  ║
    # ║   情况B：IVF / IVF_PQ（⚠️ 必须先训练！不能跳过！）              ║
    # ║      index = _create_faiss_index(dim, N)                         ║
    # ║      └─ index.is_trained → False ❌                              ║
    # ║      index.train(matrix)    ← K-means 找聚类中心（几秒~几分钟） ║
    # ║      └─ index.is_trained → True ✅                               ║
    # ║      index.add(matrix)      ← 训练好后才能加数据                 ║
    # ║                                                                  ║
    # ║   为什么 IVF 需要 train？                                        ║
    # ║     → 先有"1024个桶的中心点"，才知道新向量要丢进哪个桶           ║
    # ║     → 就像先有图书分类法（经/史/子/集...），才知道新书放哪架   ║
    # ╚══════════════════════════════════════════════════════════════════╝
    index = _create_faiss_index(dimension, num_vectors)

    # 6.3 【关键】需要训练的索引（IVF/IVF_PQ）先 train，再加向量
    #     Flat 和 HNSW 的 is_trained 默认就是 True，这步自动跳过
    if hasattr(index, "is_trained") and not index.is_trained:
        # 喂全部向量做训练（K-means 聚类 / PQ 子空间聚类）
        # 经验：训练数据不需要全量，采样10万条足够
        # 但为了简单稳妥，我们直接用全量向量（实际差距不大）
        index.train(matrix)

    # 6.4 向量加入索引
    #     - Flat：直接把原始向量复制进索引表
    #     - HNSW：逐个插入节点，并构建邻居连接关系（较慢，是构建瓶颈）
    #     - IVF：计算每个向量到桶中心的距离，扔进最近的桶
    #     - IVF_PQ：扔进桶之前，先把向量压缩成PQ编码（再省内存）
    index.add(matrix)

    # ========== 7. 原子写入索引文件和元数据文件 ==========
    # 7.1 获取文件路径
    index_path = _index_file_path(user_id)        # 如: data/faiss/user_42.faiss
    metadata_path = _metadata_file_path(user_id)  # 如: data/faiss/user_42.json
    index_tmp = _tmp_path(index_path)             # 如: data/faiss/user_42.faiss.tmp
    metadata_tmp = _tmp_path(metadata_path)       # 如: data/faiss/user_42.json.tmp

    # 7.2 写入临时文件
    faiss.write_index(index, str(index_tmp))      # FAISS 索引存为二进制 .faiss 文件

    # 7.2.1 元数据改为 v2 新格式（带索引信息）
    #   这样以后排查问题可以直接看 JSON，不用问"当时用的什么索引类型"
    metadata_v2 = {
        # 构建时实际生效的索引类型（可能被智能降级改了，比如<1万条自动Flat）
        "index_type": settings.FAISS_INDEX_TYPE if num_vectors >= 10000 else "Flat(auto)",
        "dimension": dimension,             # 向量维度
        "num_vectors": num_vectors,         # 实际索引的 chunk 数量
        "created_at": datetime.now().isoformat(timespec="seconds"),  # 构建时间
        "chunks": metadata,                 # ← 原来的映射列表（兼容字段）
    }
    metadata_tmp.write_text(
        json.dumps(metadata_v2, ensure_ascii=False),  # ensure_ascii=False 保留中文
        encoding="utf-8",
    )

    # 7.3 原子替换：用临时文件覆盖正式文件
    #     .replace() 在 POSIX 上是原子操作（rename），不会出现半成品文件
    #     在 Windows 上如果目标文件存在会先删除再重命名，也是安全的
    #
    #     ⚠️ 这一步保证：即使构建中途崩溃（比如HNSW构建了一半断电），
    #        旧的索引文件仍然完好无损，不会出现"索引文件一半损坏"的灾难。
    index_tmp.replace(index_path)
    metadata_tmp.replace(metadata_path)

    # ========== 8. 返回成功索引的 chunk 数量 ==========
    return len(metadata)


def search_user_faiss_index(
    *,
    user_id: int,
    query_embedding: list[float],
    top_k: int,
    document_ids: list[int] | None = None,
) -> list[FaissSearchHit] | None:
    """
    在指定用户的 FAISS 索引中搜索相似向量

    支持按文档ID过滤，采用渐进式搜索策略确保返回足够的有效结果。

    参数：
        user_id: 用户ID（关键字参数）
        query_embedding: 查询向量（嵌入向量）
        top_k: 返回的最大结果数量
        document_ids: 可选的文档ID过滤列表，仅返回指定文档的知识块

    返回：
        list[FaissSearchHit] | None: 搜索结果列表，FAISS不可用或索引不存在返回 None
    """
    # 检查 FAISS 是否可用
    if not faiss_available():
        return None

    # 加载元数据和索引
    metadata = _load_metadata(user_id)
    index = _load_index(user_id)
    if metadata is None or index is None:
        return None

    total = len(metadata)
    # 检查索引一致性和查询向量有效性
    if total == 0 or index.ntotal != total or not query_embedding:
        return []

    # 将查询向量转换为归一化的 NumPy 矩阵
    query = _normalize_matrix(np.asarray([query_embedding], dtype="float32"))
    # 构建允许的文档ID集合（用于过滤）
    allowed_document_ids = set(document_ids or [])

    # 计算初始搜索大小
    search_size = min(total, max(top_k, 1))
    # 如果有文档过滤，扩大搜索范围以确保找到足够的有效结果
    if allowed_document_ids:
        search_size = min(total, max(search_size * 4, top_k))

    collected: list[FaissSearchHit] = []  # 收集的结果
    seen_rows: set[int] = set()  # 已处理的行ID（避免重复）

    # 渐进式搜索：如果一次搜索不够，扩大搜索范围继续搜索
    while search_size > 0:
        # 在 FAISS 索引中搜索，获取相似度分数和行ID
        scores, row_ids = index.search(query, search_size)

        # 遍历搜索结果
        for score, row_id in zip(scores[0].tolist(), row_ids[0].tolist()):
            # 跳过无效或已处理的行
            if row_id < 0 or row_id >= total or row_id in seen_rows:
                continue

            seen_rows.add(row_id)
            item = metadata[row_id]
            document_id = int(item["document_id"])

            # 如果有文档过滤，跳过不在允许列表中的文档
            if allowed_document_ids and document_id not in allowed_document_ids:
                continue

            # 添加到结果列表
            collected.append(
                FaissSearchHit(
                    row_id=row_id,
                    chunk_id=int(item["chunk_id"]),
                    document_id=document_id,
                    score=float(score),
                )
            )

            # 如果已收集足够的结果，立即返回
            if len(collected) >= top_k:
                return collected

        # 检查是否已搜索完所有向量
        if search_size >= total:
            break

        # 扩大搜索范围（最多翻倍）
        next_search_size = min(total, search_size * 2)
        if next_search_size == search_size:
            break
        search_size = next_search_size

    return collected