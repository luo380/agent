#
#
# """
# 用户问题
#   |
#   v
# embed_text(question)                         # 仍然复用你自己的 embedding 能力
#   |
#   v
# search_similar_chunks_by_embedding(...)      # 仍然复用你自己的向量检索
#   |
#   v
# rerank_chunks(...)                           # 仍然复用你自己的重排
#   |
#   v
# RetrievedChunk -> LangChain Document         # 新增：转成 LangChain 标准文档对象
#   |
#   v
# format_documents_as_context(...)             # 把 Document 格式化成 prompt context
#   |
#   v
# ChatPromptTemplate                           # 新增：LangChain Prompt 抽象
#   |
#   v
# Runnable chain                               # 新增：LangChain LCEL 链式编排
#   |
#   v
# LLM
#   |
#   v
# answer + citations
#
#
# ===============================================================================
# 核心区别
# ===============================================================================
#
# 手写版：
# - 你自己管理 chunk
# - 你自己拼 context
# - 你自己拼 messages
# - 你自己调模型
#
# LangChain 版：
# - 用 Document 表示 chunk
# - 用 ChatPromptTemplate 表示 prompt
# - 用 Runnable / LCEL 表示执行链路
# - 底层检索能力仍然可以复用你自己写的代码
#
# 注意：
# 这里没有重做 Document Loader / Text Splitter，因为你的项目第 4 阶段已经完成了
# 文档解析、chunking、embedding 入库。阶段 5 的重点是“问答链路 LangChain 化”。
# """
# from typing import Any, Sequence
#
# from langchain_core.documents import Document
# from langchain_core.messages import BaseMessage, AIMessage
# from langchain_core.output_parsers import StrOutputParser
# from langchain_core.prompts import ChatPromptTemplate
# from langchain_core.runnables import RunnableLambda, Runnable
# from openai import AsyncOpenAI
#
# from core.service.embedding import embed_text
# from core.service.llm import get_default_model, get_default_temperature, get_llm_client
# from core.service.retrieval import RetrievedChunk, rerank_chunks, search_similar_chunks_by_embedding
#
#
# # 返回对象统一处理函数
# def _chunk_value(chunk: RetrievedChunk | dict, key: str, default: Any = None) -> Any:
#     """
#     兼容两种 chunk 形态：
#     1. 正常项目运行时，chunk 可能是 RetrievedChunk 对象
#     2. 单元测试里，chunk 可能是 dict
#
#     这样写的好处：
#     - 你以后写测试更方便
#     - 不要求所有数据都必须是同一种类型
#     """
#     if isinstance(chunk, dict):
#         return chunk.get(key, default)
#     return getattr(chunk, key, default)
#
# def chunk_to_document(chunk: RetrievedChunk | dict) -> Document:
#     """
#        把你项目里的 RetrievedChunk 转成 LangChain 的 Document。
#
#        这是阶段 5 最重要的映射之一：
#
#        RetrievedChunk                    LangChain Document
#        ----------------------------------------------------------------
#        chunk.content                  -> Document.page_content
#        chunk.document_id              -> Document.metadata["document_id"]
#        chunk.document_name            -> Document.metadata["document_name"]
#        chunk.chunk_id                 -> Document.metadata["chunk_id"]
#        chunk.chunk_index              -> Document.metadata["chunk_index"]
#        chunk.source_page              -> Document.metadata["source_page"]
#        chunk.source_section           -> Document.metadata["source_section"]
#        chunk.final_score/vector_score -> Document.metadata["score"]
#
#        注意：
#        大模型最后看的不是“向量数字”，而是 page_content 里的文本内容。
#        metadata 是给引用、调试、前端展示用的。
#        """
#     final_score = _chunk_value(chunk, "final_score")
#     vector_score = _chunk_value(chunk, "vector_score")
#
#     return Document(
#         page_content=(_chunk_value(chunk, "content", "") or "").strip(),
#         metadata={
#             "document_id": _chunk_value(chunk, "document_id"),
#             "document_name": _chunk_value(chunk, "document_name", "unknown document"),
#             "chunk_id": _chunk_value(chunk, "chunk_id"),
#             "chunk_index": _chunk_value(chunk, "chunk_index"),
#             "source_page": _chunk_value(chunk, "source_page"),
#             "source_section": _chunk_value(chunk, "source_section"),
#             "vector_score": vector_score,
#             "keyword_score": _chunk_value(chunk, "keyword_score"),
#             "final_score": final_score,
#             "score": final_score if final_score is not None else vector_score,
#         },
#     )
#
#
# def chunks_to_documents(chunks: Sequence[RetrievedChunk | dict]) -> list[Document]:
#     """
#     把检索 + rerank 后的 chunk 列表，统一转换成 LangChain Documents。
#
#     这一层的意义：
#     - 你的底层检索仍然用自己的
#     - 但从这里开始，进入 LangChain 的标准对象体系
#     """
#     return [chunk_to_document(chunk) for chunk in chunks]
#
# def format_documents_as_context(documents: Sequence[Document]) -> str:
#     """
#        把 LangChain Document 列表格式化成大模型能读懂的上下文。
#
#        这一步对应你原来的 build_context()。
#
#        为什么还要格式化？
#        - Document 是结构化对象
#        - 但大模型最终读的是文本 prompt
#        - 所以我们要把 Document.page_content 和 metadata 拼成清晰的上下文
#
#        输出示例：
#
#        [1] document=manual.md; chunk=0; page=1; section=maintenance
#        Clean the brush and filter regularly.
#
#        [2] document=faq.md; chunk=3; page=-; section=-
#        If installation fails, check your network.
#        """
#     if not documents:
#         return ""
#
#     blocks: list[str] = []
#
#     for index, doc in enumerate(documents, start=1):
#         metadata = doc.metadata
#
#         source_page = metadata.get("source_page")
#         source_section = metadata.get("source_section")
#
#         header = (
#             f"[{index}] "
#             f"document={metadata.get('document_name', 'unknown document')}; "
#             f"chunk={metadata.get('chunk_index')}; "
#             f"page={source_page if source_page is not None else '-'}; "
#             f"section={source_section or '-'}"
#         )
#
#         blocks.append(header)
#         blocks.append(doc.page_content.strip())
#         blocks.append("")
#
#     return "\n".join(blocks).strip()
#
#
# # 从 LangChain Documents 里生成 citations
# def build_citations_from_documents(documents: Sequence[Document]) -> list[dict]:
#     """
#     从 LangChain Documents 里生成 citations。
#
#     这一步对应你原来的 build_citations()。
#
#     注意：
#     citations 不一定要给模型看。
#     它主要是返回给前端，用来展示“答案引用了哪些文档”。
#     """
#     citations: list[dict] = []
#
#     for doc in documents:
#         metadata = doc.metadata
#
#         citations.append(
#             {
#                 "document_id": metadata.get("document_id"),
#                 "document_name": metadata.get("document_name"),
#                 "chunk_id": metadata.get("chunk_id"),
#                 "chunk_index": metadata.get("chunk_index"),
#                 "source_page": metadata.get("source_page"),
#                 "source_section": metadata.get("source_section"),
#                 "score": metadata.get("score"),
#                 "content": doc.page_content[:300],
#             }
#         )
#
#     return citations
#
#
# # 构建 RAG Prompt 的 chunk payload
# def build_retrieved_chunk_payloads(chunks: Sequence[RetrievedChunk | dict]) -> list[dict]:
#     payloads: list[dict] = []
#
#     for chunk in chunks:
#         payloads.append(
#             {
#                 "document_id": _chunk_value(chunk, "document_id"),
#                 "document_name": _chunk_value(chunk, "document_name", "unknown document"),
#                 "chunk_id": _chunk_value(chunk, "chunk_id"),
#                 "chunk_index": _chunk_value(chunk, "chunk_index"),
#                 "source_page": _chunk_value(chunk, "source_page"),
#                 "source_section": _chunk_value(chunk, "source_section", "") or "",
#                 "content": _chunk_value(chunk, "content", ""),
#                 "vector_score": float(_chunk_value(chunk, "vector_score", 0.0) or 0.0),
#                 "keyword_score": float(_chunk_value(chunk, "keyword_score", 0.0) or 0.0),
#                 "final_score": float(_chunk_value(chunk, "final_score", 0.0) or 0.0),
#             }
#         )
#
#     return payloads
#
# # 构建 RAG Prompt
# def build_langchain_rag_prompt(strict_mode: bool) -> ChatPromptTemplate:
#     """
#     构建 LangChain Prompt。
#
#     这一步对应你原来的 build_rag_messages()。
#
#     区别：
#     - 原来你返回的是 OpenAI messages list
#     - 现在返回的是 LangChain 的 ChatPromptTemplate
#     - 后面可以用 LCEL 的 | 和 LLM Runnable 串起来
#
#     strict_mode=True：
#     - 只能根据知识库回答
#     - 没有依据就说没有足够信息
#
#     strict_mode=False：
#     - 优先根据知识库回答
#     - 知识库没有时，可以谨慎补充，但要说明不是来自知识库
#     """
#     if strict_mode:
#         system_prompt = (
#             "你是一个知识库问答助手。"
#             "必须优先依据提供的知识库上下文回答。"
#             "如果上下文不足以支持答案，就直接说明知识库中没有足够信息，不要编造。"
#         )
#     else:
#         system_prompt = (
#             "你是一个知识库优先的问答助手。"
#             "请优先依据提供的知识库上下文回答。"
#             "如果知识库没有命中相关内容，可以基于常识做谨慎补充，"
#             "但要明确说明这部分不是来自知识库。"
#         )
#
#     return ChatPromptTemplate.from_messages(
#         [
#             ("system", system_prompt),
#             (
#                 "user",
#                 "用户问题：\n{question}\n\n"
#                 "知识库上下文：\n{context}\n\n"
#                 "回答要求：{answer_instruction}",
#             ),
#         ]
#     )
#
#
# #  辅助方法：生成回答要求
# def build_answer_instruction(context: str, strict_mode: bool) -> str:
#     """
#     根据是否有 context，生成回答要求。
#
#     这部分逻辑对应你原来 build_rag_messages() 里的 answer_instruction。
#     """
#     has_context = bool((context or "").strip())
#
#     if has_context:
#         return (
#             "请先基于知识库给出简洁回答，"
#             "并在确实引用到知识库内容时使用 [1]、[2] 这类来源编号。"
#         )
#
#     if strict_mode:
#         return (
#             "当前没有检索到相关知识库内容。"
#             "请直接说明知识库中没有足够信息，不要编造。"
#             "不要使用 [1]、[2] 这类引用标记。"
#         )
#
#     return (
#         "当前没有检索到相关知识库内容。"
#         "你可以给出谨慎的补充回答，但必须明确说明这部分不是来自知识库。"
#         "不要使用 [1]、[2] 这类引用标记。"
#     )
#
#
# # 转换 LangChain 消息为 OpenAI 格式
# def _langchain_messages_to_openai_messages(messages: list[BaseMessage]) -> list[dict]:
#     """
#     把 LangChain 的消息对象转换成 OpenAI SDK 能接受的 messages 格式。
#
#     为什么需要这一步？
#     - 你的项目现在已经有 get_llm_client()
#     - 它返回的是 OpenAI 兼容客户端 AsyncOpenAI
#     - 为了少改项目配置，这里不强制引入 langchain_openai.ChatOpenAI
#     - 而是用 RunnableLambda 包一层你现有的 OpenAI 调用
#
#     LangChain message type:
#     - system -> OpenAI role: system
#     - human  -> OpenAI role: user
#     - ai     -> OpenAI role: assistant
#     """
#
#
#     role_map = {
#         "system": "system",
#         "human": "user",
#         "ai": "assistant",
#     }
#     """
#     角色	        谁发的	    用途
#     system	    开发者	    给模型定规矩、人设
#     user	    用户	        提问、输入内容
#     assistant	AI 模型	    回答、输出内容
#     """
#     openai_messages: list[dict] = []
#
#     for message in messages:
#         openai_messages.append(
#             {
#                 "role": role_map.get(message.type, "user"),
#                 "content": message.content,
#             }
#         )
#
#     return openai_messages
#
#
# # 构建 LLM Runnable
# def build_llm_runnable(client: AsyncOpenAI) -> Runnable:
#     """
#     把你现有的 OpenAI SDK 调用包装成 LangChain Runnable。
#
#     这是阶段 5 的重点之一：
#
#     原来：
#         await client.chat.completions.create(...)
#
#     现在：
#         prompt | llm_runnable | StrOutputParser()
#
#     也就是说，底层还是你的模型客户端，
#     但外层已经变成 LangChain Runnable 链路。
#     """
#
#     async def call_llm(prompt_value) -> AIMessage:
#         """
#         prompt_value 是 ChatPromptTemplate 格式化之后的结果。
#
#         它可以转成 LangChain messages，
#         然后我们再转成 OpenAI SDK 需要的 messages。
#         """
#         langchain_messages = prompt_value.to_messages()
#         openai_messages = _langchain_messages_to_openai_messages(langchain_messages)
#
#         completion = await client.chat.completions.create(
#             model=get_default_model(),
#             messages=openai_messages,
#             temperature=get_default_temperature(),
#         )
#
#         answer_text = (completion.choices[0].message.content or "").strip()
#         return AIMessage(content=answer_text)
#
#     return RunnableLambda(call_llm)
#
#
# # 构建 RAG Chain
# def build_langchain_rag_chain(
#     *,
#     client: AsyncOpenAI,
#     strict_mode: bool,
# ) -> Runnable:
#     """
#     构建 LangChain 版 RAG Chain。
#
#     这一步对应你原来 answer_with_knowledge() 里：
#     - build_rag_messages()
#     - client.chat.completions.create()
#     - 取出 answer_text
#
#     LCEL 链路如下：
#
#     input dict
#       |
#       v
#     ChatPromptTemplate
#       |
#       v
#     LLM Runnable
#       |
#       v
#     StrOutputParser
#       |
#       v
#     answer string
#
#     这里的 | 就是 LangChain LCEL 的链式写法。
#     """
#     prompt = build_langchain_rag_prompt(strict_mode)
#     llm = build_llm_runnable(client)
#
#     return prompt | llm | StrOutputParser()
#
#
#
# # 给答案补引用
# def ensure_answer_has_document_citations(answer_text: str, documents: Sequence[Document]) -> str:
#     """
#     给答案补引用兜底。
#
#     这一步对应你原来的 ensure_answer_has_citations()。
#
#     为什么需要？
#     - prompt 里虽然要求模型输出 [1]、[2]
#     - 但模型不一定总是听话
#     - 所以这里做一道兜底：只要有检索结果，就保证最终答案里能看到来源
#     """
#     clean_answer = (answer_text or "").strip()
#
#     if not documents:
#         return clean_answer
#
#     if not clean_answer:
#         clean_answer = "我根据知识库整理了相关信息。"
#
#     # 如果模型已经输出了 [1]、[2] 这种引用，就不重复追加。
#     for index in range(1, len(documents) + 1):
#         if f"[{index}]" in clean_answer:
#             return clean_answer
#
#     reference_lines: list[str] = []
#
#     for index, doc in enumerate(documents, start=1):
#         metadata = doc.metadata
#
#         document_name = metadata.get("document_name", "unknown document")
#         source_page = metadata.get("source_page")
#         source_section = metadata.get("source_section")
#
#         page_text = f"；第 {source_page} 页" if source_page is not None else ""
#         section_text = f"；章节/区域：{source_section}" if source_section else ""
#
#         reference_lines.append(f"[{index}] {document_name}{page_text}{section_text}")
#
#     return f"{clean_answer}\n\n参考来源：\n" + "\n".join(reference_lines)
#
#
#
# # 完整 RAG 主函数
# async def stream_answer_with_knowledge_langchain(
#     db,
#     *,
#     user_id: int,
#     question: str,
#     top_k: int = 5,
#     document_ids: Sequence[int] | None = None,
#     strict_mode: bool = True,
#     client: AsyncOpenAI | None = None,
# ) -> dict:
#     """
#     LangChain 版完整 RAG 主函数。
#
#     这个函数对应你原来的：
#         answer_with_knowledge()
#
#     但内部组织方式换成了 LangChain 风格。
#
#     ===========================================================================
#     完整流程图
#     ===========================================================================
#
#     用户问题 question
#       |
#       v
#     1. embed_text(question)
#        把用户问题转成 query embedding
#       |
#       v
#     2. search_similar_chunks_by_embedding(...)
#        在当前用户知识库里做向量检索
#       |
#       v
#     3. rerank_chunks(...)
#        对候选 chunk 做加权排序/精排
#       |
#       v
#     4. chunks_to_documents(...)
#        把 RetrievedChunk 转成 LangChain Document
#       |
#       v
#     5. format_documents_as_context(...)
#        把 Document 列表格式化成 prompt context
#       |
#       v
#     6. build_langchain_rag_chain(...)
#        构建 LangChain Runnable 链
#       |
#       v
#     7. chain.ainvoke(...)
#        执行 LangChain 链，调用模型生成答案
#       |
#       v
#     8. citations + answer + context
#        返回结构化结果
#
#     ===========================================================================
#     和手写版的区别
#     ===========================================================================
#
#     手写版重点：
#         你自己一步一步组织 messages 和 LLM 调用。
#
#     LangChain 版重点：
#         用 Document / Prompt / Runnable 把这些步骤标准化。
#     """
#     client = client or get_llm_client()
#
#     # -------------------------------------------------------------------------
#     # Step 1：问题转向量
#     # -------------------------------------------------------------------------
#     # 这一步仍然复用你自己写的 embed_text。
#     # 阶段 5 不是推翻第 4 阶段，而是把第 4 阶段能力包装进 LangChain 抽象里。
#     query_embedding = await embed_text(question, client=client)
#
#     # -------------------------------------------------------------------------
#     # Step 2：向量检索
#     # -------------------------------------------------------------------------
#     # 这一步仍然复用你自己的数据库向量检索逻辑。
#     # 先取 top_k * 3 个候选，给后面的 rerank 更多选择空间。
#     vector_hits = search_similar_chunks_by_embedding(
#         db,
#         user_id=user_id,
#         query_embedding=query_embedding,
#         top_k=max(top_k * 3, top_k),
#         document_ids=document_ids,
#     )
#
#     # -------------------------------------------------------------------------
#     # Step 3：rerank 精排
#     # -------------------------------------------------------------------------
#     # 这一步仍然复用你第 4 阶段写的 rerank_chunks。
#     # LangChain 不是必须替代所有底层逻辑，真实项目里经常会保留自定义检索/重排。
#     reranked_hits = rerank_chunks(question, vector_hits, top_k=top_k)
#
#     # -------------------------------------------------------------------------
#     # Step 4：RetrievedChunk -> LangChain Document
#     # -------------------------------------------------------------------------
#     # 这是 LangChain 版和手写版的关键分界线。
#     # 从这里开始，我们把项目自己的 chunk 转成 LangChain 标准 Document。
#     documents = chunks_to_documents(reranked_hits)
#
#     # -------------------------------------------------------------------------
#     # Step 5：Document -> context 文本
#     # -------------------------------------------------------------------------
#     # 模型最终还是读文本，所以需要把 Document 格式化成 context。
#     # 这一步类似你原来的 build_context()。
#     context = format_documents_as_context(documents)
#     # -------------------------------------------------------------------------
#     # Step 5：提前整理“返回前端要用的数据”
#     # -------------------------------------------------------------------------
#     # 这里先把检索结果整理成两份结构：
#     #
#     # 1. citations
#     #    - 给前端展示“答案引用了哪些文档”
#     #    - 一般包含 document_name、page、section、score、content 摘要等
#     #
#     # 2. retrieved_chunk_payloads
#     #    - 给前端展示“检索到了哪些 chunk / 调试信息”
#     #    - 比 citations 更偏底层调试信息
#     #    - 一般包含 vector_score、keyword_score、final_score 等
#     #
#     # 为什么这里要提前准备？
#     # - 因为后面无论模型是否真正开始流式输出，这两份数据都已经确定了
#     # - 严格模式下如果没有 context，模型甚至不会被调用
#     # - 但前端依然可能需要知道：这次检索命中了多少块、有哪些引用来源
#     citations = build_citations_from_documents(documents)
#     retrieved_chunk_payloads = build_retrieved_chunk_payloads(reranked_hits)
#
#     # -------------------------------------------------------------------------
#     # Step 5.1：先向前端发一个“context 已准备好”的事件
#     # -------------------------------------------------------------------------
#     # 这个事件不是必须的，但产品体验会更好：
#     #
#     # 前端可以利用它做这些事：
#     # - 知道后端已经完成了 embedding / retrieval / rerank / context 拼装
#     # - 提前展示“检索到了多少条 chunk”
#     # - 提前展示“有多少条 citations”
#     # - 让用户知道：现在正在进入模型生成阶段，而不是请求卡住了
#     #
#     # 这很像很多市面产品里的“已找到 5 条相关内容，正在生成答案...”。
#     yield {
#         "event": "context_ready",
#         "data": {
#             # 检索并精排后，最终送入回答链路的 chunk 数量
#             "retrieved_chunk_count": len(retrieved_chunk_payloads),
#
#             # 前端可展示的引用来源数量
#             "citation_count": len(citations),
#
#             # 拼出来的 context 文本长度
#             # 这个值主要用于调试，帮助判断 context 是否过长
#             "context_length": len(context),
#
#             # query embedding 的维度，常用于调试 / 验证 embedding 模型是否一致
#             "query_embedding_dim": len(query_embedding),
#         },
#     }
#
#     # -------------------------------------------------------------------------
#     # Step 6：决定是否真的调用模型
#     # -------------------------------------------------------------------------
#     # 这里延续你原来手写版 RAG 的 strict_mode 策略：
#     #
#     # strict_mode = True 时：
#     # - 如果没有检索到任何 context
#     # - 那就不要调用模型
#     # - 直接返回“知识库中没有找到相关内容”
#     #
#     # 这样做的目的：
#     # - 避免模型在没有知识库依据时自由发挥
#     # - 降低幻觉（hallucination）
#     if not context and strict_mode:
#         # 这里直接给一个固定回答，不进入 LLM
#         answer_text = "知识库中没有找到相关内容。请尝试调整提问方式，或缩小/更换文档范围后再试。"
#
#         # 虽然没有命中 context，但这里仍然走一次“引用兜底”逻辑
#         # 目的：
#         # - 如果 documents 不为空，最终答案里最好还是能看到来源
#         # - 如果 documents 为空，这个函数会安全地直接返回原 answer_text
#         answer_text = ensure_answer_has_document_citations(answer_text, documents)
#
#         # 由于没有进入模型生成阶段，这里不会有 delta 流
#         # 直接把最终结果通过 done 事件一次性返回给前端
#         yield {
#             "event": "done",
#             "data": {
#                 # 最终回答文本
#                 "answer": answer_text,
#
#                 # 当前这次问答是否处于严格模式
#                 "strict_mode": strict_mode,
#
#                 # 返回给前端展示的引用来源
#                 "citations": citations,
#
#                 # 返回给前端展示的检索片段 / 调试信息
#                 "retrieved_chunks": retrieved_chunk_payloads,
#
#                 # 给调试使用的 context 原文
#                 "context": context,
#
#                 # query embedding 的维度
#                 "query_embedding_dim": len(query_embedding),
#             },
#         }
#         return
#
#     # -------------------------------------------------------------------------
#     # Step 7：开始构建真正要送给模型的 Prompt
#     # -------------------------------------------------------------------------
#     # 走到这里，说明两种情况之一成立：
#     #
#     # 1. 有 context
#     #    -> 正常基于知识库生成回答
#     #
#     # 2. strict_mode = False
#     #    -> 即使没有 context，也允许模型给出谨慎补充
#     #
#     # 先根据“有没有 context + strict_mode”生成回答要求
#     answer_instruction = build_answer_instruction(context, strict_mode)
#
#     # 构建 LangChain Prompt 模板
#     # 这一步对应你原来手写版的 build_rag_messages()
#     prompt = build_langchain_rag_prompt(strict_mode)
#
#     # prompt.invoke(...) 的作用：
#     # - 把 question / context / answer_instruction 三个变量填进模板
#     # - 得到最终的 PromptValue
#     #
#     # 注意：
#     # 这里虽然用了 LangChain 的 Prompt 抽象
#     # 但底层模型调用仍然走你原来的 OpenAI 兼容客户端
#     prompt_value = prompt.invoke(
#         {
#             "question": question,
#             "context": context or "未检索到相关知识库内容。",
#             "answer_instruction": answer_instruction,
#         }
#     )
#
#     # 把 LangChain messages 转成 OpenAI SDK 需要的 messages 格式
#     #
#     # 为什么要转？
#     # - LangChain 的 Prompt 输出是 LangChain 自己的消息对象
#     # - 但你当前项目里调用模型用的是 AsyncOpenAI client
#     # - 所以这里要做一层适配
#     openai_messages = _langchain_messages_to_openai_messages(prompt_value.to_messages())
#
#     # -------------------------------------------------------------------------
#     # Step 8：真正发起“流式”模型调用
#     # -------------------------------------------------------------------------
#     # stream=True 是关键：
#     # - 不再等模型一次性返回完整回答
#     # - 而是边生成边返回 token / 文本片段
#     #
#     # 这也是为什么这版更接近市面产品体验：
#     # - 前端可以边收边展示
#     # - 用户会感觉系统“正在思考并输出”
#     stream = await client.chat.completions.create(
#         model=get_default_model(),
#         messages=openai_messages,
#         temperature=get_default_temperature(),
#         stream=True,
#     )
#
#     # 用一个列表把所有 delta 片段累积起来
#     #
#     # 为什么不用 answer_text += delta？
#     # - 字符串反复拼接效率较低
#     # - list append 最后 join 是更常见、更稳妥的写法
#     answer_parts: list[str] = []
#
#     # -------------------------------------------------------------------------
#     # Step 9：持续消费模型返回的流式结果
#     # -------------------------------------------------------------------------
#     # async for chunk in stream:
#     # - 每次循环拿到模型输出的一小段结果
#     # - 这些小段结果就是前端看到“逐字出现”的来源
#     async for chunk in stream:
#         # 防御性处理：
#         # 某些 chunk 可能没有 choices，直接跳过
#         if not chunk.choices:
#             continue
#
#         # OpenAI 流式输出里，真正新增的文本通常在 delta.content 里
#         # 如果这一帧没有文本内容，就跳过
#         delta = chunk.choices[0].delta.content or ""
#         if not delta:
#             continue
#
#         # 把本次新增文本保存起来，后面要拼成完整答案
#         answer_parts.append(delta)
#
#         # 把本次新增片段通过 SSE 发送给前端
#         #
#         # 前端拿到后通常会：
#         # - assistantText += delta
#         # - 实时更新消息气泡内容
#         yield {
#             "event": "delta",
#             "data": {"content": delta},
#         }
#
#     # -------------------------------------------------------------------------
#     # Step 10：流式输出结束后，拼出完整答案
#     # -------------------------------------------------------------------------
#     # 模型全部输出完成后，把所有 delta 合并成最终完整 answer
#     answer_text = "".join(answer_parts).strip()
#
#     # 再做一次“引用兜底”
#     #
#     # 原因：
#     # - Prompt 虽然要求模型输出 [1][2]
#     # - 但模型不一定总能严格遵守
#     # - 所以这里统一后处理，保证最终答案里尽量能看到来源
#     answer_text = ensure_answer_has_document_citations(answer_text, documents)
#
#     # -------------------------------------------------------------------------
#     # Step 11：通过 done 事件把最终完整结果返回给前端
#     # -------------------------------------------------------------------------
#     # 前端收到 done 后，通常会做这些事：
#     # - 停止“流式加载中”状态
#     # - 用最终 answer 替换草稿消息
#     # - 挂上 citations
#     # - 挂上 retrieved_chunks
#     # - 记录 run_id / strict_mode
#     yield {
#         "event": "done",
#         "data": {
#             # 最终完整答案
#             "answer": answer_text,
#
#             # 当前是否严格模式
#             "strict_mode": strict_mode,
#
#             # 引用来源列表
#             "citations": citations,
#
#             # 检索结果 / 调试片段
#             "retrieved_chunks": retrieved_chunk_payloads,
#
#             # 本次实际送给模型的 context
#             "context": context,
#
#             # query embedding 维度
#             "query_embedding_dim": len(query_embedding),
#         },
#     }