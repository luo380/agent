"""
================================================================================
langchain_adapters.py  —  整合后的修改版（阶段5清理）
================================================================================

【当前架构】LangChain 适配层
  职责：把项目现有能力（parse_document / chunk / embed / search / rerank）
        适配成 LangChain 标准接口。
        不做业务判断，不直接调用 LLM。

  四个核心适配器：
    1. ProjectDocumentLoader  →  Document Loader
    2. ProjectTextSplitter    →  Text Splitter
    3. ProjectEmbeddings      →  Embeddings
    4. ProjectKnowledgeRetriever → Retriever

【修改说明】
  本文件改动较少，主要是阶段5的：
    - 头部注释统一改成 LangChain-Only 架构说明
    - 删除重复的标题注释和冗余描述
    - retrieved_chunk_to_langchain_document 字段映射说明更清晰
================================================================================
"""

import asyncio
from collections.abc import Iterator, Mapping, Sequence
from pathlib import Path
from typing import Any

from langchain_core.document_loaders import BaseLoader
from langchain_core.documents import Document
from langchain_core.embeddings import Embeddings
from langchain_core.retrievers import BaseRetriever
from langchain_text_splitters import TextSplitter
from pydantic import ConfigDict, Field, PrivateAttr

from core.db.models import KNOWLEDGE_CHUNK_ROLE_LEAF
from core.service.document_parser import parse_document
from core.service.embedding import embed_text, embed_texts
from core.service.hierarchical_chunking import build_hierarchical_chunks
from core.service.retrieval import (
    RetrievedChunk,
    rerank_chunks,
    search_similar_chunks,
)


# ============================================================
# 工具函数
# ============================================================
def _chunk_value(chunk: RetrievedChunk | dict, key: str, default: Any = None) -> Any:
    """
    统一读取 chunk 字段。
    业务里是 RetrievedChunk 对象，测试代码里有时是 dict。
    """
    if isinstance(chunk, dict):
        return chunk.get(key, default)
    return getattr(chunk, key, default)


def retrieved_chunk_to_langchain_document(chunk: RetrievedChunk | dict) -> Document:
    """
    把项目的 RetrievedChunk 转成 LangChain Document。

    字段映射：
      RetrievedChunk.content       → Document.page_content
      RetrievedChunk.document_id   → Document.metadata["document_id"]
      RetrievedChunk.document_name → Document.metadata["document_name"]
      RetrievedChunk.chunk_id      → Document.metadata["chunk_id"]
      RetrievedChunk.chunk_index   → Document.metadata["chunk_index"]
      RetrievedChunk.source_page   → Document.metadata["source_page"]
      RetrievedChunk.source_section→ Document.metadata["source_section"]
      RetrievedChunk.final_score   → Document.metadata["score"]
    """
    final_score = _chunk_value(chunk, "final_score")
    vector_score = _chunk_value(chunk, "vector_score")

    return Document(
        page_content=(_chunk_value(chunk, "content", "") or "").strip(),
        metadata={
            "document_id": _chunk_value(chunk, "document_id"),
            "document_name": _chunk_value(chunk, "document_name", "unknown document"),
            "chunk_id": _chunk_value(chunk, "chunk_id"),
            "chunk_index": _chunk_value(chunk, "chunk_index"),
            "source_page": _chunk_value(chunk, "source_page"),
            "source_section": _chunk_value(chunk, "source_section"),
            "vector_score": vector_score,
            "keyword_score": _chunk_value(chunk, "keyword_score"),
            "final_score": final_score,
            "score": final_score if final_score is not None else vector_score,
        },
    )


def retrieved_chunks_to_langchain_documents(
    chunks: Sequence[RetrievedChunk | dict],
) -> list[Document]:
    """批量把检索结果转成 LangChain Document 列表。"""
    return [retrieved_chunk_to_langchain_document(chunk) for chunk in chunks]


def _build_leaf_chunk_items(
    parsed_document: Mapping[str, Any],
    *,
    file_type: str,
    chunk_size: int,
    chunk_overlap: int,
) -> list[dict[str, Any]]:
    chunk_items = build_hierarchical_chunks(
        dict(parsed_document or {}),
        file_type=file_type or "txt",
        chunk_size=chunk_size,
        overlap=chunk_overlap,
    )
    return [
        item for item in chunk_items
        if item.get("chunk_role") == KNOWLEDGE_CHUNK_ROLE_LEAF
    ]


