from collections.abc import AsyncIterator, Sequence
from typing import Any

from langchain_core.documents import Document
from langchain_core.output_parsers import StrOutputParser
from langchain_core.prompts import ChatPromptTemplate
from langchain_core.runnables import Runnable
from langchain_openai import ChatOpenAI
from openai import AsyncOpenAI

from core.config import settings
from core.service.embedding import embed_text
from core.service.llm import get_default_model, get_default_temperature, get_llm_client
from core.service.retrieval import RetrievedChunk, rerank_chunks, search_similar_chunks_by_embedding


"""
LangChain 原生流式 RAG 服务。

这版专门用于阶段 5 对比学习：
- 不改原来的手写 RAG
- 不手动调用 client.chat.completions.create(stream=True)
- 使用 LangChain 原生 LCEL：prompt | ChatOpenAI | StrOutputParser
- 使用 LangChain 原生流式：chain.astream(...)

整体流程图：

用户问题
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
format_documents_as_context(...)
  |
  v
ChatPromptTemplate
  |
  v
ChatOpenAI(streaming=True)
  |
  v
StrOutputParser()
  |
  v
chain.astream(...)
  |
  v
delta / done
"""


def _chunk_value(chunk: RetrievedChunk | dict, key: str, default: Any = None) -> Any:
    """
    统一读取 chunk 字段。

    正常运行时 chunk 多半是 RetrievedChunk 对象。
    单元测试里 chunk 可能是 dict。
    用这个函数后，后面的转换逻辑就不用关心具体类型。
    """
    if isinstance(chunk, dict):
        return chunk.get(key, default)
    return getattr(chunk, key, default)


