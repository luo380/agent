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

from core.service.chunking import chunk_parsed_document, chunk_text
from core.service.document_parser import parse_document
from core.service.embedding import embed_text, embed_texts
from core.service.retrieval import RetrievedChunk, rerank_chunks, search_similar_chunks_by_embedding


"""
阶段 5：把第 4 阶段手写 RAG 包装成 LangChain 抽象。

这个文件不是重写底层能力，而是做“适配层”：
- 解析文件仍然复用 parse_document(...)
- 文本切块仍然复用 chunk_parsed_document(...) / chunk_text(...)
- 向量生成仍然复用 embed_text(...) / embed_texts(...)
- 向量召回和精排仍然复用 search_similar_chunks_by_embedding(...) / rerank_chunks(...)

最终目标是让你能在代码里看到岗位 JD 常写的 LangChain 关键词：
- Document Loader
- Text Splitter
- Embeddings
- Retriever

入库链路流程图：

文件路径 + 文件类型
  |
  v
ProjectDocumentLoader
  |
  v
parse_document(...)
  |
  v
parsed_document: full_text / pages / sections / metadata
  |
  v
ProjectTextSplitter
  |
  +--> chunk_parsed_document(...)  保留页码、章节、工作表等来源信息
  |
  +--> chunk_text(...)             没有结构化信息时的兜底纯文本切块
  |
  v
list[LangChain Document]
  |
  v
ProjectEmbeddings
  |
  v
embed_texts(...)
  |
  v
向量入库

在线 RAG 检索流程图：

用户问题 question
  |
  v
ProjectKnowledgeRetriever
  |
  v
ProjectEmbeddings.aembed_query(question)
  |
  v
embed_text(question)
  |
  v
search_similar_chunks_by_embedding(...)
  |
  v
rerank_chunks(...)
  |
  v
RetrievedChunk -> LangChain Document
  |
  v
list[Document]
"""


def _chunk_value(chunk: RetrievedChunk | dict, key: str, default: Any = None) -> Any:
    """
    统一读取 chunk 字段。

    为什么要封装这一层：
    - 正常业务里 chunk 是 RetrievedChunk 对象
    - 测试代码里 chunk 有时会用 dict 模拟
    - 后面转换 Document 时就不用关心具体类型
    """
    if isinstance(chunk, dict):
        return chunk.get(key, default)
    return getattr(chunk, key, default)


