# 02Agent 项目代码结构梳理 - Service层详解

> 生成日期：2026-08-05
> 本文档详细梳理 core/service/ 目录下每个服务文件的作用、核心函数、数据流和调用关系。

---

## 一、整体架构概览

### 1.1 项目分层结构

项目根目录 E:/02agent/
├── api/                          # API层（FastAPI路由）
│   ├── main.py                   # FastAPI应用入口
│   ├── deps.py                   # 依赖注入
│   ├── routes/                   # 路由定义
│   │   ├── auth.py               # 认证
│   │   ├── agents.py             # Agent管理
│   │   ├── session.py            # 会话
│   │   ├── runs.py               # 运行记录
│   │   ├── knowledge.py          # 知识库管理
│   │   ├── rag.py                # RAG问答（旧版）
│   │   ├── rag_langchain_native.py # RAG问答（LangChain版）
│   │   └── health.py             # 健康检查
│   └── schemas/                  # Pydantic请求/响应模型
├── core/                         # 核心业务逻辑
│   ├── config.py                 # 全局配置
│   ├── security.py               # 安全（JWT、密码哈希）
│   ├── exceptions.py           # 自定义异常
│   ├── db/                       # 数据库层
│   └── service/                  # ★ 服务层（本文重点）
├── test/                         # 测试用例
├── frontend/                     # Vue前端
└── 规划/                         # 学习规划文档

### 1.2 RAG完整数据流

用户上传文档                        用户提问
    │                                  │
    ▼                                  ▼
document_parser.py            query_rewrite.py
  (解析文件→文本)             (问题理解+改写)
    │                                  │
    ▼                                  ▼
hierarchical_chunking.py       rag_grounding.py
  (文本→分层切块)              (关键词提取+证据打分)
    │                                  │
    ▼                                  ▼
embedding.py                  retrieval.py
  (文本块→向量)               (向量+BM25混合检索+重排)
    │                                  │
    ▼                                  ▼
vector_index.py               langchain_adapters.py
  (FAISS索引构建/搜索)       (转成LangChain标准格式)
    │                                  │
    ▼                                  ▼
(入库保存)                  rag_langchain_native.py
                                 (组装Prompt→LLM生成答案)
                                         │
                                         ▼
                                   前端展示引用

---

## 二、Service层文件逐个详解

---

### 📄 1. llm.py —— 大语言模型基础配置

文件路径：core/service/llm.py

核心作用：提供统一的 LLM 客户端获取入口，封装配置读取。这是所有需要调用 OpenAI 兼容 API 的模块的基础。

核心函数：
==========

| 函数名 | 作用 | 返回值 |
|--------|------|--------|
| get_llm_client() | 创建并返回 AsyncOpenAI 客户端实例，读取配置中的 API_KEY 和 BASE_URL | AsyncOpenAI |
| get_default_model() | 获取默认聊天模型名称（如 gpt-4o-mini） | str |
| get_default_temperature() | 获取默认采样温度（控制创造性，0~1） | float |

被谁调用：
- embedding.py —— 做向量嵌入时复用同一个 client
- rag_langchain_native.py —— 创建 LangChain 的 ChatOpenAI 实例

---

### 📄 2. embedding.py —— 文本向量化服务

文件路径：core/service/embedding.py

核心作用：把文本（字符串）转换成高维向量（浮点数数组），用于后续的语义相似度计算。

核心函数：

| 函数名 | 作用 | 参数 | 返回值 |
|--------|------|------|--------|
| get_embedding_model() | 获取 Embedding 专用模型名（和聊天模型分开配置） | 无 | str |
| embed_text(text, client) | 单条文本转向量 | text: 待转向量的文本 | list[float] 向量数组，空文本返回 []
| embed_texts(texts, client) | 批量文本转向量 | texts: 文本列表 | list[list[float]] 批量向量 |

关键处理逻辑：
1. 空字符串保护：调用 API 前先 strip()，空文本直接返回空数组，避免 API 报错
2. 客户端复用：支持传入已有 client，不传时内部调用 get_llm_client() 创建
3. 批量优化：embed_texts() 一次 API 调用处理多条，比循环调用 embed_text() 高效得多

调用链路：
文档入库时：hierarchical_chunking → chunk文本 → embed_texts → 存入数据库
用户检索时：用户问题 → embed_text → 向量 → FAISS搜索

