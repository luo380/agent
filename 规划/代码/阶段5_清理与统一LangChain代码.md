# 阶段5：清理与统一 LangChain 代码

## 核心目标
把当前只保留 LangChain 的架构收口，避免后续维护混乱。

## 涉及文件
- `core/service/rag_langchain_native.py` - 生成链主文件
- `core/service/langchain_adapters.py` - 适配层文件
- `core/service/rag_grounding.py` - 证据与规则判断

---

## 5.1 rag_langchain_native.py 清理

### 清理点 1：删除"和手写版并存"的历史注释

**原文件第24~33行的注释需要修改：**
```python
# ========== 删除（旧历史说明） ==========
"""
LangChain 原生流式 RAG 服务。

这版专门用于阶段 5 对比学习：
- 不改原来的手写 RAG
- 不手动调用 client.chat.completions.create(stream=True)
- 使用 LangChain 原生 LCEL：prompt | ChatOpenAI | StrOutputParser
- 使用 LangChain 原生流式：chain.astream(...)
"""

# ========== 替换为（当前架构说明） ==========
"""
LangChain 原生流式 RAG 服务。

【当前架构（LangChain-Only）】
本项目的 RAG 生成层已完全迁移至 LangChain 原生实现，不再维护手写版。

整体链路：
    用户问题
      ↓
    ProjectKnowledgeRetriever（检索+重排）
      ↓
    format_documents_as_context（格式化上下文）
      ↓
    ChatPromptTemplate（组装 Prompt）
      ↓
    ChatOpenAI（LangChain 原生模型调用）
      ↓
    StrOutputParser + astream（流式输出）

文件职责：
    - 主入口：stream_answer_with_knowledge_langchain_native(...)
    - Prompt 构建：build_langchain_rag_prompt / build_answer_instruction
    - 上下文格式化：format_documents_as_context
    - 引用与兜底：ensure_answer_has_document_citations / build_citations_from_documents
"""
```

### 清理点 2：删除中间调试痕迹

**原文件第562~565行的乱码需要删掉：**
```python
# ========== 删除（调试乱码痕迹） ==========
    # Step 4??????????????????
    # citations???????????????????????
    # retrieved_chunks??????????? chunk ???????

# ========== 保留并优化正常注释 ==========
    # Step 4：准备前端需要的引用来源和检索明细。
    # - citations：偏用户可读，用于答案引用展示
    # - retrieved_chunks：偏调试，用于查看检索/重排得分
```

### 清理点 3：步骤编号统一（Step 1 ~ Step 12 连续）

```python
# ========== 调整后完整的步骤编号 ==========
    # Step 1：获取 LLM 客户端（复用已有连接，避免重复创建）
    client = client or get_llm_client()

    # Step 2：构建 LangChain Retriever（封装了 embed + 召回 + rerank）
    retriever = build_langchain_retriever(...)

    # Step 3：通过 Retriever 获取检索结果（内部执行嵌入、向量召回、rerank）
    documents = await retriever.aretrieve_documents(question)
    reranked_hits = retriever.last_reranked_hits

    # Step 4：把 Document 列表格式化为上下文文本（给模型读的字符串）
    context = format_documents_as_context(documents)

    # Step 5：构建 citations（给前端展示的引用，做过去重）
    citations = build_citations_from_documents(documents)

    # Step 6：构建 retrieved_chunks（给调试用的检索明细）
    retrieved_chunk_payloads = build_retrieved_chunk_payloads(reranked_hits)

    # Step 7：通知前端检索完成，可展示"正在生成答案"
    yield {"event": "context_ready", "data": {...}}

    # Step 8：生成前分流（拒答 / direct_answer / weak_evidence / 正常）
    #   - 无 context + strict → 直接拒答
    #   - 证据充分 → direct_grounded_answer（省 token）
    #   - 证据弱 → Prompt 提醒保守
    #   - 有冲突 → Prompt 提醒不要绝对化

    # Step 9：构建 LangChain LCEL 链（prompt | llm | parser）
    chain = build_langchain_rag_chain(strict_mode=strict_mode, streaming=True)

    # Step 10：组装 chain 输入（问题 + 上下文 + 动态回答要求）
    chain_input = {...}

    # Step 11：执行 LangChain 原生流式生成，逐 delta 推送前端
    answer_parts: list[str] = []
    async for delta in chain.astream(chain_input):
        answer_parts.append(delta)
        yield {"event": "delta", "data": {"content": delta}}

    # Step 12：拼装完整答案，追加引用兜底，输出最终 done 事件
    answer_text = "".join(answer_parts).strip()
    answer_text = ensure_answer_has_document_citations(answer_text, documents)
    yield {"event": "done", "data": {...}}
```

