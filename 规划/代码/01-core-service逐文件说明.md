# core/service 逐文件说明

## 1. `llm.py`：模型配置和客户端工厂

- `get_llm_client()`：读取 `settings.OPENAI_API_KEY`、`OPENAI_BASE_URL`，创建 `AsyncOpenAI`。聊天和 embedding 都通过它访问 OpenAI 兼容接口。
- `get_default_model()`：返回聊天模型名 `LLM_MODEL`。
- `get_default_temperature()`：返回默认温度 `LLM_TEMPERATURE`。

它不负责发送具体 prompt，只负责“用什么客户端、什么配置”。

## 2. `embedding.py`：文本转向量

- `get_embedding_model()`：读取独立的 `EMBEDDING_MODEL`，与聊天模型分开。
- `embed_text(text, client=None)`：清理单条文本，空文本返回 `[]`，否则调用 `client.embeddings.create`，返回 `list[float]`。
- `embed_texts(texts, client=None)`：批量版本，文档入库时给多个 leaf 一次性向量化。

注意：函数本身不写数据库，也不建 FAISS；它只负责调用远程 embedding 接口。

## 3. `document_parser.py`：多格式文档统一解析

统一返回一个字典，核心字段是 `full_text`、`pages`、`sections`、`metadata`。不同格式尽量保留页码、章节、工作表等来源信息。

- `normalize_text`：统一换行、空白等文本格式。
- `_sheet_cell_to_text`：把 Excel 单元格安全转换为文本。
- `parse_txt` / `parse_md`：读取普通文本；Markdown 还会拆出章节。
- `parse_pdf`：读取 PDF 页文本，保存页级信息。
- `parse_docx`：读取 Word 段落/表格并组织为文本和章节。
- `parse_xlsx` / `parse_xls`：读取工作表、单元格和表格内容。
- `parse_pptx`：按幻灯片提取文本。
- `_flush_markdown_section`、`_extract_markdown_sections`：Markdown 章节状态机的辅助函数。
- `parse_document(file_path, file_type)`：总分发入口，根据文件类型选择上述 parser。

这个文件只负责“把文件读懂”，不负责分块和向量化。

## 4. `hierarchical_chunking.py`：parent/leaf 分层切块

处理目标不是简单按字符截断，而是尽量保留段落、句子、Markdown 章节和表格结构。

- `_normalize_text`、`_validate_chunk_args`：清洗输入并校验 chunk size/overlap。
- `_split_paragraphs`、`_split_sentences`：按自然语言边界拆分。
- `_split_long_unit`：单个段落过长时再硬切。
- `_tail_overlap_text`：取前一块尾部，给下一块制造 overlap，避免语义断裂。
- `_semantic_text_chunks`：综合段落、句子、长度和 overlap 生成文本 leaf。
- `_looks_like_markdown_table_line`、`_split_markdown_section_blocks`：识别表格并按正文/表格拆块。
- `_build_parent_segments`：从 parser 的 pages/sections/full_text 构建较大的 parent 段落。
- `_build_retrieval_content`：给 leaf 加入父标题、内容类型等前缀，作为 embedding 输入。
- `_safe_find_from`：在原文中定位片段起点，避免重复内容导致 offset 错位。
- `_chunk_table_text`：表格按行切分，保留 `table_row_from/table_row_to`。
- `build_hierarchical_chunks`：总入口，输出扁平列表；每项包含 role、content、retrieval_content、父子关系、来源页/章节和 offset。

调用者随后把返回项按 role 分组：先保存 parent，再给 leaf 做 embedding 并保存。

## 5. `vector_index.py`：FAISS 索引

- `FaissSearchHit`：封装 FAISS 命中的本地位置、chunk_id、document_id 和分数。
- `faiss_available`：判断依赖是否安装。
- `ensure_faiss_index_dir`、`_index_file_path`、`_metadata_file_path`：确定 `data/faiss` 和每个用户的文件路径。
- `_parse_embedding_json`、`_normalize_matrix`：解析和归一化向量。
- `_remove_user_index_files`、`_load_metadata`、`_load_index`：清理/读取索引。
- `rebuild_user_faiss_index(db, user_id=...)`：只查 leaf embedding，过滤坏向量和维度不一致向量，使用归一化后的 `IndexFlatIP`，临时文件写完后原子替换 `.faiss` 和 `.json`。
- `search_user_faiss_index(...)`：加载用户索引，执行 top-k 向量搜索，再通过元数据映射回数据库 chunk。

FAISS 不是真实数据源：索引损坏或不存在时，`retrieval.py` 会降级到数据库暴力余弦计算。

## 6. `rag_grounding.py`：问题理解和证据约束

- `normalize_for_grounding`：统一问题/证据文本形式。
- `infer_question_type`：判断定义、原因、步骤、比较等问题类型。
- `extract_question_focus_terms`：提取问题中的主体和关注词。
- `QueryIntent`：保存问题类型、关系、焦点词和规范化查询。
- `understand_query`：组合上述逻辑，输出 `QueryIntent`。
- `relation_evidence_score`：判断证据中是否同时出现问题要求的关系两端。
- `evidence_match_score`：综合关键词、关系、问题类型线索计算证据匹配分。
- `build_direct_grounded_answer`：在严格证据模式下，从上下文抽取片段并生成“只基于证据”的回答文本。

它偏向规则和评分，不负责数据库查询。

