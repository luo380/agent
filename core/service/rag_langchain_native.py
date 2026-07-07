from collections.abc import AsyncIterator, Sequence
import re
from typing import Any

from langchain_core.documents import Document
from langchain_core.output_parsers import StrOutputParser
from langchain_core.prompts import ChatPromptTemplate
from langchain_core.runnables import Runnable
from langchain_openai import ChatOpenAI
from openai import AsyncOpenAI

from core.config import settings
from core.service.langchain_adapters import (
    ProjectEmbeddings,
    ProjectKnowledgeRetriever,
    retrieved_chunk_to_langchain_document,
    retrieved_chunks_to_langchain_documents,
)
from core.service.llm import get_default_model, get_default_temperature, get_llm_client
from core.service.retrieval import RetrievedChunk


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


STRUCTURED_SOURCE_SECTION_RE = re.compile(r"^(page|slide|sheet)_(\d+)$", re.IGNORECASE)


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


def _normalize_source_page(value: Any) -> int | None:
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _format_user_facing_section(source_page: Any, source_section: Any) -> str:
    section = str(source_section or "").strip()
    if not section:
        return ""

    match = STRUCTURED_SOURCE_SECTION_RE.fullmatch(section)
    if not match:
        return section

    kind, raw_index = match.groups()
    index = int(raw_index)
    page_number = _normalize_source_page(source_page)

    if kind.lower() == "page":
        if page_number == index:
            return ""
        return f"第 {index} 页"
    if kind.lower() == "slide":
        return f"第 {index} 张"
    if kind.lower() == "sheet":
        return f"工作表 {index}"
    return section


def _build_reference_line(document_name: str, source_page: Any, source_section: Any) -> str:
    page_number = _normalize_source_page(source_page)
    section_text = _format_user_facing_section(source_page, source_section)

    parts = [document_name]
    if page_number is not None:
        parts.append(f"第 {page_number} 页")
    if section_text:
        parts.append(f"章节/区域：{section_text}")
    return "；".join(parts)


def chunk_to_document(chunk: RetrievedChunk | dict) -> Document:
    """
    把项目自己的 RetrievedChunk 转成 LangChain Document。

    这个函数现在只是一个兼容入口，真正的转换逻辑放在
    langchain_adapters.retrieved_chunk_to_langchain_document(...) 里。

    流程图：

    RetrievedChunk
      |
      v
    retrieved_chunk_to_langchain_document(chunk)
      |
      v
    LangChain Document
    """
    return retrieved_chunk_to_langchain_document(chunk)


def chunks_to_documents(chunks: Sequence[RetrievedChunk | dict]) -> list[Document]:
    """
    把检索和 rerank 后的 chunks 批量转成 LangChain Documents。

    这个函数保留下来是为了兼容旧调用点；真正的批量转换逻辑已经移动到
    langchain_adapters.retrieved_chunks_to_langchain_documents(...)。

    流程图：

    list[RetrievedChunk]
      |
      v
    retrieved_chunks_to_langchain_documents(chunks)
      |
      v
    list[Document]
    """
    return retrieved_chunks_to_langchain_documents(chunks)


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
        source_section = _format_user_facing_section(
            source_page,
            metadata.get("source_section"),
        )

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
                "source_section": _format_user_facing_section(
                    metadata.get("source_page"),
                    metadata.get("source_section"),
                ),
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


