# core/service 深度梳理（按真实代码执行）

这份文件比 `01-core-service逐文件说明.md` 更接近源码阅读笔记：重点解释“函数为什么存在、上一步给它什么、它产出什么、下一步拿它做什么”。

## 0. 先建立一张调用地图

```text
配置层
  llm.get_llm_client / get_default_model / get_default_temperature
       |                         |
       +--> embedding.embed_text(s)   +--> rag_langchain_native.build_langchain_chat_model

入库层
  ProjectDocumentLoader.lazy_load
    -> document_parser.parse_document
    -> parsed_document
  ProjectTextSplitter / knowledge.py
    -> hierarchical_chunking.build_hierarchical_chunks
    -> parent + leaf dict
  ProjectEmbeddings.aembed_documents
    -> embedding.embed_texts
  knowledge.py 写 KnowledgeChunks
    -> vector_index.rebuild_user_faiss_index

检索层
  ProjectKnowledgeRetriever.aretrieve_documents
    -> ProjectEmbeddings.aembed_query
    -> retrieval.search_similar_chunks_by_embedding
    -> retrieval.rerank_chunks
    -> RetrievedChunk 转 Document

回答层
  rag_langchain_native.stream_answer_with_knowledge_langchain_native
    -> context/citations
    -> strict_mode 规则回答或 LangChain chain.astream
    -> context_ready / delta / done
```

## 1. `document_parser.py`：把文件变成结构化字典

### 对外入口

`parse_document(file_path, file_type) -> dict` 是唯一应该被上层直接依赖的入口。它依据扩展名/类型分派到 `parse_txt`、`parse_md`、`parse_pdf`、`parse_docx`、`parse_xlsx`、`parse_xls`、`parse_pptx`。

### 返回结构

```python
{
    "full_text": "完整纯文本",
    "pages": [...],       # PDF/PPTX 等页级信息
    "sections": [...],    # Markdown 标题、Word/Excel 章节或工作表
    "metadata": {...},    # 文件作者、创建时间等额外信息
}
```

### 各函数作用

- `normalize_text`：在进入后续切块前统一换行和空白；这是所有格式的共同清洗入口。
- `_sheet_cell_to_text`：Excel 专用，把数字、日期、空值等单元格变成可拼接文本。
- `parse_txt`：读取全文，通常没有页/章节结构。
- `parse_md`：读取全文，并调用 `_extract_markdown_sections` 保留标题层级。
- `parse_pdf`：按页提取文本，页码是后续引用的主要来源。
- `parse_docx`：提取 Word 段落和表格，并尽量组织成 section。
- `parse_xlsx` / `parse_xls`：按 worksheet 读取表格；旧版 `.xls` 与 `.xlsx` 使用不同底层库。
- `parse_pptx`：按 slide 提取文本。
- `_flush_markdown_section`：Markdown 解析时把当前累计标题/正文落入 sections。
- `_extract_markdown_sections`：以 Markdown `#` 标题为边界构造 section。

### 重要边界

此文件不做 embedding、不写数据库、不建索引。解析失败应在 API 路由中转换为文档失败状态；解析成功后交给 `hierarchical_chunking`。

## 2. `hierarchical_chunking.py`：从全文构造两层 chunk

### 主入口

`build_hierarchical_chunks(parsed, file_type, chunk_size=500, overlap=100) -> list[dict]`。

它做四件事：校验参数、构造 parent、为每个 parent 构造 leaf、返回扁平列表。列表顺序通常是：

```text
parent_0, leaf_0_1, leaf_0_2, parent_1, leaf_1_1, ...
```

### 第一步：构造 parent

`_build_parent_segments(parsed, file_type)` 按格式选择父块边界：PDF/PPTX 倾向按页，Excel 倾向按工作表，Markdown 倾向按章节，普通文本使用通用全文策略。每个 segment 至少有 `text`、`parent_title`、`block_type`，并可能带 `source_page/source_section`。

### 第二步：构造 leaf

- 正文 parent：`_semantic_text_chunks` 先按段落，再按句子，再对过长单元硬切；`_tail_overlap_text` 提供相邻块重叠。
- 表格 parent：`_chunk_table_text` 按行范围切分，并尽量重复表头；表格 leaf 的 `table_row_from/table_row_to` 用于来源追踪。
- `_build_retrieval_content(parent_title, block_type, leaf_text)` 给 leaf 增加父级标题和内容类型前缀。embedding 用的是它，而不是裸的 `content`。

