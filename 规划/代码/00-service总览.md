# Service 代码总览

本文按当前代码实际调用关系梳理 `core/service` 和 `frontend/src/shared/services`。可以先记住一句话：`service` 不是一个单独的“业务”，而是把解析、切块、向量化、检索、回答和执行记录这些可复用能力从 API 路由中拆出来。

## 一、先看整体结构

```text
知识库上传
  api/routes/knowledge.py
    -> langchain_adapters.ProjectDocumentLoader
      -> document_parser.parse_document
    -> hierarchical_chunking.build_hierarchical_chunks
    -> langchain_adapters.ProjectEmbeddings
      -> embedding.embed_texts
    -> KnowledgeChunks(parent + leaf)
    -> vector_index.rebuild_user_faiss_index

用户提问
  api/routes/rag_langchain_native.py
    -> rag_langchain_native.stream_answer_with_knowledge_langchain_native
      -> ProjectKnowledgeRetriever
        -> embedding.embed_text
        -> retrieval.search_similar_chunks
          -> query_rewrite / rag_grounding
          -> FAISS 或数据库暴力检索
          -> BM25 + 向量混合
          -> leaf 扩展为 parent
      -> LangChain chain.astream
      -> 引用、SSE 事件、RAG trace

普通聊天
  api/routes/session.py
    -> llm.get_llm_client
    -> run_trace.create_run/create_step
    -> OpenAI-compatible Chat Completions 流式调用
    -> run_trace.complete/fail*

前端
  App.vue
    -> shared/services/useApiClient.js
    -> fetch + Authorization + JSON 错误解析
```

## 二、最重要的 parent / leaf 概念

- `parent`：较大的上下文块，不直接做 embedding，命中子块后返回给 LLM，目的是让回答看到完整上下文。
- `leaf`：较小的检索单元，保存 `retrieval_content` 和 embedding，真正进入 FAISS/BM25 检索。
- 入库时先写 parent，再写 leaf，通过 `parent_chunk_id` 建立关系。
- 检索时先找 leaf，再按 `parent_chunk_id` 扩展回 parent，这就是 Small-to-Big。

## 三、各 service 的定位

| 文件 | 解决的问题 | 主要被谁调用 |
|---|---|---|
| `document_parser.py` | PDF、DOCX、Excel、PPTX、Markdown、TXT 统一解析 | `ProjectDocumentLoader`、知识库路由 |
| `hierarchical_chunking.py` | 将解析结果切成 parent/leaf，并保留来源位置 | 知识库路由、`ProjectDocumentLoader` |
| `embedding.py` | 调用 OpenAI 兼容 embedding 接口 | `ProjectEmbeddings`、检索入口 |
| `llm.py` | 创建 LLM 客户端、读取模型配置 | 普通聊天、LangChain RAG、embedding |
| `vector_index.py` | 每个用户的 FAISS 索引重建和搜索 | 知识库路由、`retrieval.py` |
| `retrieval.py` | 召回、BM25/向量融合、重排、parent 扩展 | `ProjectKnowledgeRetriever` |
| `rag_grounding.py` | 理解问题意图、证据匹配、无模型直接回答 | `query_rewrite.py`、RAG 检索 |
| `query_rewrite.py` | 为一个问题生成多个带权改写形式 | `retrieval.py` |
| `langchain_adapters.py` | 把本项目能力接入 LangChain 标准接口 | LangChain 原生 RAG |
| `rag_langchain_native.py` | 组装 LangChain RAG chain、上下文、引用和流式回答 | RAG API 路由 |
| `run_trace.py` | 普通聊天的 Run/RunStep 执行记录 | `api/routes/session.py` |
| `rag_trace.py` | RAG 专用 RagRuns/RagRunSteps 执行记录 | `api/routes/rag_langchain_native.py` |
| `useApiClient.js` | 前端统一请求、鉴权和 API 错误处理 | `frontend/src/App.vue` |

## 四、推荐阅读顺序

1. 先看本文，理解 parent/leaf 和两条主流程。
2. 看 `llm.py`、`embedding.py`、`document_parser.py`，理解最底层能力。
3. 看 `hierarchical_chunking.py`、`vector_index.py`，理解知识如何入库和建立索引。
4. 看 `retrieval.py`，重点只先看 `search_similar_chunks`、`hybrid_search`、`rerank_chunks`。
5. 看 `langchain_adapters.py` 和 `rag_langchain_native.py`，理解这些能力如何被 LangChain 串起来。
6. 最后看两个 trace 文件和 API 路由，理解一次请求如何被记录。

## 五、当前代码中容易混淆的点

- `run_trace.py` 和 `rag_trace.py` 不是重复文件：前者记录普通 Agent 聊天，后者记录知识库 RAG。
- `rag_grounding.py` 不是最终的 LLM：它负责问题理解、证据匹配和严格模式下的直接证据回答；正常 RAG 仍由 LangChain 调用模型。
- `langchain_adapters.py` 不是新的解析/检索实现，而是适配层，复用本项目已有 parser、chunking、embedding、retrieval。
- `threshold`、`rerank` 等参数在不同层的含义不能只看名字；最终检索应以 `search_similar_chunks` 及其内部调用为准。
- FAISS 只保存 leaf 的索引位置和元数据，完整文本仍在数据库 `KnowledgeChunks` 中。

