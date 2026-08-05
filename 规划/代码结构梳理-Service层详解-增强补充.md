# Service 层详解（增强补充）

本文件与 代码结构梳理-Service层详解-增强版.md 配套。前一份说明基础能力、文档解析和分层切块；本文件继续深入 FAISS、检索、问题理解、LangChain、RAG 回答和 trace。

---

## 一、vector_index.py：FAISS 索引服务

文件路径：core/service/vector_index.py

### 1. FaissSearchHit

这个不可变 dataclass 表示一次 FAISS 命中：

    row_id       FAISS 内部行号
    chunk_id     KnowledgeChunks.id
    document_id  所属文档
    score        FAISS 返回分数

row_id 不是数据库主键，必须借助 metadata JSON 映射。

### 2. 辅助函数

| 函数 | 作用 |
|---|---|
| faiss_available | 判断 FAISS/NumPy 是否可用 |
| ensure_faiss_index_dir | 创建或返回索引目录 |
| _index_file_path | 拼接用户 .faiss 路径 |
| _metadata_file_path | 拼接用户 .json 路径 |
| _tmp_path | 得到临时写入路径 |
| _parse_embedding_json | 解析数据库向量 |
| _normalize_matrix | L2 归一化二维矩阵 |
| _remove_user_index_files | 删除已有用户索引 |
| _load_metadata | 读取 FAISS 行号映射 |
| _load_index | 加载索引，失败返回安全结果 |

### 3. rebuild_user_faiss_index(db, user_id) -> int

这是全量重建，不是单条增量更新：

    1. FAISS 不可用 -> 返回 0
    2. 查当前用户 KnowledgeChunks
    3. 只取 chunk_role=leaf
    4. 按 document_id/chunk_index 排序
    5. 解析 embedding_json
    6. 跳过坏 JSON、空向量、维度不一致向量
    7. L2 归一化
    8. 使用 IndexFlatIP 建索引
    9. 写 faiss 临时文件和 metadata 临时文件
    10. replace 正式文件
    11. 返回成功索引的 leaf 数量

为什么只索引 leaf：parent 是命中后回表的完整上下文，同时索引 parent 和 leaf 会造成重复。

为什么用 IndexFlatIP：向量归一化后，内积等价于余弦相似度。

为什么跳过坏向量：不同 embedding 模型可能产生不同维度，混在同一个 FAISS 矩阵会直接失败。

### 4. search_user_faiss_index

执行：

    1. 加载当前 user_id 的 .faiss 和 .json
    2. 归一化 query embedding
    3. index.search 得到 score 和 row_id
    4. row_id 通过 metadata 映射到 chunk_id/document_id
    5. 按 document_ids 范围过滤
    6. 返回命中信息给 retrieval 回表

FAISS 不保存完整上下文。真正的 content、source_page、parent_chunk_id 仍在 KnowledgeChunks 中。

### 5. 当前路径校正

当前源码通过 ensure_faiss_index_dir() 和 settings 管理目录，工作区使用 data/faiss 结构。旧说明中的 tmp/faiss_indexes 不能直接当成当前路径。当前源码主要公开 faiss_available、rebuild_user_faiss_index、search_user_faiss_index，也不能假设一定存在 ensure_faiss_index 或 delete_user_faiss_index。

---

## 二、retrieval.py：检索和排序中枢

文件路径：core/service/retrieval.py

文件很长，建议按以下顺序读：

    RetrievedChunk
      -> tokenize/BM25
      -> FAISS/暴力召回
      -> hybrid_search
      -> parent 扩展
      -> rerank_chunks
      -> search_similar_chunks

### 1. RetrievedChunk 字段分组

    一、定位
    document_id, document_name, chunk_id, chunk_index

    二、内容和来源
    content, retrieval_content, source_page, source_section

    三、层级
    chunk_role, parent_chunk_id, parent_title,
    block_type, child_index, table_row_from, table_row_to

    四、评分
    vector_score, keyword_score, final_score

    五、检索临时信息
    embedding_json, matched_child_content

content 是给模型看的正文，retrieval_content 是给 embedding/BM25 的增强文本。matched_child_content 表示 parent 是因为哪一个 leaf 命中的。

### 2. 基础函数

- _recall_text：选择候选参与召回的文本。
- parse_embedding：把 JSON 字符串或 list 统一成浮点列表。
- cosine_similarity：暴力路径的余弦相似度。
- _generate_cjk_ngrams：中文生成 2 到 4 字 n-gram。
- tokenize：生成 token 集合。
- _tokenize_for_bm25：生成保留词频的 token 列表。
- _normalize_score_map：把不同召回路分数归一化到可融合范围。