---

### 📄 3. document_parser.py —— 多格式文档解析器

文件路径：core/service/document_parser.py

核心作用：把用户上传的各种格式文件（PDF/Word/Excel/PPT/Markdown/纯文本）解析成统一的结构化数据，保留页码、章节等来源信息。

统一返回格式（所有 parse_* 函数都返回这个结构）：
{
    "full_text": str,      # 完整的纯文本内容（拼接后的）
    "pages": list[dict],   # 逐页内容，每页: {"page": 1, "text": "...", "section": "page_1"}
    "sections": list[dict],# 逐章节内容，每节: {"section": "标题", "text": "..."}
    "metadata": dict,      # 额外信息: 解析器类型、页数、章节数等
}

核心函数：

| 函数名 | 支持格式 | 特点 |
|--------|----------|------|
| normalize_text(text) | 所有 | 文本清洗：去行尾空白 + 压缩连续空行 |
| parse_txt(file_path) | .txt | 最简单，直接读 UTF-8 文本 |
| parse_md(file_path) | .md | 提取 Markdown 标题层级作为 sections，后续 chunking 可利用 |
| parse_pdf(file_path) | .pdf | 保留逐页信息（pages 非空），后续引用可显示"第几页" |
| parse_docx(file_path) | .docx | 识别 Word 的 Heading 样式作为章节分隔 |
| parse_xlsx(file_path) | .xlsx | 按工作表+行解析，保留 sheet 名 |
| parse_xls(file_path) | .xls | 老版 Excel，用 xlrd 库 |
| parse_pptx(file_path) | .pptx | 按幻灯片逐页提取 |
| parse_document(file_path, file_type) | 所有 | 统一入口函数，根据后缀分发到具体解析器 |

---

### 📄 4. hierarchical_chunking.py —— 分层语义切块

文件路径：core/service/hierarchical_chunking.py

核心作用：把解析后的长文本切成适合向量化和检索的"小块（chunk）"。采用分层策略，不是简单按字符硬切。

切块策略层级（从优到劣兜底）：
第1层：按段落边界切（自然段）
    ↓ 段落仍太长？
第2层：按句子边界切（。！？；）
    ↓ 单句仍太长？
第3层：按字符硬切（最终兜底）

核心常量：
| 常量名 | 值 | 含义 |
|--------|-----|------|
| MIN_TEXT_CHUNK_CHARS | 120 | 最小块字符数，避免切出太碎的块 |
| MAX_TABLE_ROWS_PER_CHUNK | 12 | 表格块最多包含的行数 |

核心函数：

| 函数名 | 作用 |
|--------|------|
| _split_paragraphs(text) | 按空行切分成段落列表 |
| _split_sentences(text) | 按中英文标点切分成句子列表（逐字符扫描） |
| _split_long_unit(unit, chunk_size) | 长段落兜底切分：先句子→贪心装箱→还长就字符切 |
| _tail_overlap_text(text, overlap) | 生成重叠文本，优先按句子从尾部截取，不是粗暴截字符 |
| _semantic_text_chunks(text, chunk_size, overlap) | 正文切分主逻辑：段落→贪心装箱→加重叠 |
| build_hierarchical_chunks(parsed_doc, ...) | 对外主入口：输入解析后的文档，输出父子层级的 chunks |

父子块（Parent-Child Chunk）概念：
┌─────────────────────────────────────┐
│  Parent Chunk（大块，约1500字符）    │  ← 用于给LLM做上下文，内容完整
│  ┌───────┐ ┌───────┐ ┌──────────┐  │
│  │ Leaf1 │ │ Leaf2 │ │  Leaf3   │  │  ← 这些做向量索引，用于精确检索
│  └───────┘ └───────┘ └──────────┘  │
└─────────────────────────────────────┘

检索时：先命中 Leaf → 找到对应的 Parent → 把 Parent 内容喂给 LLM
好处：检索精确（小块）+ 回答有上下文（大块）

---

### 📄 5. vector_index.py —— FAISS 向量索引服务

文件路径：core/service/vector_index.py

核心作用：基于 Facebook 的 FAISS 库，构建高效的向量相似度索引，支持百万级向量的毫秒级检索。