def retrieved_chunk_to_langchain_document(chunk: RetrievedChunk | dict) -> Document:
    """
    把项目自己的 RetrievedChunk 转成 LangChain Document。

    这是第 4 阶段和第 5 阶段之间最关键的桥：

    RetrievedChunk.content       -> Document.page_content
    RetrievedChunk.document_id   -> Document.metadata["document_id"]
    RetrievedChunk.document_name -> Document.metadata["document_name"]
    RetrievedChunk.chunk_id      -> Document.metadata["chunk_id"]
    RetrievedChunk.chunk_index   -> Document.metadata["chunk_index"]
    RetrievedChunk.source_page   -> Document.metadata["source_page"]
    RetrievedChunk.final_score   -> Document.metadata["score"]

    流程图：

    RetrievedChunk
      |
      v
    读取 content / 文档名 / 页码 / 分数
      |
      v
    Document(page_content=文本, metadata=来源信息)
      |
      v
    交给 LangChain Prompt / Chain / 前端引用展示
    """
    final_score = _chunk_value(chunk, "final_score")
    vector_score = _chunk_value(chunk, "vector_score")

    return Document(
        # page_content 是大模型真正会读到的文本。
        page_content=(_chunk_value(chunk, "content", "") or "").strip(),
        metadata={
            # metadata 不直接作为回答内容，它主要用于引用、调试和前端展示。
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
    """
    批量把检索结果转成 LangChain Document。

    流程图：

    list[RetrievedChunk]
      |
      v
    for each chunk
      |
      v
    retrieved_chunk_to_langchain_document(chunk)
      |
      v
    list[Document]
    """
    return [retrieved_chunk_to_langchain_document(chunk) for chunk in chunks]


class ProjectDocumentLoader(BaseLoader):
    """
    项目版 LangChain Document Loader。

    对应 LangChain 概念：Document Loader。

    作用：
    - 负责把文件读进来
    - 负责调用项目已有的 parse_document(...)
    - 产出 LangChain 标准 Document

    注意：
    Loader 不负责切块。切块交给 ProjectTextSplitter。

    流程图：

    file_path + file_type
      |
      v
    ProjectDocumentLoader.load()
      |
      v
    parse_document(file_path, file_type)
      |
      v
    parsed_document
      |
      v
    Document(page_content=full_text, metadata={parsed_document, file_type, file_path})
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
        调用项目已有的统一文档解析入口。

        parse_document(...) 返回的结构通常包含：
        - full_text：整篇纯文本
        - pages：按页解析的内容，PDF / PPTX 常用
        - sections：按章节或工作表解析的内容，DOCX / Excel 常用
        - metadata：解析器额外信息
        """
        return parse_document(self.file_path, file_type=self.file_type)

    def lazy_load(self) -> Iterator[Document]:
        """
        LangChain Loader 标准接口。

        这里先 yield 一个整篇文档 Document。
        后续再交给 TextSplitter 切成多个 chunk Document。
        """
        parsed_document = self.load_parsed_document()
        file_name = self.metadata.get("document_name") or Path(self.file_path).name

        yield Document(
            page_content=parsed_document.get("full_text", "") or "",
            metadata={
                **self.metadata,
                "document_name": file_name,
                "file_path": self.file_path,
                "file_type": self.file_type,
                # 把结构化解析结果继续传给 Splitter，避免丢失页码和章节信息。
                "parsed_document": parsed_document,
                "parser_metadata": parsed_document.get("metadata") or {},
            },
        )


class ProjectTextSplitter(TextSplitter):
    """
    项目版 LangChain Text Splitter。

    对应 LangChain 概念：Text Splitter。

    它不替换你原来的切块算法，而是包装你原来的切块函数：
    - chunk_parsed_document(...)：优先使用，保留页码/章节等结构化来源
    - chunk_text(...)：兜底使用，只处理普通纯文本

    流程图：

    list[Document]
      |
      v
    每个 Document 是否带 parsed_document?
      |
      +--> 是：chunk_parsed_document(...)
      |        |
      |        v
      |      带 source_page / source_section 的 chunk Documents
      |
      +--> 否：create_documents(...) / split_text(...)
               |
               v
             普通 chunk Documents
    """

    def __init__(self, *, chunk_size: int = 500, chunk_overlap: int = 100) -> None:
        super().__init__(
            chunk_size=chunk_size,
            chunk_overlap=chunk_overlap,
            add_start_index=False,
        )
        self.project_chunk_size = chunk_size
        self.project_chunk_overlap = chunk_overlap

    def split_text(self, text: str) -> list[str]:
        """
        纯文本切块入口。

        LangChain TextSplitter 要求实现 split_text(...)。
        这里直接复用你第 4 阶段写好的 chunk_text(...)。
        """
        return [
            item["content"]
            for item in chunk_text(
                text,
                chunk_size=self.project_chunk_size,
                overlap=self.project_chunk_overlap,
            )
        ]

    def split_documents(self, documents: Sequence[Document]) -> list[Document]:
        """
        把 Loader 产出的 Document 切成多个 chunk Document。

        重点：
        - 如果 metadata 里有 parsed_document，说明它来自项目解析器
        - 此时优先走 chunk_parsed_document(...)，保留来源页码和章节
        - 如果没有 parsed_document，就退回 LangChain 标准纯文本切块
        """
        split_documents: list[Document] = []

        for document in documents:
            base_metadata = dict(document.metadata or {})
            parsed_document = base_metadata.pop("parsed_document", None)

            if parsed_document is None:
                split_documents.extend(self.create_documents([document.page_content], [base_metadata]))
                continue

            chunk_items = chunk_parsed_document(
                parsed_document,
                chunk_size=self.project_chunk_size,
                overlap=self.project_chunk_overlap,
            )

            for chunk in chunk_items:
                split_documents.append(
                    Document(
                        page_content=chunk["content"],
                        metadata={
                            **base_metadata,
                            "chunk_index": chunk["chunk_index"],
                            "start_offset": chunk["start_offset"],
                            "end_offset": chunk["end_offset"],
                            "source_page": chunk["source_page"],
                            "source_section": chunk["source_section"],
                            "lc_splitter": "project_chunk_parsed_document",
                        },
                    )
                )

        return split_documents


class ProjectEmbeddings(Embeddings):
    """
    项目版 LangChain Embeddings。

    对应 LangChain 概念：Embeddings。

    它把项目已有的 embedding 函数包装成 LangChain 标准接口：
    - embed_query(text)：单条文本转向量
    - embed_documents(texts)：多条文本批量转向量
    - aembed_query(text)：异步单条文本转向量
    - aembed_documents(texts)：异步批量文本转向量

    流程图：

    LangChain 调用 Embeddings
      |
      +--> aembed_query(question)
      |      |
      |      v
      |    embed_text(question)
      |
      +--> aembed_documents(chunks)
             |
             v
           embed_texts(chunks)
    """

    def __init__(self, *, client: Any = None) -> None:
        self.client = client

    def embed_query(self, text: str) -> list[float]:
        """
        同步单文本 embedding。

        在本项目的 FastAPI 异步链路中，更推荐使用 aembed_query(...)。
        """
        return self._run_async(self.aembed_query(text))

    def embed_documents(self, texts: list[str]) -> list[list[float]]:
        """
        同步批量 embedding。
        """
        return self._run_async(self.aembed_documents(texts))

    async def aembed_query(self, text: str) -> list[float]:
        """
        异步单文本 embedding，实际调用项目自己的 embed_text(...)。
        """
        return await embed_text(text, client=self.client)

    async def aembed_documents(self, texts: list[str]) -> list[list[float]]:
        """
        异步批量 embedding，实际调用项目自己的 embed_texts(...)。
        """
        return await embed_texts(texts, client=self.client)

    @staticmethod
    def _run_async(coroutine):
        """
        为同步接口提供兜底执行方式。

        如果当前已经在事件循环里，不能再 asyncio.run(...)。
        所以异步环境下应该直接调用 aembed_query / aembed_documents。
        """
        try:
            asyncio.get_running_loop()
        except RuntimeError:
            return asyncio.run(coroutine)

        raise RuntimeError(
            "ProjectEmbeddings synchronous methods were called inside an active event loop. "
            "Use aembed_query() or aembed_documents() in async code."
        )


class ProjectKnowledgeRetriever(BaseRetriever):
    """
    项目版 LangChain Retriever。

    对应 LangChain 概念：Retriever。

    这是阶段 5 的核心：把你第 4 阶段的手写检索链路封装为标准 Retriever。

    内部仍然是你自己的逻辑：
    1. embed_text(question) 生成问题向量
    2. search_similar_chunks_by_embedding(...) 做向量召回
    3. rerank_chunks(...) 做加权精排
    4. retrieved_chunks_to_langchain_documents(...) 转成 LangChain Document

    上层调用方式变成：
    documents = await retriever.aretrieve_documents(question)

    流程图：

    question
      |
      v
    ProjectKnowledgeRetriever.aretrieve_documents(question)
      |
      v
    ProjectEmbeddings.aembed_query(question)
      |
      v
    query_embedding
      |
      v
    search_similar_chunks_by_embedding(...)
      |
      v
    vector_hits
      |
      v
    rerank_chunks(question, vector_hits, top_k)
      |
      v
    reranked_hits
      |
      v
    retrieved_chunks_to_langchain_documents(reranked_hits)
      |
      v
    list[Document]
    """

    model_config = ConfigDict(arbitrary_types_allowed=True)

    db: Any = Field(exclude=True)
    user_id: int
    top_k: int = 5
    candidate_multiplier: int = 3
    document_ids: list[int] | None = None
    embeddings: Any = Field(default_factory=ProjectEmbeddings, exclude=True)

    # 这些 last_* 字段用于保留中间过程，方便 SSE、trace 和前端调试展示。
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
        """
        LangChain 同步检索入口。
        """
        query_embedding = self.embeddings.embed_query(query)
        return self._search_documents(query, query_embedding)

    async def _aget_relevant_documents(self, query: str, *, run_manager) -> list[Document]:
        """
        LangChain 异步检索入口。

        FastAPI 的 RAG 接口是异步的，所以主流程会走这个方法。
        """
        query_embedding = await self.embeddings.aembed_query(query)
        return self._search_documents(query, query_embedding)

    def retrieve_documents(self, query: str) -> list[Document]:
        return self._get_relevant_documents(query, run_manager=None)

    async def aretrieve_documents(self, query: str) -> list[Document]:
        return await self._aget_relevant_documents(query, run_manager=None)

    def _search_documents(self, query: str, query_embedding: list[float]) -> list[Document]:
        """
        执行真正的召回、精排和 Document 转换。

        流程图：

        query_embedding
          |
          v
        search_similar_chunks_by_embedding(...)
          |
          v
        vector_hits
          |
          v
        rerank_chunks(...)
          |
          v
        reranked_hits
          |
          v
        list[Document]
        """
        recall_top_k = max(self.top_k * max(self.candidate_multiplier, 1), self.top_k)

        vector_hits = search_similar_chunks_by_embedding(
            self.db,
            user_id=self.user_id,
            query_embedding=query_embedding,
            top_k=recall_top_k,
            document_ids=self.document_ids or None,
        )
        reranked_hits = rerank_chunks(query, vector_hits, top_k=self.top_k)

        self._last_query_embedding = list(query_embedding)
        self._last_vector_hits = list(vector_hits)
        self._last_reranked_hits = list(reranked_hits)

        return retrieved_chunks_to_langchain_documents(reranked_hits)