### 3. bm25_search

BM25 不理解语义，它关注：

    词是否出现
    词出现了几次
    这个词在候选集里是否稀有
    文档长度是否过长

因此它适合产品型号、数字、功能名和连续专业术语。向量检索适合“用户说法”和“文档说法”不同的情况。

### 4. hybrid_search

有有效 query_text 时的实际路径：

    query_text + query_embedding
      -> 向量召回 leaf
      -> BM25 召回 leaf
      -> 按 chunk_id 合并两路结果
      -> 各自归一化
      -> hybrid_score = 0.65 * vector + 0.35 * keyword
      -> 保留约 top_k * 3 个 leaf
      -> leaf 按 parent_chunk_id 分组
      -> 返回约 top_k * 2 个 parent 候选

向量和 BM25 的互补关系：

    向量：意思接近但表述不同也能命中
    BM25：型号、参数、数字必须精确出现才更容易命中

### 5. 查询变体和评分函数

| 函数 | 作用 |
|---|---|
| _phrase_terms | 抽取英文/数字短语 |
| _phrase_query_forms | 构造短语 query |
| _evidence_score | 候选是否提供问题证据 |
| _phrase_overlap_once | 检查连续短语 |
| phrase_overlap_score | 计算短语重合 |
| build_weighted_recall_query_forms | 生成带权 recall query |
| _build_weighted_bm25_query_terms | 合并带权 BM25 词 |
| _append_query_form | 去重追加 query form |
| build_recall_query_forms | 生成普通 query form |
| keyword_overlap_score | 关键词覆盖度 |
| coarse_recall_score | 粗排综合分 |

### 6. 数据库读取和权限

- load_user_chunks：先按 user_id，再按可选 document_ids。
- load_chunks_by_ids：按命中 id 回表，但仍必须带 user_id。
- load_parent_chunks_by_ids：批量读取 parent 完整上下文。

权限原则是：

    document_ids 只是检索范围
    user_id 才是数据归属边界
    二者必须同时存在

### 7. FAISS 和暴力降级

_search_similar_chunks_by_faiss 先得到命中 id，再回数据库拿内容。索引不存在、加载失败或 FAISS 不可用时，_search_similar_chunks_by_bruteforce 遍历用户 leaf，逐条计算 cosine。

search_similar_chunks_by_embedding 统一封装这两条路径。暴力路径复杂度约为 O(N)，N 是用户 leaf 数量；它牺牲速度换取可用性。

### 8. rerank_chunks

精排候选通常是 parent。函数会把 parent.content 与 matched_child_content 合并，使用原问题和改写 query 计算：

    原问题关键词分
    原问题短语分
    改写关键词分
    改写短语分
    evidence_score
    relation_evidence_score
    初始 vector_score
    初始 keyword_score

当前综合权重：

    vector_score            * 0.35
    retrieval_keyword_score * 0.12
    primary_keyword_score   * 0.04
    primary_phrase_score    * 0.04
    rewrite keyword         * 0.16
    rewrite phrase          * 0.20
    evidence score          * 0.30
    relation score          * 0.18

最终按 final_score 排序并截 top_k。调试不能只盯向量分，应同时看命中的短语、关系和证据。

### 9. _expand_leaf_hits_to_parent_context

执行：

    1. 遍历 leaf hits
    2. 按 parent_chunk_id 分组
    3. 批量回查 parent
    4. 组内命中分聚合
    5. 把命中的 leaf 原文保存到 matched_child_content
    6. 生成 parent 类型 RetrievedChunk
    7. 排序后返回

这就是 Small-to-Big：小块负责定位，大块负责上下文。

### 10. search_similar_chunks

这是检索门面：

    query_text 非空
      -> hybrid_search

    query_text 为空
      -> FAISS 向量召回
      -> FAISS 不可用则暴力余弦
      -> parent 扩展

注意：search_similar_chunks 主要负责召回和 parent 扩展；ProjectKnowledgeRetriever 后面还会调用 rerank_chunks，不能把它简单理解成已经完成全部最终排序。

---

## 三、rag_grounding.py：问题理解和证据判定

文件路径：core/service/rag_grounding.py

### 1. 查询理解函数

| 函数 | 作用 |
|---|---|
| normalize_for_grounding | 统一空格、大小写、标点等文本形式 |
| infer_question_type | 判断问题类型 |
| _strip_product_prefix | 清除产品前缀和口语前缀 |
| _clean_focus | 清洗疑问词和语气词 |
| _add_unique_term | 去重添加词 |
| _append_term | 添加有效词 |
| extract_question_focus_terms | 提取主体、对象、参数、能力 |
| _collect_fragment_terms | 收集关系片段词 |
| _match_relation | 找主体-关系-客体 |
| _build_normalized_query | 构造标准查询 |
| understand_query | 输出 QueryIntent |