### 清理点 4：chunk_to_document / chunks_to_documents 的注释更新

这两个函数现在是纯兼容入口，注释要写清楚：
```python
def chunk_to_document(chunk: RetrievedChunk | dict) -> Document:
    """
    【兼容保留函数】把 RetrievedChunk 转成 LangChain Document。

    ⚠️  注意：新代码不要直接调用这个函数，请使用
    langchain_adapters.retrieved_chunk_to_langchain_document(...)。

    本函数保留仅为了兼容旧调用点。
    """
    return retrieved_chunk_to_langchain_document(chunk)


def chunks_to_documents(chunks: Sequence[RetrievedChunk | dict]) -> list[Document]:
    """
    【兼容保留函数】批量把 RetrievedChunk 转成 LangChain Documents。

    ⚠️  注意：新代码不要直接调用这个函数，请使用
    langchain_adapters.retrieved_chunks_to_langchain_documents(...)。

    本函数保留仅为了兼容旧调用点。
    """
    return retrieved_chunks_to_langchain_documents(chunks)
```

---

## 5.2 langchain_adapters.py 清理

### 清理点 1：头部注释统一成 LangChain-only 架构

**原文件第22~45行的注释更新：**
```python
# ========== 替换后的头部注释 ==========
"""
项目的 LangChain 适配层（当前架构：LangChain-Only）。

【文件定位】
本文件不实现任何 RAG 业务逻辑，只负责把项目现有的文档解析、
切块、嵌入、检索能力"接入"LangChain 标准接口。

【四个核心适配器】
1. ProjectDocumentLoader  →  LangChain Document Loader
   - 入参：文件路径 + 文件类型
   - 内部复用：parse_document(...)
   - 产出：LangChain Document（含 parsed_document 元数据）

2. ProjectTextSplitter    →  LangChain Text Splitter
   - 入参：Loader 产出的 Document
   - 内部复用：build_hierarchical_chunks(...)（保留页码/章节信息）
   - 产出：切分后的 chunk Documents

3. ProjectEmbeddings      →  LangChain Embeddings
   - 入参：单条或批量文本
   - 内部复用：embed_text(...) / embed_texts(...)
   - 产出：list[float] 向量

4. ProjectKnowledgeRetriever → LangChain Retriever
   - 入参：用户问题
   - 内部复用：search_similar_chunks(...) + rerank_chunks(...)
   - 产出：重排后的相关 Documents

【上下游关系】
    入库：File → ProjectDocumentLoader → ProjectTextSplitter → ProjectEmbeddings → 向量库
    问答：Question → ProjectKnowledgeRetriever → rag_langchain_native（生成链）
"""
```

### 清理点 2：删除重复或多余的注释

**原文件第120~124行的重复标题注释删除：**
```python
# ========== 删除（重复的标题注释） ==========
#
def retrieved_chunk_to_langchain_document(...):

# ========== 保留并简化为 ==========
def retrieved_chunk_to_langchain_document(chunk: RetrievedChunk | dict) -> Document:
    """
    把项目的 RetrievedChunk 转成 LangChain Document。

    字段映射：
      RetrievedChunk.content       → Document.page_content
      RetrievedChunk.document_id   → Document.metadata["document_id"]
      RetrievedChunk.document_name → Document.metadata["document_name"]
      RetrievedChunk.chunk_id      → Document.metadata["chunk_id"]
      RetrievedChunk.chunk_index   → Document.metadata["chunk_index"]
      RetrievedChunk.source_page   → Document.metadata["source_page"]
      RetrievedChunk.source_section→ Document.metadata["source_section"]
      RetrievedChunk.final_score   → Document.metadata["score"]
    """
    # 原有实现不变...
```

### 清理点 3：retrieved_chunks_to_langchain_documents 注释简化

删除"【批量转换函数】"这种重复标签：
```python
def retrieved_chunks_to_langchain_documents(
    chunks: Sequence[RetrievedChunk | dict],
) -> list[Document]:
    """
    批量把检索结果转成 LangChain Document 列表。
    """
    return [retrieved_chunk_to_langchain_document(chunk) for chunk in chunks]
```

