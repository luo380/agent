import json
import math
import re
from dataclasses import dataclass

from sqlalchemy import Sequence
from sqlalchemy.orm import Session

from core.db.models import KnowledgeChunks, KnowledgeDocuments
from core.service.vector_index import rebuild_user_faiss_index, search_user_faiss_index

# 简单分词：中英文数字都保留
LATIN_TOKEN_RE = re.compile(r"[A-Za-z0-9]+")
CJK_TOKEN_RE = re.compile(r"[\u4e00-\u9fff]+")

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


def phrase_overlap_score(query_text: str, chunk_text: str) -> float:
    query_text = re.sub(r"\s+", "", (query_text or "").lower())
    chunk_text = re.sub(r"\s+", "", (chunk_text or "").lower())
    if not query_text or not chunk_text:
        return 0.0

    if query_text in chunk_text:
        return 1.0

    query_terms: set[str] = set(LATIN_TOKEN_RE.findall(query_text))
    for token in CJK_TOKEN_RE.findall(query_text):
        query_terms.update(_generate_cjk_ngrams(token, min_size=2, max_size=6))

    meaningful_terms = {term for term in query_terms if len(term) >= 2}
    if not meaningful_terms:
        return 0.0

    matched_terms = {term for term in meaningful_terms if term in chunk_text}
    return len(matched_terms) / len(meaningful_terms)



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

    return round(vector_score + primary_bonus + focused_bonus, 6)

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

def load_chunks_by_ids(
    db: Session,
    *,
    user_id: int,
    chunk_ids: Sequence[int],
) -> list[RetrievedChunk]:
    if not chunk_ids:
        return []

    rows = (
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
        .filter(
            KnowledgeChunks.user_id == user_id,
            KnowledgeDocuments.user_id == user_id,
            KnowledgeChunks.id.in_(list(chunk_ids)),
        )
        .all()
    )

    chunk_map: dict[int, RetrievedChunk] = {}
    for row in rows:
        chunk_map[int(row.chunk_id)] = RetrievedChunk(
            document_id=row.document_id,
            document_name=row.document_name,
            chunk_id=row.chunk_id,
            chunk_index=row.chunk_index,
            content=row.content,
            source_page=row.source_page,
            source_section=row.source_section or "",
            embedding_json=row.embedding_json or "",
        )

    return [chunk_map[int(chunk_id)] for chunk_id in chunk_ids if int(chunk_id) in chunk_map]


def _score_retrieved_chunks(
    query_text: str | None,
    chunks: Sequence[RetrievedChunk],
    *,
    top_k: int,
) -> list[RetrievedChunk]:
    scored: list[tuple[float, RetrievedChunk]] = []

    for chunk in chunks:
        if chunk.vector_score <= 0:
            continue

        recall_score = coarse_recall_score(query_text, chunk.content, chunk.vector_score)
        scored.append(
            (
                recall_score,
                RetrievedChunk(
                    document_id=chunk.document_id,
                    document_name=chunk.document_name,
                    chunk_id=chunk.chunk_id,
                    chunk_index=chunk.chunk_index,
                    content=chunk.content,
                    source_page=chunk.source_page,
                    source_section=chunk.source_section,
                    embedding_json=chunk.embedding_json,
                    vector_score=chunk.vector_score,
                ),
            )
        )

    scored.sort(
        key=lambda item: (item[0], item[1].vector_score, item[1].chunk_index),
        reverse=True,
    )
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
    # 鏌ヨ鍚戦噺锛堝皢鐢ㄦ埛闂杞垚鐨勬暟瀛楀垪琛級
    query_embedding: list[float],
    query_text: str | None = None,
    # 鍙€夛細闄愬畾鎼滅储鍝簺鏂囨。
    document_ids: Sequence[int] | None = None,
    # 鏈€澶氳繑鍥炲嚑鏉＄粨鏋?
    top_k: int = 10,
    # 鐩镐技搴﹂槇鍊硷紙浣庝簬姝ゅ€肩殑缁撴灉琚繃婊わ級
    threshold: float = 0.5,
        # 鏄惁瀵圭粨鏋滈噸鏂版帓搴忥紙鎻愰珮绮惧害锛?
    rerank: bool = True,
) -> list[RetrievedChunk]:
    faiss_results = _search_similar_chunks_by_faiss(
        db,
        user_id=user_id,
        query_embedding=query_embedding,
        query_text=query_text,
        document_ids=document_ids,
        top_k=top_k,
    )
    if faiss_results is not None:
        return faiss_results

    return _search_similar_chunks_by_bruteforce(
        db,
        user_id=user_id,
        query_embedding=query_embedding,
        query_text=query_text,
        document_ids=document_ids,
        top_k=top_k,
    )

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
    query_text: str,
    chunks: Sequence[RetrievedChunk],
    top_k: int = 5,
) -> list[RetrievedChunk]:
    # 再精排：向量分 + 关键词重合度
    reranked: list[RetrievedChunk] = []

    query_forms = build_recall_query_forms(query_text)
    primary_form = query_forms[0] if query_forms else query_text
    focused_forms = query_forms[1:] or [primary_form]

    for chunk in chunks:
        keyword_score = max(keyword_overlap_score(form, chunk.content) for form in focused_forms)
        phrase_score = max(phrase_overlap_score(form, chunk.content) for form in focused_forms)
        primary_keyword_score = keyword_overlap_score(primary_form, chunk.content)
        primary_phrase_score = phrase_overlap_score(primary_form, chunk.content)
        # Blend semantic recall with a stronger focus on the question tail.
        # For prefixed queries like "?????????????",
        # the focused tail should outrank generic product mentions.
        final_score = round(
            (chunk.vector_score * 0.42)
            + (primary_keyword_score * 0.04)
            + (primary_phrase_score * 0.04)
            + (keyword_score * 0.22)
            + (phrase_score * 0.28),
            6,
        )

        reranked.append(
        RetrievedChunk(
            document_id=chunk.document_id,
            document_name=chunk.document_name,
            chunk_id=chunk.chunk_id,
            chunk_index=chunk.chunk_index,
            content=chunk.content,
            source_page=chunk.source_page,
            source_section=chunk.source_section,
            embedding_json=chunk.embedding_json,
            vector_score=chunk.vector_score,
            keyword_score=keyword_score,
            final_score=final_score,
             )
            )
    reranked.sort(
        key=lambda item: (item.final_score, item.vector_score, item.chunk_index),
        reverse=True,
    )
    return reranked[:top_k]