常见问题类型：

    yes_no       是否、能否、支持、兼容
    frequency    多久、频率、几次
    how_to       如何、怎么、步骤
    list         哪些、有什么
    fact         其他事实问题

### 2. QueryIntent

核心字段：

    question_type
    subject_terms
    object_terms
    relation
    normalized_query
    focus_terms

例如：

    原问题：扫地机器人能不能连接 5G WiFi？
    主体：扫地机器人
    关系：连接/支持
    客体：5G WiFi

### 3. 证据判定函数

- _relation_evidence_windows：寻找主体、关系、客体附近的局部窗口。
- _relation_score_in_window：检查三者是否在同一证据窗口成立。
- relation_evidence_score：计算关系证据分。
- _evidence_window：围绕焦点词提取上下文。
- _context_cue_score：检查步骤、列表、频率等类型提示。
- evidence_match_score：综合焦点、关系和问题类型。
- _extract_snippet：抽取最相关的文本片段。
- build_direct_grounded_answer：严格模式下直接生成证据回答。

关键区别：

    关键词命中：主体词和功能词都出现了
    关系成立：文档明确说主体支持/不支持该功能

grounding 模块主要是规则和评分，不是另一个大模型。

---

## 四、query_rewrite.py：多查询改写

文件路径：core/service/query_rewrite.py

### RewriteQuery

    text      改写文本
    weight    相对权重
    strategy  改写策略名

### 三类改写

- _build_relation_rewrites：主体 + 关系 + 客体。
- _build_question_type_rewrites：改成文档标题常用形式。
- _build_focus_term_rewrites：只保留主体、型号、功能等焦点。

### build_weighted_rewrite_queries(question, max_forms=8)

    understand_query
      -> 原始问题
      -> normalized_query
      -> relation rewrite
      -> question type rewrite
      -> focus term rewrite
      -> 去重
      -> 限制 max_forms

改写是辅助召回，不替换用户原问题。精排仍保留原始 query，防止改写偏离。

---

## 五、langchain_adapters.py：项目实现和 LangChain 的边界

文件路径：core/service/langchain_adapters.py

### 1. 转换辅助函数

- _chunk_value：同时读取 RetrievedChunk 对象和 dict。
- retrieved_chunk_to_langchain_document：content -> page_content，其余字段 -> metadata。
- retrieved_chunks_to_langchain_documents：批量转换并保持排序。
- _build_leaf_chunk_items：调用项目分层切块生成适配数据。

### 2. ProjectDocumentLoader

__init__ 保存 file_path、file_type 和调用方 metadata。

load_parsed_document 直接调用 parse_document。

lazy_load 只 yield 一个整篇 Document：

    page_content = parsed_document.full_text
    metadata = {
        调用方 metadata,
        file_path,
        file_type,
        parsed_document,
        parser_metadata,
    }

它不负责切块。把 parsed_document 放入 metadata，是为了让 splitter 保留 pages/sections。

### 3. ProjectTextSplitter

__init__ 保存 project_chunk_size 和 project_chunk_overlap。

split_text 为没有结构化 metadata 的纯文本提供兜底。

split_documents 的实际步骤：

    1. 复制原 Document metadata
    2. 取出 parsed_document
    3. 没有 parsed_document 时构造 TXT 兜底结构
    4. 调用 _build_leaf_chunk_items
    5. 每个 chunk 生成 Document
    6. 把 chunk_index、role、parent_title、block_type、
       source_page、source_section、offset 等放入 metadata

### 4. ProjectEmbeddings

| 方法 | 实际调用 | 用途 |
|---|---|---|
| embed_query | aembed_query | 同步查询向量 |
| embed_documents | aembed_documents | 同步批量文档向量 |
| aembed_query | embed_text | 异步查询向量 |
| aembed_documents | embed_texts | 异步批量文档向量 |
| _run_async | 事件循环适配 | 同步调用异步函数 |

算法仍在 embedding.py，这里只是适配 LangChain 接口。

### 5. ProjectKnowledgeRetriever

初始化时持有：

    db
    user_id
    top_k
    document_ids
    embedding client

同时保存最近一次检索缓存：

    last_query_embedding
    last_query_embedding_dim
    last_vector_hits
    last_reranked_hits

核心路径：

    aretrieve_documents(question)
      -> aembed_query
      -> search_similar_chunks
      -> rerank_chunks
      -> retrieved_chunks_to_langchain_documents