### 第三步：生成定位信息

`_safe_find_from` 在父块/全文中寻找 leaf 的位置；结果写入 `start_offset/end_offset`。找不到时采用当前游标作为防御性兜底，因此 offset 是辅助定位信息，不应当被当成绝对可靠的唯一主键。

### 每个返回 dict 的关键字段

```text
local_parent_key       内存阶段父子关联键，如 parent_0
chunk_role             parent 或 leaf
chunk_index            全文统一顺序
parent_title           父级主题
block_type             text 或 table
child_index            leaf 在 parent 中的序号
content                实际展示/上下文内容
retrieval_content      检索和 embedding 内容，parent 通常为空
source_page/section    来源位置
start/end_offset       原文字符范围
table_row_from/to      表格行范围
```

数据库入库后，`local_parent_key` 被替换为真实的 `parent_chunk_id`。

## 3. `embedding.py` 与 `llm.py`：两个远程模型基础能力

### `llm.py`

- `get_llm_client()`：每次返回一个配置好的 `AsyncOpenAI` 客户端，使用 `OPENAI_BASE_URL`，所以可以接 OpenAI 兼容服务。
- `get_default_model()` 和 `get_default_temperature()`：只读配置，不执行网络请求。

### `embedding.py`

- `get_embedding_model()`：读取 embedding 专用模型名。
- `embed_text`：空字符串直接返回空向量；非空文本调用单条 embedding API。
- `embed_texts`：批量调用 embedding API；返回顺序必须与输入顺序一致，知识库入库依靠这个顺序把向量对应回 leaf。

注意：embedding 维度不是代码固定值，而由模型决定。FAISS 建索引时会检查维度一致性。

## 4. `vector_index.py`：数据库向量的本地加速层

### 文件布局

按用户生成两类文件：

```text
data/faiss/user_{user_id}.faiss   FAISS 索引
data/faiss/user_{user_id}.json    FAISS 行号 -> chunk_id/document_id 映射
```

### `rebuild_user_faiss_index`

执行顺序：

1. `faiss_available()` 失败时返回 0，系统仍可用。
2. 查询当前用户的 `KnowledgeChunks`，只取 `chunk_role=leaf`。
3. `_parse_embedding_json` 解析 embedding；坏 JSON、空向量、维度异常向量被跳过。
4. `_normalize_matrix` 做 L2 归一化。
5. 使用 `IndexFlatIP`；向量归一化后，内积等价于 cosine similarity。
6. 先写 `.tmp`，然后 `.replace()` 原文件，降低中途崩溃留下半索引的风险。
7. 返回真正写入的 leaf 数量。

### `search_user_faiss_index`

加载索引后返回命中结果。FAISS 只知道本地行号，因此必须读 JSON metadata 才能得到数据库 chunk id；完整内容仍需要回数据库读取。

### 失败降级

FAISS 不可用、文件不存在或读取失败时，`retrieval.py` 使用 `_search_similar_chunks_by_bruteforce`，遍历数据库中的 leaf embedding 做余弦计算。代价是慢，但不会因为索引问题直接让问答不可用。

## 5. `retrieval.py`：最复杂的检索中枢

### 数据结构

`RetrievedChunk` 是整个检索层的标准结果。除了文本和来源，还包含：

```text
vector_score       向量相似度
keyword_score      BM25/关键词分
final_score        当前阶段最终排序分
matched_child_content  parent 扩展时命中的 leaf 内容
```

### 召回工具函数

- `parse_embedding`：兼容 JSON 字符串和 list 输入。
- `cosine_similarity`：暴力检索时使用。
- `_generate_cjk_ngrams`：中文没有天然空格，生成 2-4 字 n-gram。
- `tokenize`、`_tokenize_for_bm25`：兼顾中文 n-gram 和拉丁字母/数字 token。
- `bm25_search`：从数据库加载候选后计算关键词相关性。
- `_normalize_score_map`：把不同召回路的分数压到可融合的范围。

### `hybrid_search`

这是有原始问题文本时的主路径：

1. 根据 query 做向量召回和 BM25 召回。
2. 通过 chunk id 合并两路结果。
3. 归一化向量分和关键词分。
4. 计算 `final_score = vector_score * 0.65 + keyword_score * 0.35`。
5. 先保留约 `top_k * 3` 的 leaf 候选。
6. `_expand_leaf_hits_to_parent_context` 聚合到 parent。
7. 交给上层 `rerank_chunks` 做最终精排。