def build_langchain_retriever(
    db,
    *,
    user_id: int,
    top_k: int = 5,
    document_ids: Sequence[int] | None = None,
    client: AsyncOpenAI | None = None,
    candidate_multiplier: int = 3,
) -> ProjectKnowledgeRetriever:
    """
    构建项目里的 LangChain Retriever。

    这层 helper 的职责很简单：
    - 把项目数据库会话、用户 ID、文档范围等参数收口到一个地方
    - 给 Retriever 注入项目自己的 Embeddings 适配器
    - 避免调用方直接拼装 Retriever 时遗漏依赖
    """
    return ProjectKnowledgeRetriever(
        db=db,
        user_id=user_id,
        top_k=top_k,
        candidate_multiplier=candidate_multiplier,
        document_ids=list(document_ids) if document_ids else None,
        embeddings=ProjectEmbeddings(client=client),
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
    - 如果答案里已经有完整“参考来源”块，直接返回
    - 否则统一追加“参考来源”
    """
    clean_answer = (answer_text or "").strip()

    if not documents:
        return clean_answer

    if not clean_answer:
        clean_answer = "我根据知识库整理了相关信息。"

    if "参考来源：" in clean_answer:
        return clean_answer

    reference_lines: list[str] = []
    seen_references: set[tuple[Any, str, int | None, str]] = set()

    for doc in documents:
        metadata = doc.metadata
        document_name = metadata.get("document_name", "unknown document")
        source_page = metadata.get("source_page")
        section_text = _format_user_facing_section(source_page, metadata.get("source_section"))

        reference_key = (
            metadata.get("document_id"),
            document_name,
            _normalize_source_page(source_page),
            section_text,
        )
        if reference_key in seen_references:
            continue
        seen_references.add(reference_key)
        reference_lines.append(_build_reference_line(document_name, source_page, section_text))

    numbered_reference_lines = [
        f"[{index}] {line}"
        for index, line in enumerate(reference_lines, start=1)
    ]

    return f"{clean_answer}\n\n参考来源：\n" + "\n".join(numbered_reference_lines)


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
    LangChain 原生流式 RAG 主流程。

    这个函数现在分成两段：

    第一段：LangChain Retriever 负责检索
    - 把用户问题转成向量
    - 在当前用户知识库中做向量召回
    - 对候选 chunk 做 rerank
    - 把最终 chunk 转成 LangChain Document

    第二段：LangChain LCEL Chain 负责生成
    - 把 Document 格式化成 context
    - 使用 ChatPromptTemplate 拼 prompt
    - 使用 ChatOpenAI(streaming=True) 调模型
    - 使用 StrOutputParser 输出纯文本
    - 通过 chain.astream(...) 原生流式返回 delta

    完整流程图：

    用户问题 question
      |
      v
    build_langchain_retriever(...)
      |
      v
    ProjectKnowledgeRetriever.aretrieve_documents(question)
      |
      +--> ProjectEmbeddings.aembed_query(question)
      |      |
      |      v
      |   embed_text(question)
      |
      +--> search_similar_chunks_by_embedding(...)
      |
      +--> rerank_chunks(...)
      |
      +--> RetrievedChunk -> LangChain Document
      |
      v
    list[Document]
      |
      v
    format_documents_as_context(documents)
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
    chain.astream(chain_input)
      |
      +--> yield {event: "delta"}
      |
      v
    yield {event: "done"}
    """
    client = client or get_llm_client()

    # Step 1：构建 LangChain Retriever。
    # 这里不再在 service 里手写 embed/search/rerank，而是交给 Retriever 抽象处理。
    # 好处：service 层只关心“我要相关文档”，底层怎么检索由 Retriever 封装。
    retriever = build_langchain_retriever(
        db,
        user_id=user_id,
        top_k=top_k,
        document_ids=document_ids,
        client=client,
    )

    # Step 2：通过 LangChain Retriever 获取相关 Document。
    # 注意：这行代码看起来很短，但内部完整执行了：
    # 1. 用户问题 -> query embedding
    # 2. 向量召回候选 chunk
    # 3. rerank 精排
    # 4. RetrievedChunk -> LangChain Document
    documents = await retriever.aretrieve_documents(question)

    # Retriever 内部会缓存 rerank 后的原始 RetrievedChunk，
    # 这里取出来是为了继续兼容前端 retrieved_chunks 调试展示。
    reranked_hits = retriever.last_reranked_hits

    # Step 3：把 LangChain Document 列表拼成 prompt 里的 context 文本。
    # 大模型最终读的是字符串，所以 Document 需要在这里格式化成上下文。
    context = format_documents_as_context(documents)

    # Step 4??????????????????
    # citations???????????????????????
    # retrieved_chunks??????????? chunk ???????
    # Step 4：准备前端需要的引用来源和检索明细。
    # citations：偏用户可读，用来展示“答案引用了哪些文档”。
    # retrieved_chunks：偏调试，用来展示每个 chunk 的分数和内容。

    # Step 4：准备前端需要的引用来源和检索明细。
    # citations：偏用户可读，用来展示“答案引用了哪些文档”。
    # retrieved_chunks：偏调试，用来展示每个 chunk 的分数和内容。
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
            "query_embedding_dim": retriever.last_query_embedding_dim,
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
                "query_embedding_dim": retriever.last_query_embedding_dim,
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
            "query_embedding_dim": retriever.last_query_embedding_dim,
        },
    }
