import json
import math
import re
from dataclasses import dataclass

from sqlalchemy import Sequence
from sqlalchemy.orm import Session

from core.db.models import KnowledgeChunks, KnowledgeDocuments

# 简单分词：中英文数字都保留
TOKEN_RE = re.compile(r"[A-Za-z0-9\u4e00-\u9fff]+")

@dataclass
class RetrievedChunk:
    """检索返回的统一数据结构
    
    用于封装混合检索（向量检索+关键词检索）返回的文本块信息，
    包含文档元数据、文本内容以及多维度的评分信息。
    """
    # 文档唯一标识符，对应数据库中的文档ID
    document_id: int
    # 文档名称，用于展示文档来源
    document_name: str
    # 文本块（chunk）的唯一标识符
    chunk_id: int
    # 文本块在原文档中的序号索引（从0或1开始，取决于切分策略）
    chunk_index: int
    # 文本块的实际内容，作为检索返回的核心数据
    content: str
    # 来源页码，对于PDF等分页文档有意义，非分页文档为None
    source_page: int | None
    # 来源章节名称，标识文本块在文档中的位置
    source_section: str
    # 向量嵌入的JSON字符串表示，可选存储，默认为空
    embedding_json: str = ""
    # 向量相似度评分（语义检索得分），范围通常为[0,1]，值越高越相关
    vector_score: float = 0.0
    # 关键词匹配评分（传统检索得分），基于词频或BM25等算法
    keyword_score: float = 0.0
    # 最终综合评分，由vector_score和keyword_score加权融合得到，用于结果排序
    final_score: float = 0.0

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
def tokenize(text: str) -> set[str]:
    # 用于简单 rerank
    return {token.lower() for token in TOKEN_RE.findall((text or "").lower())}



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
    db: Session,
    *,
    user_id: int,
    document_ids: Sequence[int] | None = None,
) -> list[RetrievedChunk]:
    # 只加载当前用户自己的 chunk，避免越权
    query = (
        db.query(
            KnowledgeChunks.id.label("chunk_id"),
            KnowledgeChunks.document_id,
            KnowledgeChunks.chunk_index,
            KnowledgeChunks.content,
            KnowledgeChunks.source_page,
            KnowledgeChunks.source_section,
            KnowledgeChunks.embedding_json,
            KnowledgeDocuments.name.label("document_name"),
        )
        .join(KnowledgeDocuments, KnowledgeDocuments.id == KnowledgeChunks.document_id)
        .filter(KnowledgeChunks.user_id == user_id, KnowledgeDocuments.user_id == user_id)
    )

    if document_ids:
        # SELECT ... FROM knowledge_chunks chunks
        # JOIN knowledge_documents docs ON docs.id = chunks.document_id
        # WHERE chunks.user_id = :user_id
        #   AND docs.user_id   = :user_id
        #   AND chunks.document_id IN (5, 8, 12)   -- 新增：只返回这3个文档的文本块
        query = query.filter(KnowledgeChunks.document_id.in_(list(document_ids)))

    rows = (
        query.order_by(KnowledgeChunks.document_id.asc(), KnowledgeChunks.chunk_index.asc())
        .all()
    )

    chunks: list[RetrievedChunk] = []
    for row in rows:
        chunks.append(
            RetrievedChunk(
                document_id=row.document_id,
                document_name=row.document_name,
                chunk_id=row.chunk_id,
                chunk_index=row.chunk_index,
                content=row.content,
                source_page=row.source_page,
                source_section=row.source_section or "",
                embedding_json=row.embedding_json or "",
            )
        )

    return chunks
