# 02Agent 项目代码结构梳理 - Service 层详解（增强版）

> 生成日期：2026-08-05
>
> 本文以当前 E:/02agent/core/service/ 源码为准。目标不是只解释文件名，而是说明每个函数的输入、输出、调用顺序、数据库字段、异常降级和调试方法。

---

## 阅读说明

这里的 service 是 Python 模块目录，不是微服务进程。各层职责如下：

    api/routes/        参数校验、权限、HTTP/SSE 响应
    core/service/      解析、切块、模型调用、检索、回答、轨迹
    core/db/models.py  ORM 数据模型
    core/config.py     全局配置

当前 core/service 的 12 个源码文件：

| 文件 | 作用 | 阶段 |
|---|---|---|
| llm.py | 创建 OpenAI 兼容客户端、读取聊天模型配置 | 基础设施 |
| embedding.py | 调用 embedding API，将文本变成向量 | 入库/检索 |
| document_parser.py | 读取 TXT、MD、PDF、DOCX、XLS/XLSX、PPTX | 入库 |
| hierarchical_chunking.py | 生成 parent/leaf 两层 chunk | 入库 |
| vector_index.py | 构建和搜索每个用户的 FAISS 索引 | 入库/检索 |
| retrieval.py | 向量、BM25、混合检索、精排、parent 扩展 | 检索 |
| rag_grounding.py | 问题理解、证据匹配、规则直答 | 检索/回答 |
| query_rewrite.py | 生成多个带权问题变体 | 检索 |
| langchain_adapters.py | 包装成 LangChain 标准接口 | 适配 |
| rag_langchain_native.py | 编排检索、上下文、Prompt、流式回答 | 回答 |
| rag_trace.py | 记录 RAG 的运行/步骤轨迹 | 观测 |
| run_trace.py | 记录普通聊天的运行/步骤轨迹 | 观测 |

---

## 一、两条主链路

### 1. 文档上传链路

    knowledge.py
      -> ProjectDocumentLoader.lazy_load
      -> document_parser.parse_document
      -> hierarchical_chunking.build_hierarchical_chunks
      -> ProjectEmbeddings.aembed_documents
      -> embedding.embed_texts
      -> 写入 KnowledgeChunks
      -> vector_index.rebuild_user_faiss_index

解析结果统一为 full_text/pages/sections/metadata；切块结果是 parent/leaf；只有 leaf 做 embedding 和 FAISS 索引。

### 2. RAG 问答链路

    rag_langchain_native.stream_answer_with_knowledge_langchain_native
      -> ProjectKnowledgeRetriever.aretrieve_documents
         -> ProjectEmbeddings.aembed_query
         -> embedding.embed_text
         -> retrieval.search_similar_chunks
            -> FAISS 或数据库暴力向量召回
            -> BM25 关键词召回
            -> 混合分数
            -> leaf 扩展 parent
         -> retrieval.rerank_chunks
      -> RetrievedChunk 转 LangChain Document
      -> context_ready
      -> strict 无上下文/规则 grounding 直接 done
      -> Prompt -> ChatOpenAI -> StrOutputParser
      -> delta ... delta -> done

### 3. parent/leaf 先记住这句话

    leaf 用来找得准，parent 用来答得完整。

leaf 是小块检索单元，保存 retrieval_content 和 embedding；parent 是完整上下文块，不直接进 FAISS，命中 leaf 后通过 parent_chunk_id 回查。

---

## 二、基础能力层

## 1. llm.py：模型客户端工厂

文件路径：core/service/llm.py

依赖 AsyncOpenAI 和 core.config.settings。它不读数据库、不写 prompt、不直接生成答案。

### get_llm_client() -> AsyncOpenAI

实际创建：

    AsyncOpenAI(
        api_key=settings.OPENAI_API_KEY,
        base_url=settings.OPENAI_BASE_URL,
    )

输入没有显式参数，配置来自 settings；输出是异步 OpenAI 兼容客户端。embedding.py 用它调用 embeddings，普通聊天路由用它调用 chat completions，RAG service 用同一配置创建 LangChain ChatOpenAI。

它是客户端工厂，不是 singleton。真正的网络请求发生在调用 embeddings.create 或聊天接口时。

### get_default_model() -> str

返回 settings.LLM_MODEL，只代表聊天模型。embedding 模型由 embedding.get_embedding_model() 单独读取。

### get_default_temperature() -> float

返回 settings.LLM_TEMPERATURE，只影响回答生成的随机性，不影响向量检索。

---

## 2. embedding.py：文本向量化

文件路径：core/service/embedding.py

调用关系：

    embedding.py
      -> settings.EMBEDDING_MODEL
      -> llm.get_llm_client()
      -> AsyncOpenAI.embeddings.create()

### get_embedding_model() -> str