def chunk_to_document(chunk: RetrievedChunk | dict) -> Document:
    """
    把项目自己的 RetrievedChunk 转成 LangChain Document。

    映射关系：
    - chunk.content -> Document.page_content
    - chunk.document_name -> metadata["document_name"]
    - chunk.source_page -> metadata["source_page"]
    - chunk.final_score -> metadata["score"]

    注意：
    大模型不会直接读取向量数字。
    它最终读取的是 page_content 里的文本。
    metadata 主要用于引用来源、前端展示和调试。
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


def chunks_to_documents(chunks: Sequence[RetrievedChunk | dict]) -> list[Document]:
    """
    把检索和 rerank 后的 chunks 转成 LangChain Documents。

    这是手写 RAG 和 LangChain RAG 的关键分界点：
    - 这之前是你自己的底层数据结构
    - 这之后进入 LangChain 标准对象体系
    """
    return [chunk_to_document(chunk) for chunk in chunks]


def format_documents_as_context(documents: Sequence[Document]) -> str:
    """
    把 LangChain Documents 格式化成 LLM 可读的 context。

    LangChain Document 是结构化对象。
    LLM 最终读的是文本 prompt。
    所以这里要把 page_content 和 metadata 拼成清晰上下文。
    """
    if not documents:
        return ""

    blocks: list[str] = []
    for index, doc in enumerate(documents, start=1):
        metadata = doc.metadata
        source_page = metadata.get("source_page")
        source_section = metadata.get("source_section")

        header = (
            f"[{index}] "
            f"document={metadata.get('document_name', 'unknown document')}; "
            f"chunk={metadata.get('chunk_index')}; "
            f"page={source_page if source_page is not None else '-'}; "
            f"section={source_section or '-'}"
        )

        blocks.append(header)
        blocks.append(doc.page_content.strip())
        blocks.append("")

    return "\n".join(blocks).strip()


def build_citations_from_documents(documents: Sequence[Document]) -> list[dict]:
    """
    从 Document.metadata 里整理 citations。

    citations 用于前端展示“答案引用了哪些文档”，不是给模型看的。
    """
    citations: list[dict] = []

    for doc in documents:
        metadata = doc.metadata
        citations.append(
            {
                "document_id": metadata.get("document_id"),
                "document_name": metadata.get("document_name"),
                "chunk_id": metadata.get("chunk_id"),
                "chunk_index": metadata.get("chunk_index"),
                "source_page": metadata.get("source_page"),
                "source_section": metadata.get("source_section") or "",
                "score": float(metadata.get("score") or 0.0),
                "content": doc.page_content[:300],
            }
        )

    return citations


def build_retrieved_chunk_payloads(chunks: Sequence[RetrievedChunk | dict]) -> list[dict]:
    """
    把 RetrievedChunk 整理成前端 retrieved_chunks 结构。

    citations 偏“用户可读的答案出处”。
    retrieved_chunks 偏“开发调试的检索明细”。
    """
    payloads: list[dict] = []

    for chunk in chunks:
        payloads.append(
            {
                "document_id": _chunk_value(chunk, "document_id"),
                "document_name": _chunk_value(chunk, "document_name", "unknown document"),
                "chunk_id": _chunk_value(chunk, "chunk_id"),
                "chunk_index": _chunk_value(chunk, "chunk_index"),
                "source_page": _chunk_value(chunk, "source_page"),
                "source_section": _chunk_value(chunk, "source_section", "") or "",
                "content": _chunk_value(chunk, "content", ""),
                "vector_score": float(_chunk_value(chunk, "vector_score", 0.0) or 0.0),
                "keyword_score": float(_chunk_value(chunk, "keyword_score", 0.0) or 0.0),
                "final_score": float(_chunk_value(chunk, "final_score", 0.0) or 0.0),
            }
        )

    return payloads


def build_langchain_rag_prompt(strict_mode: bool) -> ChatPromptTemplate:
    """
    构建 LangChain Prompt。

    对应手写版里的 build_rag_messages()。

    手写版：
    - 自己拼 OpenAI messages list

    LangChain 版：
    - 用 ChatPromptTemplate 表达 prompt
    - 后面可以通过 LCEL 写成 prompt | llm | parser
    """
    if strict_mode:
        system_prompt = (
            "你是一个知识库问答助手。"
            "必须优先依据提供的知识库上下文回答。"
            "如果上下文不足以支持答案，就直接说明知识库中没有足够信息，不要编造。"
        )
    else:
        system_prompt = (
            "你是一个知识库优先的问答助手。"
            "请优先依据提供的知识库上下文回答。"
            "如果知识库没有命中相关内容，可以基于常识做谨慎补充，"
            "但要明确说明这部分不是来自知识库。"
        )

    return ChatPromptTemplate.from_messages(
        [
            ("system", system_prompt),
            (
                "user",
                "用户问题：\n{question}\n\n"
                "知识库上下文：\n{context}\n\n"
                "回答要求：{answer_instruction}",
            ),
        ]
    )


def build_answer_instruction(context: str, strict_mode: bool) -> str:
    """
    根据 context 和 strict_mode 生成回答要求。

    有 context：
    - 要求模型基于知识库回答，并尽量使用 [1]、[2] 引用编号。

    没有 context 且 strict_mode=True：
    - 要求模型不要编造。

    没有 context 且 strict_mode=False：
    - 允许谨慎补充，但必须说明不是来自知识库。
    """
    has_context = bool((context or "").strip())

    if has_context:
        return (
            "请先基于知识库给出简洁回答，"
            "并在确实引用到知识库内容时使用 [1]、[2] 这类来源编号。"
        )

    if strict_mode:
        return (
            "当前没有检索到相关知识库内容。"
            "请直接说明知识库中没有足够信息，不要编造。"
            "不要使用 [1]、[2] 这类引用标记。"
        )

    return (
        "当前没有检索到相关知识库内容。"
        "你可以给出谨慎的补充回答，但必须明确说明这部分不是来自知识库。"
        "不要使用 [1]、[2] 这类引用标记。"
    )


def build_langchain_chat_model(*, streaming: bool) -> ChatOpenAI:
    """
    构建 LangChain 原生 ChatOpenAI 模型。

    关键点：
    - streaming=True 时，模型支持 LangChain 原生流式输出。
    - 后面可以使用 chain.astream(...)。
    - 这和手动 OpenAI SDK stream=True 不一样。

    配置仍然复用项目里的环境变量：
    - OPENAI_BASE_URL
    - OPENAI_API_KEY
    - LLM_MODEL
    - LLM_TEMPERATURE
    """
    return ChatOpenAI(
        model=get_default_model(),
        temperature=get_default_temperature(),
        api_key=settings.OPENAI_API_KEY,
        base_url=settings.OPENAI_BASE_URL,
        streaming=streaming,
    )


def build_langchain_rag_chain(*, strict_mode: bool, streaming: bool = False) -> Runnable:
    """
    构建真正的 LangChain LCEL 生成链。

    链路：
    ChatPromptTemplate
      |
      v
    ChatOpenAI
      |
      v
    StrOutputParser

    LCEL 写法：
    prompt | llm | StrOutputParser()

    非流式执行：
    await chain.ainvoke({...})

    原生流式执行：
    async for delta in chain.astream({...}):
        ...
    """
    prompt = build_langchain_rag_prompt(strict_mode)
    llm = build_langchain_chat_model(streaming=streaming)
    return prompt | llm | StrOutputParser()


def ensure_answer_has_document_citations(answer_text: str, documents: Sequence[Document]) -> str:
    """
    给最终答案补引用兜底。

    Prompt 虽然要求模型输出 [1]、[2]，但模型不一定每次都遵守。
    所以生成结束后统一检查：
    - 如果答案里已经有 [1] 这类引用，直接返回
    - 如果没有，就追加“参考来源”
    """
    clean_answer = (answer_text or "").strip()

    if not documents:
        return clean_answer

    if not clean_answer:
        clean_answer = "我根据知识库整理了相关信息。"

    for index in range(1, len(documents) + 1):
        if f"[{index}]" in clean_answer:
            return clean_answer

    reference_lines: list[str] = []

    for index, doc in enumerate(documents, start=1):
        metadata = doc.metadata
        document_name = metadata.get("document_name", "unknown document")
        source_page = metadata.get("source_page")
        source_section = metadata.get("source_section")

        page_text = f"；第 {source_page} 页" if source_page is not None else ""
        section_text = f"；章节/区域：{source_section}" if source_section else ""
        reference_lines.append(f"[{index}] {document_name}{page_text}{section_text}")

    return f"{clean_answer}\n\n参考来源：\n" + "\n".join(reference_lines)


async def answer_with_knowledge_langchain_native(
    db,
    *,
    user_id: int,
    question: str,
    top_k: int = 5,
    document_ids: Sequence[int] | None = None,
    strict_mode: bool = True,
    client: AsyncOpenAI | None = None,
) -> dict:
    """
    LangChain 原生非流式 RAG。

    这个函数用于普通 JSON 接口。
    它同样使用 LCEL chain，只是执行方式是 chain.ainvoke。
    """
    client = client or get_llm_client()
    query_embedding = await embed_text(question, client=client)

    vector_hits = search_similar_chunks_by_embedding(
        db,
        user_id=user_id,
        query_embedding=query_embedding,
        top_k=max(top_k * 3, top_k),
        document_ids=document_ids,
    )
    reranked_hits = rerank_chunks(question, vector_hits, top_k=top_k)
    documents = chunks_to_documents(reranked_hits)
    context = format_documents_as_context(documents)

    citations = build_citations_from_documents(documents)
    retrieved_chunk_payloads = build_retrieved_chunk_payloads(reranked_hits)

    if not context and strict_mode:
        answer_text = "知识库中没有找到相关内容。请尝试调整提问方式，或缩小/更换文档范围后再试。"
    else:
        chain = build_langchain_rag_chain(strict_mode=strict_mode, streaming=False)
        answer_text = await chain.ainvoke(
            {
                "question": question,
                "context": context or "未检索到相关知识库内容。",
                "answer_instruction": build_answer_instruction(context, strict_mode),
            }
        )

    answer_text = ensure_answer_has_document_citations(answer_text, documents)

    return {
        "answer": answer_text,
        "citations": citations,
        "retrieved_chunks": retrieved_chunk_payloads,
        "documents": documents,
        "context": context,
        "query_embedding_dim": len(query_embedding),
    }


async def stream_answer_with_knowledge_langchain_native(
    db,
    *,
    user_id: int,
    question: str,
    top_k: int = 5,
    document_ids: Sequence[int] | None = None,
    strict_mode: bool = True,
    client: AsyncOpenAI | None = None,
) -> AsyncIterator[dict]:
    """
    LangChain 原生流式 RAG。

    这里真正使用：
    async for delta in chain.astream(...)

    这就是你想看的 chain.invoke -> chain.stream/astream 思路。
    由于 FastAPI 路由是 async，所以这里用 astream，而不是同步 stream。
    """
    client = client or get_llm_client()

    # Step 1：用户问题转 query embedding。
    # 仍然复用你第 4 阶段已经写好的 embedding 能力。
    query_embedding = await embed_text(question, client=client)

    # Step 2：在当前用户知识库范围内做向量检索。
    # top_k * 3 是候选召回数量，给 rerank 留出空间。
    vector_hits = search_similar_chunks_by_embedding(
        db,
        user_id=user_id,
        query_embedding=query_embedding,
        top_k=max(top_k * 3, top_k),
        document_ids=document_ids,
    )

    # Step 3：对候选 chunk 做精排。
    reranked_hits = rerank_chunks(question, vector_hits, top_k=top_k)

    # Step 4：转成 LangChain Document。
    documents = chunks_to_documents(reranked_hits)

    # Step 5：Document -> prompt context。
    context = format_documents_as_context(documents)

    # Step 6：提前准备前端最终需要的数据。
    citations = build_citations_from_documents(documents)
    retrieved_chunk_payloads = build_retrieved_chunk_payloads(reranked_hits)

    # Step 7：先通知前端检索完成。
    # 前端可以展示“已找到 N 条相关内容，正在生成答案”。
    yield {
        "event": "context_ready",
        "data": {
            "retrieved_chunk_count": len(retrieved_chunk_payloads),
            "citation_count": len(citations),
            "context_length": len(context),
            "query_embedding_dim": len(query_embedding),
        },
    }

    # Step 8：严格模式下没有 context，不调用模型，避免幻觉。
    if not context and strict_mode:
        answer_text = "知识库中没有找到相关内容。请尝试调整提问方式，或缩小/更换文档范围后再试。"
        answer_text = ensure_answer_has_document_citations(answer_text, documents)
        yield {
            "event": "done",
            "data": {
                "answer": answer_text,
                "strict_mode": strict_mode,
                "citations": citations,
                "retrieved_chunks": retrieved_chunk_payloads,
                "context": context,
                "query_embedding_dim": len(query_embedding),
            },
        }
        return

    # Step 9：构建 LangChain 原生流式链。
    # 重点就是 streaming=True + chain.astream。
    chain = build_langchain_rag_chain(strict_mode=strict_mode, streaming=True)

    chain_input = {
        "question": question,
        "context": context or "未检索到相关知识库内容。",
        "answer_instruction": build_answer_instruction(context, strict_mode),
    }

    answer_parts: list[str] = []

    # Step 10：真正执行 LangChain 原生流式。
    # StrOutputParser 会让 astream 持续吐出文本片段。
    async for delta in chain.astream(chain_input):
        if not delta:
            continue

        answer_parts.append(delta)
        yield {
            "event": "delta",
            "data": {"content": delta},
        }

    # Step 11：流式结束后，拼出完整答案，用于落库和 done 事件。
    answer_text = "".join(answer_parts).strip()
    answer_text = ensure_answer_has_document_citations(answer_text, documents)

    # Step 12：发送最终完整结果。
    yield {
        "event": "done",
        "data": {
            "answer": answer_text,
            "strict_mode": strict_mode,
            "citations": citations,
            "retrieved_chunks": retrieved_chunk_payloads,
            "context": context,
            "query_embedding_dim": len(query_embedding),
        },
    }