这些 last 字段用于 context_ready、RAG trace 和前端 retrieved_chunks 调试展示。

---

## 六、rag_langchain_native.py：RAG 回答编排

文件路径：core/service/rag_langchain_native.py

### 1. 格式和引用函数

| 函数 | 作用 |
|---|---|
| _chunk_value | 兼容对象和 dict |
| _normalize_source_page | 页码统一为 int 或 None |
| _format_user_facing_section | 格式化页码/章节 |
| _build_reference_line | 构造来源头 |
| chunk_to_document | 单 chunk -> Document |
| chunks_to_documents | 批量转换 |
| format_documents_as_context | Documents -> context 字符串 |
| build_citations_from_documents | Documents -> 用户引用 |
| build_retrieved_chunk_payloads | chunks -> 调试 JSON |

content 是正文，metadata 保存文档名、页码、章节、chunk id 和分数。

### 2. Prompt 和 chain

- build_langchain_rag_prompt(strict_mode)：创建严格/非严格 Prompt。
- build_answer_instruction(context, strict_mode)：生成本次回答约束。
- build_langchain_chat_model(streaming)：读取模型、温度和 endpoint，创建 ChatOpenAI。
- build_langchain_retriever：创建 ProjectKnowledgeRetriever。
- build_langchain_rag_chain：Prompt -> ChatOpenAI -> StrOutputParser。
- ensure_answer_has_document_citations：没有引用时做输出兜底。

### 3. stream_answer_with_knowledge_langchain_native

完整过程：

    1. 创建或复用 AsyncOpenAI client
    2. 创建 ProjectKnowledgeRetriever
    3. await retriever.aretrieve_documents(question)
    4. 生成 context、citations、retrieved payloads
    5. yield context_ready
    6. strict_mode 且没有 context -> yield done
    7. strict_mode 且规则 grounded answer 非空 -> yield done
    8. 否则创建 streaming=True 的 chain
    9. chain.astream 逐段 yield delta
    10. 拼接完整答案并补引用
    11. yield done

context_ready 主要返回：

    retrieved_chunk_count
    citation_count
    context_length
    query_embedding_dim

done 主要返回：

    answer
    strict_mode
    citations
    retrieved_chunks
    context
    query_embedding_dim

该 service yield Python dict；api/routes/rag_langchain_native.py 才负责把事件编码成 SSE StreamingResponse。该函数本身不是全部 trace 落库逻辑，RagRuns/RagRunSteps 由 route 配合 rag_trace.py 维护。

---

## 七、run_trace.py 和 rag_trace.py

### 1. rag_trace.py

对应 ORM：RagRuns、RagRunSteps。

dump_payload 把 dict/list 序列化为 Text：

    json.dumps(payload, ensure_ascii=False)

create_rag_run 保存：

    user_id
    question
    status=running
    top_k
    strict_mode -> 1/0
    document_scope_json
    started_at

complete_rag_run 写 completed、answer、finished_at；fail_rag_run 写 failed、error_message、finished_at，也可以保留部分 answer。

create_rag_step 创建 running step；complete_rag_step 写 output payload 和完成时间；fail_rag_step 写错误和可选 output。

### 2. run_trace.py

对应 ORM：Runs、RunSteps。

    create_run -> create_step* -> complete_step/fail_step -> complete_run/fail_run

普通 Run 记录 session、agent、user、输入和输出；RAG Run 记录 question、top_k、strict_mode、document scope。两个文件结构相似，但服务的业务类型和数据库表不同。

普通聊天步骤可能是：

    receive_input
    load_agent
    build_messages
    llm_call
    stream_response
    save_message

---

## 八、数据库字段生命周期

    parser.full_text/pages/sections
      -> chunk dict
      -> KnowledgeChunks
           parent.content
           leaf.content
           leaf.retrieval_content
           leaf.embedding_json
      -> vector_index
           FAISS + metadata JSON
      -> retrieval
           RetrievedChunk
      -> langchain adapter
           Document
      -> rag service
           context/citations/answer

关键字段：

    content             展示/回答内容
    retrieval_content   embedding/BM25 增强内容
    embedding_json      leaf 的向量 JSON
    parent_chunk_id     leaf 入库后指向 parent
    source_page         页码引用
    source_section      章节引用
    matched_child_content  parent 命中的 leaf 证据

入库必须先 parent 后 leaf：

    1. 插入 parent
    2. flush 得到 parent.id
    3. local_parent_key 映射到 parent.id
    4. 插入 leaf 并填 parent_chunk_id
    5. commit

parent 没有 embedding 是设计，不应先当成错误；应检查 leaf embedding 和父子关系。