# ============================================================
# 1. ProjectDocumentLoader（LangChain Document Loader）
# ============================================================
class ProjectDocumentLoader(BaseLoader):
    """
    LangChain Document Loader 适配。
    内部复用 parse_document(...)。
    Loader 只负责"加载"，不负责"切块"（切块交给 ProjectTextSplitter）。
    """

    def __init__(
        self,
        file_path: str,
        *,
        file_type: str,
        metadata: Mapping[str, Any] | None = None,
    ) -> None:
        self.file_path = file_path
        self.file_type = file_type
        self.metadata = dict(metadata or {})

    def load_parsed_document(self) -> dict:
        """
        调用项目统一文档解析入口。
        返回结构通常包含 full_text / pages / sections / metadata。
        """
        return parse_document(self.file_path, file_type=self.file_type)

    def lazy_load(self) -> Iterator[Document]:
        """LangChain Loader 标准接口（懒加载）。"""
        parsed_document = self.load_parsed_document()
        file_name = self.metadata.get("document_name") or Path(self.file_path).name

        yield Document(
            page_content=parsed_document.get("full_text", "") or "",
            metadata={
                **self.metadata,
                "document_name": file_name,
                "file_path": self.file_path,
                "file_type": self.file_type,
                "parsed_document": parsed_document,
                "parser_metadata": parsed_document.get("metadata") or {},
            },
        )


# ============================================================
# 2. ProjectTextSplitter（LangChain Text Splitter）
# ============================================================
class ProjectTextSplitter(TextSplitter):
    """
    LangChain Text Splitter 适配。
    优先使用 build_hierarchical_chunks(...) 保留页码、章节等结构化信息，
    兜底时走纯文本切块。
    """

    def __init__(
        self,
        *,
        chunk_size: int = 500,
        chunk_overlap: int = 100,
    ) -> None:
        super().__init__(
            chunk_size=chunk_size,
            chunk_overlap=chunk_overlap,
            add_start_index=False,
        )
        self.project_chunk_size = chunk_size
        self.project_chunk_overlap = chunk_overlap

    def split_text(self, text: str) -> list[str]:
        """纯文本切块入口（LangChain 要求实现）。"""
        chunk_items = _build_leaf_chunk_items(
            {
                "full_text": text or "",
                "pages": [],
                "sections": [],
                "metadata": {},
            },
            file_type="txt",
            chunk_size=self.project_chunk_size,
            chunk_overlap=self.project_chunk_overlap,
        )
        if not chunk_items:
            clean_text = (text or "").strip()
            return [clean_text] if clean_text else []
        return [item["content"] for item in chunk_items]

    def split_documents(self, documents: Sequence[Document]) -> list[Document]:
        """
        把 Loader 产出的 Document 切成 chunk Documents。
        如果 metadata 里带了 parsed_document，优先保留页码/章节。
        """
        split_documents: list[Document] = []

        for document in documents:
            base_metadata = dict(document.metadata or {})
            parsed_document = base_metadata.pop("parsed_document", None)
            file_type = str(base_metadata.get("file_type") or "txt")
            if parsed_document is None:
                parsed_document = {
                    "full_text": document.page_content or "",
                    "pages": [],
                    "sections": [],
                    "metadata": {},
                }

            chunk_items = _build_leaf_chunk_items(
                parsed_document,
                file_type=file_type,
                chunk_size=self.project_chunk_size,
                chunk_overlap=self.project_chunk_overlap,
            )

            for chunk in chunk_items:
                split_documents.append(
                    Document(
                        page_content=chunk["content"],
                        metadata={
                            **base_metadata,
                            "chunk_index": chunk["chunk_index"],
                            "chunk_role": chunk["chunk_role"],
                            "parent_title": chunk["parent_title"],
                            "block_type": chunk["block_type"],
                            "child_index": chunk["child_index"],
                            "table_row_from": chunk["table_row_from"],
                            "table_row_to": chunk["table_row_to"],
                            "retrieval_content": chunk["retrieval_content"],
                            "start_offset": chunk["start_offset"],
                            "end_offset": chunk["end_offset"],
                            "source_page": chunk["source_page"],
                            "source_section": chunk["source_section"],
                            "lc_splitter": "project_hierarchical_chunking",
                        },
                    )
                )
        return split_documents