### `search_similar_chunks_by_embedding`

这是带 query embedding 的召回封装，内部优先 `_search_similar_chunks_by_faiss`，失败时 `_search_similar_chunks_by_bruteforce`。它是“召回”，不等于最终结果；调用方还会 rerank。

### `rerank_chunks`

对候选 parent 做更细评分。每个候选会计算：原问题关键词、原问题短语、改写关键词、改写短语、证据分、关系证据分，并保留初始向量/关键词分。源码当前综合公式的权重为：

```text
向量 0.35
粗排关键词 0.12
原问题关键词 0.04
原问题短语 0.04
改写关键词 0.16
改写短语 0.20
证据 0.30
关系证据 0.18
```

排序后截取 `top_k`。这里的“关系证据”用于区分“词都出现了但关系不成立”的错误命中。

### `load_*` 系列

- `load_user_chunks`：按 user_id、可选 document_ids 读取候选 chunk。
- `load_chunks_by_ids`：按命中 id 回表，并再次带用户条件做权限隔离。
- `load_parent_chunks_by_ids`：按 parent id 批量取完整上下文。

### `_expand_leaf_hits_to_parent_context`

把多个 leaf 按 `parent_chunk_id` 分组；每个 parent 的代表分数通常取组内最高命中分；把命中的 leaf 文本放到 `matched_child_content`；最终返回 parent 内容。这样检索定位精确，送给模型的上下文又不会碎。

### `search_similar_chunks`

这是推荐的门面入口：

- `query_text` 非空：调用 `hybrid_search`。
- `query_text` 为空：只走向量召回，通常先取 `top_k * 3` 个 leaf，再扩展成 `top_k * 2` 个 parent。
- `document_ids`：限制当前用户的文档范围。
- `user_id`：每个数据库查询和 FAISS 文件都以用户隔离。

## 6. `rag_grounding.py`：查询理解和规则证据

### 查询理解

- `normalize_for_grounding`：统一大小写、空白和标点形式。
- `infer_question_type`：从问题词判断定义/原因/步骤/比较等类型。
- `extract_question_focus_terms`：提取产品、主体和核心关注词。
- `_match_relation`：尝试抽取“主体 - 关系 - 客体”，例如“设备是否支持某能力”。
- `QueryIntent`：承载 question_type、focus_terms、relation、normalized_query 等结构化意图。
- `understand_query`：组合以上规则，供 query rewrite 和证据评分使用。

### 证据评分

- `relation_evidence_score`：在局部 evidence window 内判断关系两端是否一起出现。
- `_context_cue_score`：检查上下文是否出现符合问题类型的提示词。
- `evidence_match_score`：综合焦点词、关系和问题类型。
- `build_direct_grounded_answer`：从上下文中抽取 snippet，在严格模式下可直接返回规则答案，避免无证据时调用 LLM。

它不是“另一个大模型服务”，主要是 RAG 的确定性约束和打分工具。

## 7. `query_rewrite.py`：生成检索 query 变体

`RewriteQuery` 保存一个改写文本及其权重/来源。三个构造器分别从关系、问题类型、焦点词生成变体；`_append_rewrite` 负责去空、去重、限制数量。`build_weighted_rewrite_queries(question, max_forms=8)` 最终返回有限个带权 query。

这些改写主要影响 BM25/关键词召回和 rerank，不会替换用户原问题；精排仍保留原始 query，防止改写偏离用户意图。

## 8. `langchain_adapters.py`：项目实现与 LangChain 接口的边界

### `ProjectDocumentLoader`

`load_parsed_document` 调 parser；`lazy_load` 只 yield 一个完整 `Document`，并把 `parsed_document` 放进 metadata。这里的 loader 不负责真正分层切块。

### `ProjectTextSplitter`

`split_text` 为无结构纯文本提供兜底；`split_documents` 优先读取 metadata 中的 `parsed_document`，调用 `_build_leaf_chunk_items`，把 chunk 字段复制到 LangChain Document metadata。它主要是 LangChain 兼容入口，知识库路由目前也会直接调用项目分层函数。

### `ProjectEmbeddings`

实现 LangChain 要求的同步/异步四个接口：`embed_query`、`embed_documents`、`aembed_query`、`aembed_documents`。异步接口直接复用 `embedding.py`；同步接口通过 `_run_async` 适配。

### `ProjectKnowledgeRetriever`