存储位置：tmp/faiss_indexes/user_{id}.faiss + user_{id}.json

核心数据类：
@dataclass(frozen=True)  # 不可变
class FaissSearchHit:
    row_id: int        # FAISS内部行号
    chunk_id: int      # 对应数据库 KnowledgeChunks.id
    document_id: int   # 所属文档ID
    score: float       # 相似度分数（内积，越大越相似，范围[-1,1]

核心函数：

| 函数名 | 作用 | 关键细节 |
|--------|------|----------|
| faiss_available() | 检查 FAISS + NumPy 是否已安装 | |
| rebuild_user_faiss_index(db, user_id) | 重建用户的整个向量索引 | 从 DB 查所有 leaf chunk 的 embedding → 组装矩阵 → L2归一化 → 建 IndexFlatIP → 写入文件 |
| search_user_faiss_index(db, user_id, query_embedding, top_k) | 搜索Top-K 最相似的 chunk | 加载已有索引 → 搜索 → 根据元数据映射回 chunk_id |
| ensure_faiss_index(user_id, db) | 确保索引存在，不存在则重建 | 避免首次搜索时报错 |
| delete_user_faiss_index(user_id) | 删除用户的索引文件 | 清理用 |

技术要点：
1. 索引类型：IndexFlatIP（内积），配合 L2 归一化后等价于余弦相似度
2. 写入安全：先写 .tmp 临时文件，成功后 rename 替换原文件，避免中途崩溃损坏
3. 用户隔离：每个用户独立一份索引文件，避免跨用户数据泄露
4. 只索引 Leaf Chunk：Parent Chunk 不进向量库

---

### 📄 6. retrieval.py —— 混合检索与重排序

文件路径：core/service/retrieval.py

核心作用：RAG 的"检索中间层"。输入用户问题 → 多路召回（向量+关键词）→ 融合打分 → 重排 → 返回高质量候选块。

核心数据类 RetrievedChunk（非常重要，贯穿全链路）：

RetrievedChunk 字段分组：
├── 一、核心标识字段
│   ├── document_id       文档ID
│   ├── document_name     文档名
│   ├── chunk_id          块ID
│   ├── chunk_index       块在文档中的序号
│   ├── content           块的实际文本
│   ├── source_page       来源页码（PDF有）
│   └── source_section    来源章节
├── 二、检索辅助字段
│   ├── embedding_json    向量（JSON字符串存库）
│   └── retrieval_content 检索用文本（可能与content不同）
├── 三、层级结构字段
│   ├── chunk_role        LEAF / PARENT
│   ├── parent_chunk_id   父块ID
│   ├── parent_title      父块标题
│   ├── block_type        text/table
│   └── child_index       在父块中的子序号
├── 四、评分字段（多路召回融合）
│   ├── vector_score      向量检索分
│   ├── keyword_score     关键词检索分
│   └── final_score       最终融合分
└── 五、临时字段（仅检索阶段）
    └── matched_child_content  记录命中的子块原文，重排时保留精确信号

核心函数：

| 函数名 | 作用 | 算法细节 |
|--------|------|----------|
| cosine_similarity(a, b) | 纯Python实现余弦相似度 | 点积 / (||a|| × ||b||) |
| tokenize(text) | 分词，生成用于匹配的 token 集合 | 英文数字按单词，中文做 2~4 gram |
| bm25_search(db, user_id, query_text, top_k, ...) | BM25 关键词检索 | Okapi BM25 经典公式：TF饱和度(k1=1.5) + 文档长度归一化(b=0.75) + IDF |
| search_similar_chunks(db, user_id, question, ...) | 主检索入口（向量+BM25混合） | 1.问题转向量 → FAISS召回 2.问题分词 → BM25召回 3.两路人马归一化 → 加权融合 → 重排 |
| rerank_chunks(chunks, question, ...) | 重排序（Rerank） | 关键词覆盖度 + 证据匹配分 + 关系证据分 + 父子块合并逻辑 |

