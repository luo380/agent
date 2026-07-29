"""
向量索引服务模块

该模块提供基于 FAISS（Facebook AI Similarity Search）的向量索引功能，
用于实现高效的文本语义检索。主要功能包括：
1. 从数据库加载知识块的嵌入向量并构建 FAISS 索引
2. 对用户查询进行语义搜索，返回最相关的知识块

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
    加载指定用户的索引元数据

    元数据是一个列表，每个元素包含 chunk_id 和 document_id，
    用于将 FAISS 索引的行号映射回数据库中的知识块记录。

    参数：
        user_id: 用户ID

    返回：
        list[dict[str, int]] | None: 元数据列表，加载失败返回 None
    """
    metadata_path = _metadata_file_path(user_id)
    if not metadata_path.exists():
        return None

    try:
        payload = json.loads(metadata_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None

    if not isinstance(payload, list):
        return None

    return payload


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

    # ========== 6. 构建 FAISS 索引 ==========
    # 6.1 将向量列表转为 NumPy 矩阵，并做 L2 归一化
    #     归一化后，内积（Inner Product）等价于余弦相似度
    matrix = _normalize_matrix(np.asarray(vectors, dtype="float32"))

    # 6.2 创建 IndexFlatIP 索引
    #     IndexFlatIP: 暴力内积索引，对所有向量做精确最近邻搜索
    #     "Flat" 表示不压缩，精度最高但内存占用大
    #     适合中小规模数据（< 10万条），如果需要更大规模可改用 IVF 或 HNSW
    index = faiss.IndexFlatIP(dimension)
    index.add(matrix)  # 将归一化后的向量矩阵加入索引

    # ========== 7. 原子写入索引文件和元数据文件 ==========
    # 7.1 获取文件路径
    index_path = _index_file_path(user_id)        # 如: data/faiss/user_42.faiss
    metadata_path = _metadata_file_path(user_id)  # 如: data/faiss/user_42.json
    index_tmp = _tmp_path(index_path)             # 如: data/faiss/user_42.faiss.tmp
    metadata_tmp = _tmp_path(metadata_path)       # 如: data/faiss/user_42.json.tmp

    # 7.2 写入临时文件
    faiss.write_index(index, str(index_tmp))      # FAISS 索引存为二进制 .faiss 文件
    metadata_tmp.write_text(
        json.dumps(metadata, ensure_ascii=False),  # 元数据存为 JSON，ensure_ascii=False 保留中文
        encoding="utf-8",
    )

    # 7.3 原子替换：用临时文件覆盖正式文件
    #     .replace() 在 POSIX 上是原子操作（rename），不会出现半成品文件
    #     在 Windows 上如果目标文件存在会先删除再重命名，也是安全的
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