读取 settings.EMBEDDING_MODEL。聊天模型输出文字，embedding 模型输出数字数组，二者不能混用。

### embed_text(text, client=None) -> list[float]

步骤：

1. (text or "").strip() 清理输入。
2. 空文本直接返回 []，避免远程 API 报错。
3. 未传 client 时调用 get_llm_client()。
4. 调用 client.embeddings.create(model=get_embedding_model(), input=text)。
5. 读取第一个 embedding，并转成普通 float 列表。

### embed_texts(texts, client=None) -> list[list[float]]

批量版本用于文档入库。输入和输出必须按顺序对应。输入空列表返回 []；非空时一次调用批量 embedding API。

### 边界

- 空文本的 [] 不是合法向量，入库路由要检查 leaf 数量和向量数量一致。
- API/网络异常会向上抛，不在这里吞掉。
- 向量维度由模型决定，vector_index.py 建索引时会检查一致性。

---

## 三、document_parser.py：多格式解析

文件路径：core/service/document_parser.py

统一返回：

    {
        "full_text": str,
        "pages": list[dict],
        "sections": list[dict],
        "metadata": dict,
    }

full_text 给切块使用；pages/sections 给来源引用和 parent 边界；metadata 存解析器信息。

### 函数表

| 函数 | 真实职责 |
|---|---|
| normalize_text | 统一换行、行尾空格、连续空行 |
| _sheet_cell_to_text | Excel 单元格转安全字符串 |
| parse_txt | 读取纯文本全文 |
| parse_md | 读取 Markdown 并提取章节 |
| parse_pdf | 提取 PDF 页面文本，保留页码 |
| parse_docx | 提取 Word 段落、标题和表格 |
| parse_xlsx | 读取新版 Excel worksheet |
| parse_xls | 读取旧版 Excel worksheet |
| parse_pptx | 按幻灯片提取文本 |
| _flush_markdown_section | 保存 Markdown 当前章节 |
| _extract_markdown_sections | 按标题扫描 Markdown sections |
| parse_document | 按 file_type 分派统一入口 |

### parse_document(file_path, file_type) -> dict

上层应直接使用它：

    pdf  -> parse_pdf
    docx -> parse_docx
    xlsx -> parse_xlsx
    xls  -> parse_xls
    pptx -> parse_pptx
    md   -> parse_md
    txt  -> parse_txt

这个文件只负责把文件读成结构化文本，不负责 embedding、数据库和 FAISS。

---

## 四、hierarchical_chunking.py：parent/leaf 分层切块

文件路径：core/service/hierarchical_chunking.py

### 内部函数表

| 函数 | 作用 |
|---|---|
| _normalize_text | 统一内部文本 |
| _validate_chunk_args | 校验 chunk_size/overlap |
| _split_paragraphs | 按空行切自然段 |
| _split_sentences | 按中英文标点切句 |
| _split_long_unit | 长段落/句子的硬切兜底 |
| _tail_overlap_text | 取上块尾部做 overlap |
| _semantic_text_chunks | 正文切块主算法 |
| _looks_like_markdown_table_line | 识别 Markdown 表格行 |
| _split_markdown_section_blocks | 分正文和表格 block |
| _build_parent_segments | 构造 parent 边界 |
| _build_retrieval_content | 加父标题/内容类型前缀 |
| _safe_find_from | 计算原文 offset |
| _chunk_table_text | 按表格行范围切分 |
| build_hierarchical_chunks | 串联全部步骤 |

正文优先按段落，再按句子，再贪心装箱；过长句子最后才按字符硬切。overlap 用来保护跨边界语义，不是错误重复。

表格单独按行切，尽量保留表头，记录 table_row_from/table_row_to，并标记 block_type=table。

### build_hierarchical_chunks(parsed, file_type, chunk_size=500, overlap=100)

真实步骤：

1. 校验 size/overlap。
2. 清洗 parsed.full_text，空文本返回 []。
3. _build_parent_segments 构造 parent。
4. 分配 local_parent_key=parent_N。
5. 计算 parent 的 start/end_offset。
6. 先输出 parent item。
7. text parent 调 _semantic_text_chunks。
8. table parent 调 _chunk_table_text。
9. 给 leaf 写 retrieval_content、来源、offset、child_index。
10. 返回扁平 parent/leaf 列表。

关键字段：

    local_parent_key       内存阶段父子键
    chunk_role             parent 或 leaf
    chunk_index            parent/leaf 统一顺序
    parent_chunk_id        入库前 None，入库后为真实 parent id
    parent_title           父主题
    block_type             text 或 table
    child_index            leaf 在 parent 内的序号
    content                展示/上下文文本
    retrieval_content      embedding/BM25 增强文本
    source_page/section    来源
    start/end_offset       原文位置
    table_row_from/to      表格行范围