检索流程详解：
用户问题: "扫地机器人能不能连5G WiFi？"
    │
    ├─→ 1. 向量召回（FAISS）: 找语义最像的 Top-K 个 chunk
    │      vector_score ∈ [0, 1]
    │
    ├─→ 2. BM25关键词召回: 找包含查询词的 chunk
    │      keyword_score 基于词频/逆文档频率
    │
    └─→ 3. 融合 + Rerank
           a) 归一化两路分数（除以各自最大值）
           b) final_score = w1*vector_score + w2*keyword_score
           c) 证据匹配加分: chunk中是否真的包含焦点词和关系词
           d) 父子块合并: Leaf命中 → 展开Parent，保留Leaf命中信号
           e) 去重 + 按 final_score 降序
              ↓
        返回 Top-N 个高质量 RetrievedChunk

---

### 📄 7. rag_grounding.py —— 知识接地与证据判定

文件路径：core/service/rag_grounding.py

核心作用：RAG 的"裁判模块"。判断知识库内容能不能、够不够回答用户问题，避免模型胡编乱造（幻觉）。

问题类型分类：

| 类型 | 关键词示例 | 典型问题 |
|------|-----------|----------|
| yes_no | 是否/能否/支持/兼容 + 吗？ | "扫地机器人支持5G WiFi吗？" |
| frequency | 多久/几次/频率 | "滤网多久清理一次？" |
| how_to | 如何/怎么/怎样 | "怎么连接蓝牙？" |
| list | 哪些/有什么 | "有哪些清洁模式？" |
| fact | （其他） | "水箱容量多大？" |

核心数据类 QueryIntent（结构化查询理解）：
@dataclass
class QueryIntent:
    question_type: str        # 上述5种之一
    subject_terms: list[str]  # 主体词，如 ["扫地机器人"]
    object_terms: list[str]   # 客体词，如 ["5G WiFi"]
    relation: str             # 关系词，如 "连接" / "支持"
    normalized_query: str     # 归一化后的标准问法
    focus_terms: list[str]    # 所有焦点关键词

核心函数：

| 函数名 | 作用 |
|--------|------|
| infer_question_type(question) | 根据关键词识别问题类型 |
| extract_question_focus_terms(question) | 提取查询焦点关键词（剥掉疑问词/产品前缀/语气词，露出真正关心的实体 |
| understand_query(question) | 结构化查询理解主函数，返回 QueryIntent |
| evidence_match_score(question, context) | 证据匹配分：焦点词在 chunk 中出现的覆盖率 + 强度 |
| relation_evidence_score(intent, context) | 关系证据分：不仅看主体有没有，还要看"关系词"有没有匹配（避免答非所问） |
| build_direct_grounded_answer(question, chunks, ...) | 规则级直接回答：证据极强时，不调 LLM，直接用规则拼出答案，又快又准又无幻觉 |

GROUNDING_INSTRUCTION 常量：
给 LLM 的回答铁律："如果知识库上下文已经提供能回答问题的证据，必须基于该证据直接回答；列表、枚举、频率、步骤和参数都算有效证据。只有在上下文没有相关证据时，才能回答'知识库未提及'。"

---

### 📄 8. query_rewrite.py —— 查询改写（Query Rewrite）

文件路径：core/service/query_rewrite.py

核心作用：把用户的口语化问题，改写成多种更适合检索的"标准问法"，提高召回率。

核心数据类：
@dataclass(frozen=True)
class RewriteQuery:
    text: str           # 改写后的查询文本
    weight: float       # 这条改写在召回中的权重（越高越重要）
    strategy: str       # 来自哪种改写策略，用于调试

改写策略矩阵（示例：用户问"我家扫地机器人能不能连5G WiFi？"）：

| strategy | 生成的改写文本 | weight | 思路 |
|----------|---------------|--------|------|
| original | 我家扫地机器人能不能连5G WiFi？ | 1.0 | 保留原问题 |
| normalized_query | 扫地机器人 连接 5G WiFi | 0.96 | 剥掉口语，露出主谓宾 |
| entity_relation | 扫地机器人 连接 5G WiFi | 0.93 | 主体+关系+客体 显式拼接 |
| entity_pair | 扫地机器人 5G WiFi | 0.86 | 去掉关系词，只留实体对 |
| relation_synonym | 扫地机器人 接入 5G WiFi | 0.72 | 关系词换成同义词（接入/联网/配网/绑定） |
| yes_no 类型改写 | 扫地机器人 5G WiFi 支持情况 | 0.62 | 改成文档标题常见写法 |