初始化时持有 db、user_id、top_k、document_ids、embedding client，并维护最近一次检索缓存。`_aget_relevant_documents`/`aretrieve_documents` 是异步主路径：问题 embedding → `search_similar_chunks` → `rerank_chunks` → `RetrievedChunk` 转 Document。`last_query_embedding_dim`、`last_vector_hits`、`last_reranked_hits` 供 RAG trace 和 API 返回调试信息。

## 9. `rag_langchain_native.py`：回答编排

- `chunk_to_document`：把 chunk content 放到 `page_content`，把文档名、页码、章节、分数放到 metadata。
- `format_documents_as_context`：把 Documents 拼成带来源标识的上下文字符串。
- `build_citations_from_documents`：把 metadata 去重成用户可看的引用。
- `build_retrieved_chunk_payloads`：把检索对象序列化为 API 可返回的字典。
- `build_langchain_rag_prompt`：生成严格/非严格 prompt。
- `build_answer_instruction`：根据是否有 context 和 strict_mode 生成回答约束。
- `build_langchain_chat_model`：用默认模型/温度创建 `ChatOpenAI`，streaming 参数决定是否支持增量输出。
- `build_langchain_retriever`：创建 `ProjectKnowledgeRetriever`。
- `build_langchain_rag_chain`：连接 prompt → chat model → `StrOutputParser`。
- `ensure_answer_has_document_citations`：回答缺引用时补齐引用行。

### `stream_answer_with_knowledge_langchain_native`

实际顺序是：创建 retriever → 检索 Documents → 格式化 context → 构造 citations/payloads → yield `context_ready`。随后有两个短路分支：严格模式无 context，直接返回“知识库没有相关内容”；`build_direct_grounded_answer` 得到规则答案且严格模式开启，也直接 `done`。否则创建 streaming chain，逐段 yield `delta`，结束后拼接完整答案并 yield `done`。

此函数本身不写 `RagRuns`；数据库轨迹由 API route 调 `rag_trace.py` 负责。

## 10. `run_trace.py` 与 `rag_trace.py`：只负责落库状态

### 普通聊天

`run_trace.py` 使用 `Runs` / `RunSteps`：

```text
create_run -> create_step* -> complete_step/fail_step -> complete_run/fail_run
```

Run 保存 session、agent、user、输入输出和整体状态；Step 保存某个阶段的名称、输入输出 JSON、错误和时间。

### RAG

`rag_trace.py` 使用 `RagRuns` / `RagRunSteps`，额外保存 question、top_k、strict_mode、document_scope。Step 类型可以记录 `embed_query`、`vector_search`、`rerank_chunks`、`generate_answer` 等 RAG 阶段。

两个文件都通过 `dump_payload(..., ensure_ascii=False)` 保持中文 JSON 可读，并在每个状态变更函数中 commit/refresh。

## 11. 数据字段的真正生命周期

```text
parser
  parsed.full_text/pages/sections
    -> chunking
      parent.content
      leaf.content
      leaf.retrieval_content
      source_page/source_section/start_offset/end_offset
        -> knowledge.py
          KnowledgeChunks.embedding_json (只给 leaf)
            -> vector_index
              FAISS + metadata json
                -> retrieval
                  RetrievedChunk
                    -> retriever
                      LangChain Document
                        -> rag_langchain_native
                          context / citations / answer
```

最容易误解的字段是：

- `content` 是用于展示/上下文的内容。
- `retrieval_content` 是给 embedding/BM25 的增强内容，通常包含父标题和 block 类型。
- `embedding_json` 只有 leaf 应有实际向量；parent 为空是设计，不是漏保存。
- `parent_chunk_id` 只有入库后才是真实数据库 id；切块阶段使用 `local_parent_key`。

## 12. 阅读和调试建议

遇到“回答不对”，按以下顺序定位：

1. parser：`full_text/pages/sections` 是否正确。
2. chunking：leaf 是否切断了关键信息，`retrieval_content` 是否包含正确父标题。
3. embedding：查询向量维度是否与索引一致。
4. vector_index：FAISS 是否存在、metadata 映射是否正确；必要时确认是否走暴力降级。
5. retrieval：先看 vector/keyword/final 分，再看 `matched_child_content` 和 parent 内容。
6. rerank：看关系证据和短语匹配是否把真正答案排到前面。
7. RAG：看 `context_ready` 的数量、context 长度和 strict_mode 分支。
8. generation：最后才判断 prompt 或 LLM 输出问题。