---

## 5.3 rag_grounding.py 清理

### 清理点 1：GROUNDING_INSTRUCTION 的乱码恢复（注意编码）

检查一下文件中 GROUNDING_INSTRUCTION 常量是否因为编码问题变成了 unicode 转义。
如果是，确保它是正常的中文：

```python
# ========== 确保是正常中文，不是 unicode 转义 ==========
GROUNDING_INSTRUCTION = (
    "如果知识库上下文已经提供能回答问题的证据，"
    "必须基于该证据直接回答；"
    "列表、枚举、频率、步骤和参数都算有效证据。"
    "只有在上下文没有相关证据时，才能回答"知识库未提及"。"
)
```

### 清理点 2：底部的 backward-compatible 别名加备注

```python
# ========== 原有底部保留别名，补充注释说明 ==========

# ============================================================
# 向后兼容别名
# 用途：旧代码迁移过程中的过渡兼容。
# 新代码请直接使用上面的正式函数名，不要使用这些别名。
# ============================================================
SUPPORT_QUERY_ANCHORS = YES_NO_ANCHORS
LIST_MEMBERSHIP_GROUNDING_RULE = GROUNDING_INSTRUCTION
extract_support_question_item = lambda question: (extract_question_focus_terms(question) or [""])[0]
support_item_in_text = lambda question, text: bool(evidence_match_score(question, text))
build_direct_support_answer = build_direct_grounded_answer
```

### 清理点 3：QueryIntent dataclass 注释补充当前用途

```python
@dataclass
class QueryIntent:
    """
    轻量结构化 Query 理解结果。

    当前在项目中的实际用途：
    1. relation_evidence_score(...)：判断"主体-关系-客体"是否真正共现
    2. build_direct_grounded_answer(...)：yes_no 类问题的关系证据补强
    3. 后续可扩展：用于 query rewrite、检索增强等场景

    注意：本结构是"足够稳、足够便宜"的轻量规则解析，
         不追求 NLP 级完美语义理解。
    """
    # 问题类型：yes_no / frequency / how_to / list / fact
    question_type: str
    # 主体实体：通常是"设备 / 产品 / 主对象"
    subject_terms: list[str] = field(default_factory=list)
    # 客体实体：通常是"能力 / 功能 / 属性 / 约束对象"
    object_terms: list[str] = field(default_factory=list)
    # 规范化关系词：支持 / 连接 / 控制 / 包含 / 设置
    relation: str = ""
    # 原有焦点词抽取结果，继续复用
    focus_terms: list[str] = field(default_factory=list)
    # 规范化后的主检索式
    normalized_query: str = ""
    # 原始问题，方便调试和兜底
    original_query: str = ""
```

---

## 5.4 三个文件的职责边界（最终版）

为避免后续维护混乱，建议在三个文件的头部都加上职责声明：

### rag_langchain_native.py（生成链层）
```
职责：
  - 组装 Prompt（包含系统规则 + 上下文 + 动态回答要求）
  - 调用 LangChain LCEL 链生成回答
  - 处理 direct_grounded_answer / 拒答 / 弱证据 等生成前分流
  - 生成后引用兜底、最终 done 事件组装
```

### langchain_adapters.py（适配层）
```
职责：
  - 把项目现有能力（parse_document / chunk / embed / search / rerank）
    适配成 LangChain 标准接口
  - 不做任何业务判断
  - 不直接调用 LLM
```

### rag_grounding.py（证据与规则层）
```
职责：
  - Query 轻量结构化理解（问题类型、主体、关系、客体）
  - 证据匹配分数计算（关键词 + 上下文线索）
  - 关系证据分数计算（主体-关系-客体局部共现）
  - 高置信度直接回答（direct grounded answer）
  - 不调用 LLM，不做流式输出
```

---

## 阶段5 完成标准检查清单
- [ ] `rag_langchain_native.py` 头部注释已改成 LangChain-only 架构说明
- [ ] 删除了 "Step 4????????" 这类乱码调试痕迹
- [ ] `stream_answer_with_knowledge_langchain_native` 的步骤编号连续（Step 1 ~ Step 12）
- [ ] `langchain_adapters.py` 头部注释已统一成四个核心适配器说明
- [ ] `rag_grounding.py` 底部兼容别名区已加"新代码不要用"的提醒
- [ ] 三个文件的职责边界清晰，没有互相越权的逻辑