核心函数：
| 函数名 | 作用 |
|--------|------|
| _build_relation_rewrites(intent) | 基于 QueryIntent 的 subject/relation/object 生成实体关系类改写 |
| _build_question_type_rewrites(intent) | 基于问题类型（yes_no/how_to/list/...）生成文档标题风改写 |
| build_weighted_rewrite_queries(question) | 主入口，串联所有策略，去重，返回带权重的改写列表 |

---

### 📄 9. rag_trace.py —— RAG 运行链路追踪

文件路径：core/service/rag_trace.py

核心作用：把每一次 RAG 问答的全过程记录到数据库，用于调试、审计和前端展示"运行轨迹"。

数据模型（对应 DB 表）：
RagRuns（一次问答 = 一条 Run）
├── id, user_id, question
├── status: RUNNING / COMPLETED / FAILED
├── top_k, strict_mode, document_scope_json
├── answer, error_message
└── started_at, finished_at

RagRunSteps（Run 下的每个步骤）
├── id, rag_run_id
├── step_type: query_rewrite / retrieval / rerank / llm / grounding
├── step_name: 展示用名称
├── status: RUNNING / COMPLETED / FAILED
├── input_payload_json, output_payload_json  ← 步骤的输入输出快照
├── error_message
└── started_at, finished_at

核心函数（成对出现：创建→完成/失败）：

| 函数名 | 作用 |
|--------|------|
| create_rag_run(...) | 问答开始时创建 Run，状态=RUNNING |
| complete_rag_run(run, answer) | 问答成功，状态=COMPLETED，写入 answer |
| fail_rag_run(run, error_message) | 问答失败，状态=FAILED，写入错误信息 |
| create_rag_step(rag_run_id, step_type, step_name, input) | 每个步骤开始前调用 |
| complete_rag_step(step, output) | 步骤成功结束 |
| fail_rag_step(step, error, output) | 步骤失败 |

前端用途：前端的 "Run Trace 面板" 就是读这两张表，把每一步的耗时、输入输出可视化展示出来。

---

### 📄 10. run_trace.py —— Agent 会话运行追踪

文件路径：core/service/run_trace.py

核心作用：和 rag_trace.py 类似，但追踪的是 Agent 会话（普通聊天）的执行过程，不是专门的 RAG 问答。

数据模型：
Runs（一次用户消息 = 一条 Run）
├── id, session_id, agent_id, user_id
├── input_text, output_text
├── status: RUNNING / COMPLETED / FAILED
├── error_message
└── started_at, finished_at

RunSteps（Run 下的每个步骤）
├── id, run_id
├── step_type: receive_input / load_agent / build_messages / llm_call / stream_response / save_message
├── step_name, status
├── input_payload_json, output_payload_json
└── started_at, finished_at

核心函数和 rag_trace.py 完全同构：
- create_run() / complete_run() / fail_run()
- create_step() / complete_step() / fail_step()

---

### 📄 11. langchain_adapters.py —— LangChain 标准接口适配层

文件路径：core/service/langchain_adapters.py

核心作用：把项目自己写的一套"文档解析→切块→向量→检索"能力，套上 LangChain 的标准接口，这样就能无缝接入 LangChain 生态（Chain、LCEL 等）。

实现了 4 个 LangChain 标准基类（面试常考知识点）：

| 类名 | 继承的 LangChain 基类 | 对应概念 | 包装的项目内部能力 |
|------|---------------------|----------|-------------------|
| ProjectDocumentLoader | BaseLoader | Document Loader（文档加载器） | parse_document() 解析文件 → LangChain Document |
| ProjectTextSplitter | TextSplitter | Text Splitter（文本分割器） | build_hierarchical_chunks() 分层切块 → 多个 Document |
| ProjectEmbeddings | Embeddings | Embeddings（嵌入模型） | embed_text() / embed_texts() 转向量 |
| ProjectKnowledgeRetriever | BaseRetriever | Retriever（检索器） | search_similar_chunks() + rerank_chunks() → 返回 Document 列表 |

关键转换函数：
| 函数名 | 作用 |
|--------|------|
| retrieved_chunk_to_langchain_document(chunk) | 核心桥接：项目的 RetrievedChunk → LangChain 的 Document
映射关系：
- content → page_content
- document_id/name/chunk_id/page/score → metadata dict |
| retrieved_chunks_to_langchain_documents(chunks) | 批量转换 |