## 7. `query_rewrite.py`：查询改写

- `RewriteQuery`：保存改写后的 query 和权重/来源。
- `_build_relation_rewrites`：围绕“谁与谁是什么关系”生成变体。
- `_build_question_type_rewrites`：围绕问题类型生成变体。
- `_build_focus_term_rewrites`：围绕主体、产品、主题词生成变体。
- `build_weighted_rewrite_queries`：调用 `understand_query`，合并、去重、限制最多 `max_forms` 个改写。

检索会用多个 query form 做关键词召回并按权重合并，目的是减少用户问法和文档表述不一致造成的漏召回。

## 8. `retrieval.py`：检索总中枢

文件很大，建议按“入口 → 召回 → 重排 → 上下文扩展”理解，不要从第一行读到最后一行。

- `RetrievedChunk`：检索结果统一结构，包含 chunk 内容、父子关系、向量分、关键词分、最终分、来源信息和命中的子块。
- `parse_embedding`、`cosine_similarity`：向量解析与相似度。
- `tokenize`、`_tokenize_for_bm25`、`bm25_search`：处理中英文 token 和 BM25 关键词搜索。
- `hybrid_search`：向量召回与 BM25 召回归一化、融合，通常按向量 65% + 关键词 35% 组合，再扩展 parent。
- `build_recall_query_forms`、`build_weighted_recall_query_forms`：生成原问题、规范化问题和改写问题。
- `keyword_overlap_score`、`phrase_overlap_score`、`coarse_recall_score`：为精确词组和证据重合提供奖励。
- `load_user_chunks`、`load_chunks_by_ids`、`load_parent_chunks_by_ids`：从数据库加载用户范围内的 chunk。
- `_search_similar_chunks_by_faiss`：优先走用户 FAISS 索引。
- `_search_similar_chunks_by_bruteforce`：没有可用 FAISS 时，遍历数据库向量计算相似度。
- `search_similar_chunks_by_embedding`：按 embedding 做一轮召回。
- `rerank_chunks`：对初步命中进一步按关键词、证据和结构信息排序。
- `_expand_leaf_hits_to_parent_context`：把 leaf 按 parent 分组，用子块最高分聚合，返回 parent 上下文。
- `search_similar_chunks`：对外总入口。有有效 `query_text` 时走 hybrid；没有文本时走纯向量；最终都返回 parent 结果。

关键漏斗：先多召回 leaf，再重排/聚合，最后给 LLM 较少但更完整的 parent。

## 9. `langchain_adapters.py`：项目能力接入 LangChain

- `retrieved_chunk_to_langchain_document` / `retrieved_chunks_to_langchain_documents`：把项目的 `RetrievedChunk` 转成 LangChain `Document`。
- `_build_leaf_chunk_items`：从解析结果中提取用于切块/入库的 leaf 项。
- `ProjectDocumentLoader`：实现 LangChain `BaseLoader`，内部调用 `parse_document` 和 `build_hierarchical_chunks`，把解析结果作为 Document metadata 交给上层。
- `ProjectTextSplitter`：实现 `TextSplitter` 接口，复用本项目分层切块逻辑。
- `ProjectEmbeddings`：实现 LangChain `Embeddings`，同步方法通过异步方法调用 `embed_text/embed_texts`。
- `ProjectKnowledgeRetriever`：实现 `BaseRetriever`；查询时调用 embedding 和 `search_similar_chunks`，保存最近一次 query embedding、向量命中、重排命中，方便 trace/debug。

这是适配层，不应在这里重新实现一套检索算法。

## 10. `rag_langchain_native.py`：原生 LangChain RAG

- `chunk_to_document`、`chunks_to_documents`：结果转换并补齐来源 metadata。
- `format_documents_as_context`：把多个 Document 拼成给模型看的上下文。
- `build_citations_from_documents`：从 metadata 生成引用。
- `build_retrieved_chunk_payloads`：生成 API/trace 可序列化的命中结果。
- `build_langchain_rag_prompt`：创建严格/普通模式 prompt。
- `build_answer_instruction`：把上下文和严格模式规则转为回答指令。
- `build_langchain_chat_model`：创建 LangChain `ChatOpenAI`，设置模型、温度和 streaming。
- `build_langchain_retriever`：创建 `ProjectKnowledgeRetriever`。
- `build_langchain_rag_chain`：组合 prompt、chat model、字符串解析器。
- `ensure_answer_has_document_citations`：回答没有引用时，依据文档补充引用。
- `stream_answer_with_knowledge_langchain_native`：RAG 服务总入口；先检索并产出 context_ready，再调用 `chain.astream` 产出 delta，最后输出 done 所需的 answer/citations/metadata。

## 11. `run_trace.py` 与 `rag_trace.py`：执行轨迹

两个文件结构相同：`dump_payload` 把 dict/list 序列化为 UTF-8 JSON；`create_*` 创建 running 记录；`complete_*` 写成功结果和结束时间；`fail_*` 写失败信息和结束时间。

- `run_trace.py` 使用 `Runs`、`RunSteps`，字段围绕普通聊天的 session、agent、输入和输出。
- `rag_trace.py` 使用 `RagRuns`、`RagRunSteps`，额外记录问题、top_k、strict_mode、document scope、命中和引用。

这些函数每次都会 commit/refresh，因此调用方可以立即拿到数据库 id；异常处理时要保证未完成的 run/step 被标成 failed。

