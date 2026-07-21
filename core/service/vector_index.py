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
    重建指定用户的 FAISS 向量索引

    从数据库中读取该用户的所有知识块，提取嵌入向量，构建 FAISS 索引并保存到磁盘。

    参数：
        db: SQLAlchemy 数据库会话
        user_id: 用户ID（关键字参数）

    返回：
        int: 成功索引的知识块数量，FAISS 不可用时返回 0
    """
    # 检查 FAISS 是否可用
    if not faiss_available():
        return 0

    # 从数据库查询用户的所有知识块
    # 按 document_id 和 chunk_index 排序，确保顺序一致
    rows = (
        db.query(
            KnowledgeChunks.id.label("chunk_id"),
            KnowledgeChunks.document_id,
            KnowledgeChunks.embedding_json,
        )
        .filter(KnowledgeChunks.user_id == user_id)
        .order_by(KnowledgeChunks.document_id.asc(), KnowledgeChunks.chunk_index.asc())
        .all()
    )

    # 存储向量和元数据
    vectors: list[list[float]] = []
    metadata: list[dict[str, int]] = []
    dimension: int | None = None  # 向量维度

    # 遍历查询结果，提取有效向量
    for row in rows:
        embedding = _parse_embedding_json(row.embedding_json)
        if not embedding:
            continue  # 跳过无效向量

        # 确定向量维度（首次遇到有效向量时）
        if dimension is None:
            dimension = len(embedding)
        # 跳过维度不一致的向量
        if len(embedding) != dimension:
            continue

        vectors.append(embedding)
        metadata.append(
            {
                "chunk_id": int(row.chunk_id),
                "document_id": int(row.document_id),
            }
        )

    # 如果没有有效向量，删除旧索引并返回
    if not vectors or dimension is None:
        _remove_user_index_files(user_id)
        return 0

    # 将向量列表转换为 NumPy 矩阵并归一化
    #向量入库前预处理：确保所有索引向量长度一致
    #查询向量预处理：保证查询时与索引向量具有可比性
    #内积检索优化：加速相似度计算
    matrix = _normalize_matrix(np.asarray(vectors, dtype="float32"))

    # 创建 FAISS 索引：使用 IndexFlatIP（内积索引）
    # 内积在归一化后等价于余弦相似度
    index = faiss.IndexFlatIP(dimension)
    index.add(matrix)  # 将向量添加到索引

    # 获取文件路径
    index_path = _index_file_path(user_id)
    metadata_path = _metadata_file_path(user_id)
    index_tmp = _tmp_path(index_path)
    metadata_tmp = _tmp_path(metadata_path)

    # 先写入临时文件
    faiss.write_index(index, str(index_tmp))
    metadata_tmp.write_text(
        json.dumps(metadata, ensure_ascii=False),
        encoding="utf-8",
    )

    # 原子替换原文件（确保写入失败时不会损坏原文件）
    index_tmp.replace(index_path)
    metadata_tmp.replace(metadata_path)

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