入库链路（使用适配层）：
上传文件
  → ProjectDocumentLoader.load()
    → parse_document() 解析
  → ProjectTextSplitter.split_documents()
    → build_hierarchical_chunks() 切块
  → ProjectEmbeddings.embed_documents()
    → embed_texts() 做向量
  → 存入 DB + rebuild_user_faiss_index()

检索链路（使用适配层）：
用户问题
  → ProjectKnowledgeRetriever.get_relevant_documents(question)
    → ProjectEmbeddings.aembed_query(question)  问题转向量
    → search_similar_chunks()  混合检索
    → rerank_chunks()          重排
    → retrieved_chunks_to_langchain_documents()  转标准格式
  → 拿到 list[Document]，喂给 LangChain Chain

---

### 📄 12. rag_langchain_native.py —— LangChain 原生 RAG 问答服务

文件路径：core/service/rag_langchain_native.py

核心作用：RAG 业务主入口。把检索、Prompt 组装、LLM 流式生成、引用整理串成完整的问答闭环。使用 LangChain 原生 LCEL 语法。

完整处理流程：

用户问题 + user_id + strict_mode + top_k
    │
    ▼
┌─ 1. 预检查 ──────────────────────────────────────┐
│    创建 RagRun（trace）                           │
│    strict_mode=True 且 无可用chunk → 直接拒答      │
└──────────────────────────────────────────────────┘
    │
    ▼
┌─ 2. 查询理解与改写 ───────────────────────────────┐
│    understand_query(question) → QueryIntent       │
│    build_weighted_rewrite_queries() → 多路改写     │
└──────────────────────────────────────────────────┘
    │
    ▼
┌─ 3. 混合检索 ─────────────────────────────────────┐
│    search_similar_chunks()  向量+BM25召回          │
│    rerank_chunks()          融合重排 → Top-K chunks│
└──────────────────────────────────────────────────┘
    │
    ▼
┌─ 4. Grounding 判定（要不要直接回答？）─────────────┐
│    evidence_match_score()  证据打分                │
│    relation_evidence_score() 关系证据打分           │
│    build_direct_grounded_answer() → 够强就直接返回  │
│                                                 │
│    ├─ 够强 → 规则出答案（不调LLM，又快又准）        │
│    └─ 不够 → 继续走 LLM 生成                       │
└──────────────────────────────────────────────────┘
    │（如果需要LLM生成）
    ▼
┌─ 5. 组装 Prompt（LCEL）───────────────────────────┐
│    format_documents_as_context(docs)               │
│      → 把每个 chunk 拼成: [序号] 文档名+页+章节     │
│                              正文内容               │
│                                                        │
│    ChatPromptTemplate.from_messages([              │
│      ("system", GROUNDING_INSTRUCTION + 回答要求), │
│      ("human", "请根据上下文回答：{question}\n"    │
│                "上下文：\n{context}")              │
│    ])                                              │
└──────────────────────────────────────────────────┘
    │
    ▼
┌─ 6. LangChain LCEL Chain ────────────────────────┐
│    chain = prompt                                 │
│          | ChatOpenAI(streaming=True, ...)        │
│          | StrOutputParser()                      │
│    调用 chain.astream({question, context})        │
│    → 异步流式吐出一个个 token（delta）             │
└──────────────────────────────────────────────────┘
    │
    ▼
┌─ 7. 整理输出 ─────────────────────────────────────┐
│    build_citations_from_documents() → 引用列表     │
│      （用于前端显示"答案来自哪些文档/第几页"）       │
│    build_retrieved_chunk_payloads() → 检索明细     │
│      （用于调试面板显示每个 chunk 的分数/内容）      │
│    complete_rag_run() → 更新 trace 状态            │
└──────────────────────────────────────────────────┘
    │
    ▼
  流式返回给前端：
  {
    "answer_delta": "...",      // 增量的回答文本（SSE推送）
    "citations": [...],         // 引用列表
    "retrieved_chunks": [...],  // 检索明细
    "run_id": 123               // 本次运行ID
  }