# ============================================================
# 3. ProjectEmbeddings（LangChain Embeddings）
# ============================================================
class ProjectEmbeddings(Embeddings):
    """
    LangChain Embeddings 适配。
    内部复用 embed_text(...) / embed_texts(...)。
    """

    def __init__(self, *, client: Any = None) -> None:
        self.client = client

    def embed_query(self, text: str) -> list[float]:
        """
        同步单文本 embedding。
        异步链路中请使用 aembed_query(...)。
        """
        return self._run_async(self.aembed_query(text))

    def embed_documents(self, texts: list[str]) -> list[list[float]]:
        return self._run_async(self.aembed_documents(texts))

    async def aembed_query(self, text: str) -> list[float]:
        """异步单文本 embedding（主链路推荐）。"""
        return await embed_text(text, client=self.client)

    async def aembed_documents(self, texts: list[str]) -> list[list[float]]:
        """异步批量 embedding。"""
        return await embed_texts(texts, client=self.client)

    @staticmethod
    def _run_async(coroutine):
        """
        同步接口的兜底执行器。
        注意：如果当前已经在事件循环里，不能再 asyncio.run()，
        所以异步环境下请直接使用 aembed_query / aembed_documents。
        """
        try:
            asyncio.get_running_loop()
        except RuntimeError:
            return asyncio.run(coroutine)
        raise RuntimeError(
            "ProjectEmbeddings synchronous methods were called inside an active "
            "event loop. Use aembed_query() or aembed_documents() in async code."
        )


# ============================================================
# 4. ProjectKnowledgeRetriever（LangChain Retriever）
# ============================================================
class ProjectKnowledgeRetriever(BaseRetriever):
    """
    LangChain Retriever 适配。
    封装：query embedding → search_similar_chunks → rerank_chunks → Document。

    last_* 属性用于 SSE、trace 和前端调试展示。
    """

    model_config = ConfigDict(arbitrary_types_allowed=True)

    db: Any = Field(exclude=True)
    user_id: int
    top_k: int = 5
    candidate_multiplier: int = 5
    document_ids: list[int] | None = None
    embeddings: Any = Field(default_factory=ProjectEmbeddings, exclude=True)

    _last_query_embedding: list[float] = PrivateAttr(default_factory=list)
    _last_vector_hits: list[RetrievedChunk] = PrivateAttr(default_factory=list)
    _last_reranked_hits: list[RetrievedChunk] = PrivateAttr(default_factory=list)

    @property
    def last_query_embedding(self) -> list[float]:
        return list(self._last_query_embedding)

    @property
    def last_query_embedding_dim(self) -> int:
        return len(self._last_query_embedding)

    @property
    def last_vector_hits(self) -> list[RetrievedChunk]:
        return list(self._last_vector_hits)

    @property
    def last_reranked_hits(self) -> list[RetrievedChunk]:
        return list(self._last_reranked_hits)

    def _get_relevant_documents(self, query: str, *, run_manager) -> list[Document]:
        """LangChain 同步检索入口。"""
        query_embedding = self.embeddings.embed_query(query)
        return self._search_documents(query, query_embedding)

    async def _aget_relevant_documents(
        self, query: str, *, run_manager
    ) -> list[Document]:
        """
        LangChain 异步检索入口。
        FastAPI RAG 接口主流程走这里。
        """
        query_embedding = await self.embeddings.aembed_query(query)
        return self._search_documents(query, query_embedding)

    def retrieve_documents(self, query: str) -> list[Document]:
        return self._get_relevant_documents(query, run_manager=None)

    async def aretrieve_documents(self, query: str) -> list[Document]:
        return await self._aget_relevant_documents(query, run_manager=None)

    def _search_documents(
        self, query: str, query_embedding: list[float]
    ) -> list[Document]:
        """
        真正执行：向量召回 → rerank → 转 Document。
        """
        recall_top_k = max(
            self.top_k * max(self.candidate_multiplier, 1),
            self.top_k,
        )
        vector_hits = search_similar_chunks(
            self.db,
            user_id=self.user_id,
            query_embedding=query_embedding,
            query_text=query,
            top_k=recall_top_k,
            document_ids=self.document_ids or None,
        )
        reranked_hits = rerank_chunks(query, vector_hits, top_k=self.top_k)

        self._last_query_embedding = list(query_embedding)
        self._last_vector_hits = list(vector_hits)
        self._last_reranked_hits = list(reranked_hits)

        return retrieved_chunks_to_langchain_documents(reranked_hits)