---

## 九、真实示例

### 示例 A：Markdown 连接说明

    # WiFi 连接
    设备支持 2.4G WiFi。

    ## 连接步骤
    打开 App，点击添加设备，然后输入 WiFi 密码。

可能产生：

    parent_0: WiFi 连接
    leaf_0_1: [父级主题] WiFi 连接 ... 设备支持 2.4G WiFi
    parent_1: 连接步骤
    leaf_1_1: [父级主题] 连接步骤 ... 打开 App...

问“怎么连接 WiFi”时，向量/BM25 找到 leaf_1_1，再扩展 parent_1，模型看到完整步骤。

### 示例 B：型号参数表

    型号 | 频段 | 最大速度
    A    | 2.4G | 300M
    B    | 5G   | 867M

表格 leaf 会保留表头和行范围。问“B 型号 5G 最大速度是多少”时，BM25 提供型号和数字的精确匹配，向量提供语义补充，relation/evidence 检查问题关系，parent 扩展保留完整表格上下文。

---

## 十、问题排查

### 上传成功但搜不到

    1. KnowledgeDocuments.content_text 是否有内容
    2. chunk_items 是否为空
    3. parent/leaf 数量是否合理
    4. leaf.embedding_json 是否非空
    5. embedding 维度是否一致
    6. rebuild_user_faiss_index 返回值是否 > 0
    7. FAISS metadata 数量和 index.ntotal 是否一致

### 命中错误内容

    1. query embedding 模型是否一致
    2. BM25 是否命中型号/参数
    3. vector_score、keyword_score、final_score 各是多少
    4. matched_child_content 是否真的相关
    5. relation_evidence_score 是否过低
    6. rerank 后的 final_score 是否合理

### 引用缺页或错页

    1. parser 是否保留 pages/sections
    2. chunking 是否传 source_page/source_section
    3. KnowledgeChunks 是否保存来源
    4. chunk_to_document 是否复制 metadata
    5. build_citations_from_documents 是否正确去重

### RAG 不流式输出

    1. route 是否使用 StreamingResponse
    2. service 是否 yield context_ready
    3. strict_mode 是否提前 done
    4. direct_grounded_answer 是否提前 done
    5. chain 是否 streaming=True
    6. chain.astream 是否产生 delta

---

## 十一、快速查表

| 需求 | 文件 | 函数/类 |
|---|---|---|
| 模型客户端 | llm.py | get_llm_client |
| 聊天模型 | llm.py | get_default_model |
| embedding 模型 | embedding.py | get_embedding_model |
| 文本转向量 | embedding.py | embed_text / embed_texts |
| 解析文件 | document_parser.py | parse_document |
| 正文切分 | hierarchical_chunking.py | _semantic_text_chunks |
| 表格切分 | hierarchical_chunking.py | _chunk_table_text |
| parent/leaf | hierarchical_chunking.py | build_hierarchical_chunks |
| 建索引 | vector_index.py | rebuild_user_faiss_index |
| FAISS 搜索 | vector_index.py | search_user_faiss_index |
| BM25 | retrieval.py | bm25_search |
| 混合检索 | retrieval.py | hybrid_search |
| 总检索入口 | retrieval.py | search_similar_chunks |
| 精排 | retrieval.py | rerank_chunks |
| parent 扩展 | retrieval.py | _expand_leaf_hits_to_parent_context |
| 问题理解 | rag_grounding.py | understand_query |
| 证据评分 | rag_grounding.py | evidence_match_score |
| query 改写 | query_rewrite.py | build_weighted_rewrite_queries |
| LangChain 检索器 | langchain_adapters.py | ProjectKnowledgeRetriever |
| RAG chain | rag_langchain_native.py | build_langchain_rag_chain |
| 流式 RAG | rag_langchain_native.py | stream_answer_with_knowledge_langchain_native |
| RAG 轨迹 | rag_trace.py | create_rag_run / create_rag_step |
| 普通聊天轨迹 | run_trace.py | create_run / create_step |

---

## 十二、当前源码校正

- FAISS 路径由 ensure_faiss_index_dir() 和 settings 决定，当前工作区使用 data/faiss 结构。
- 当前 vector_index.py 主要公开 faiss_available、rebuild_user_faiss_index、search_user_faiss_index；不要假设一定有 ensure_faiss_index 或 delete_user_faiss_index。
- search_similar_chunks 负责召回和 parent 扩展，ProjectKnowledgeRetriever 后续仍会调用 rerank_chunks。
- stream_answer_with_knowledge_langchain_native 负责 yield RAG 事件；route 与 rag_trace.py 配合完成数据库轨迹。