核心函数：
| 函数名 | 作用 |
|--------|------|
| format_documents_as_context(documents) | 把 list[Document] 格式化成 LLM 可读的上下文字符串（带序号、来源头） |
| build_citations_from_documents(documents) | 整理给用户看的引用列表（含文档名、页码、章节、分数、内容摘要） |
| build_retrieved_chunk_payloads(chunks) | 整理给调试看的检索明细 |
| stream_answer_with_knowledge_langchain_native(...) | 主入口函数，实现上述完整流程，返回 AsyncIterator |

使用的 LangChain 组件：
- ChatPromptTemplate —— Prompt 模板
- ChatOpenAI(streaming=True) —— 流式聊天模型
- StrOutputParser —— 字符串输出解析
- | 管道符（LCEL 语法）—— 串联组件成 Chain

---

## 三、模块依赖关系图

                    ┌─────────────────┐
                    │   config.py     │ ← 全局配置（API Key、路径、模型名）
                    └────────┬────────┘
                             │ 被所有 service 导入
        ┌────────────────────┼────────────────────┐
        ▼                    ▼                    ▼
┌───────────────┐   ┌───────────────┐   ┌───────────────┐
│   llm.py      │   │ security.py   │   │ exceptions.py │
│ (LLM客户端)   │   └───────────────┘   └───────────────┘
└───────┬───────┘
        │
        ▼
┌───────────────┐
│ embedding.py  │ ← 文本转向量
└───────┬───────┘
        │
        ├─────────────────────────────────────────────┐
        │                                             ▼
        │                                   ┌──────────────────┐
┌───────▼──────────┐                        │  vector_index.py │
│ document_parser  │                        │  (FAISS索引)      │
│  (文档解析)      │                        └────────┬─────────┘
└───────┬──────────┘                                 │
        │                                            │
        ▼                                            ▼
┌──────────────────────┐                   ┌──────────────────┐
│ hierarchical_chunking│                   │   retrieval.py   │
│  (分层切块)          │◄──────────────────┤ (混合检索+重排)  │
└──────────┬───────────┘                   └────────┬─────────┘
           │                                        │
           │                                        ▼
           │                              ┌──────────────────┐
           │                              │  rag_grounding.py│
           │                              │ (证据判定+直答)  │
           │                              └────────┬─────────┘
           │                                       │
           │                                       ▼
           │                              ┌──────────────────┐
           │                              │ query_rewrite.py │
           │                              │  (查询改写)      │
           │                              └────────┬─────────┘
           │                                       │
           │                                       ▼
           │                              ┌──────────────────┐
           └─────────────────────────────►│langchain_adapters│
                                          │ (LangChain适配)  │
                                          └────────┬─────────┘
                                                   │
                                                   ▼
                                          ┌──────────────────┐
                                          │rag_langchain_    │
                                          │native.py         │
                                          │ (RAG主服务)      │
                                          └────────┬─────────┘
                                                   │
                    ┌──────────────────────────────┼──────────────────────────────┐
                    ▼                              ▼                              ▼
          ┌──────────────────┐         ┌──────────────────┐           ┌──────────────────┐
          │   rag_trace.py   │         │   run_trace.py   │           │   api/routes/    │
          │  (RAG链路追踪)   │         │(Agent链路追踪)   │           │  路由层调用      │
          └──────────────────┘         └──────────────────┘           └──────────────────┘

---

## 四、典型业务调用链（从API到Service）

### 4.1 文档上传入库

POST /api/knowledge/documents/upload
    │
    ▼  api/routes/knowledge.py
    │  接收 multipart 文件 → 保存到临时目录
    │
    ▼  langchain_adapters.py
    │  ProjectDocumentLoader.load()
    │    → document_parser.parse_document()
    │
    ▼  langchain_adapters.py
    │  ProjectTextSplitter.split_documents()
    │    → hierarchical_chunking.build_hierarchical_chunks()
    │      (生成 Parent + Leaf 层级块)
    │
    ▼  langchain_adapters.py
    │  ProjectEmbeddings.embed_documents()
    │    → embedding.embed_texts()
    │
    ▼  DB 写入 KnowledgeDocuments + KnowledgeChunks
    │
    ▼  vector_index.py
       rebuild_user_faiss_index()  重建FAISS索引

### 4.2 RAG 问答

POST /api/rag-langchain-native/ask
    │
    ▼  api/routes/rag_langchain_native.py
    │  校验参数 → 拿到 db session, user_id, question, strict_mode, top_k
    │
    ▼  rag_trace.py
    │  create_rag_run()  创建运行记录
    │
    ▼  rag_langchain_native.py :: stream_answer_with_knowledge_langchain_native()
    │
    │  ├─ query_rewrite.build_weighted_rewrite_queries(question)
    │  │   → 得到带权重的改写查询列表
    │  │
    │  ├─ retrieval.search_similar_chunks()
    │  │   ├─ embedding.embed_text(question)
    │  │   ├─ vector_index.search_user_faiss_index()  向量召回
    │  │   ├─ retrieval.bm25_search()                 关键词召回
    │  │   └─ retrieval.rerank_chunks()               融合重排
    │  │
    │  ├─ rag_grounding.build_direct_grounded_answer()
    │  │   → 证据够强直接返回（走不到LLM）
    │  │
    │  ├─ 证据不够？走 LangChain 生成：
    │  │   ├─ langchain_adapters.retrieved_chunks_to_langchain_documents()
    │  │   ├─ format_documents_as_context()  组装上下文
    │  │   ├─ ChatPromptTemplate 组装 Prompt
    │  │   ├─ ChatOpenAI(streaming=True) | StrOutputParser  建链
    │  │   └─ chain.astream()  流式生成，逐 token 推送
    │  │
    │  └─ build_citations_from_documents()  整理引用
    │
    ▼  rag_trace.py
       complete_rag_run() / fail_rag_run()  更新运行状态

---

## 五、学习建议（按顺序）

如果你要逐个吃透，建议按这个顺序读源码：

1. 入门层（2天）：llm.py → embedding.py → document_parser.py
   - 搞懂"文本怎么来的，怎么转成向量"

2. 切块层（2天）：hierarchical_chunking.py
   - 搞懂"长文本为什么不能硬切，怎么切才合理"

3. 索引层（2天）：vector_index.py
   - 搞懂 FAISS 的基本概念：IndexFlatIP、L2归一化、为什么比暴力搜快

4. 检索层（3天）：rag_grounding.py → query_rewrite.py → retrieval.py
   - 这是RAG最核心的部分：问题怎么理解、怎么改写、怎么召回、怎么重排
   - 重点啃 RetrievedChunk 每个字段的含义

5. 适配层（2天）：langchain_adapters.py
   - 搞懂 LangChain 的四大标准接口：Loader / Splitter / Embeddings / Retriever
   - 理解"为什么要做适配层"而不是直接用 LangChain

6. 业务主层（3天）：rag_langchain_native.py + rag_trace.py + run_trace.py
   - 把前面所有模块串起来看一遍
   - 跟着"完整处理流程"那节的7个步骤，对照代码一行行走

---

## 六、快速查表（调用某个功能该找哪个文件）

| 我想做的事 | 去哪个文件 | 找哪个函数 |
|-----------|-----------|-----------|
| 把文本转成向量 | embedding.py | embed_text() / embed_texts() |
| 解析上传的 PDF/Word | document_parser.py | parse_document() |
| 把长文本切成 chunk | hierarchical_chunking.py | build_hierarchical_chunks() |
| 重建用户的 FAISS 索引 | vector_index.py | rebuild_user_faiss_index() |
| 用向量搜最相似的 chunk | vector_index.py | search_user_faiss_index() |
| 用关键词搜（BM25） | retrieval.py | bm25_search() |
| 混合检索+重排一步到位 | retrieval.py | search_similar_chunks() |
| 提取问题的关键词 | rag_grounding.py | extract_question_focus_terms() |
| 结构化理解用户问题 | rag_grounding.py | understand_query() |
| 判定证据够不够回答 | rag_grounding.py | evidence_match_score() / relation_evidence_score() |
| 改写问题提高召回率 | query_rewrite.py | build_weighted_rewrite_queries() |
| RetrievedChunk 转 LangChain Document | langchain_adapters.py | retrieved_chunk_to_langchain_document() |
| 完整的流式 RAG 问答 | rag_langchain_native.py | stream_answer_with_knowledge_langchain_native() |
| 记录一次问答的全过程 | rag_trace.py | create_rag_run() / create_rag_step() |
| 记录一次聊天的全过程 | run_trace.py | create_run() / create_step() |
