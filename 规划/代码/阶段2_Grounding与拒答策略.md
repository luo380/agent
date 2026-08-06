# 阶段2：Grounding与拒答策略

## 核心目标
减少幻觉，让"该答就答、该拒就拒"。

## 涉及函数
- `build_direct_grounded_answer(...)` - 强化直接回答边界
- `evidence_match_score(...)` - 证据匹配分
- `relation_evidence_score(...)` - 关系证据分
- `stream_answer_with_knowledge_langchain_native(...)` - 拒答分流逻辑

---

## 2.1 build_direct_grounded_answer 强化

### 原代码问题
1. 只看 `evidence_match_score`，没有结合 `relation_evidence_score`
2. 没有处理 chunk 之间冲突的情况
3. yes_no 类判断阈值太硬（0.9），可能漏判

### 优化后代码
```python
# ============================================================
# 优化后：build_direct_grounded_answer
# 改动点：
#   1. 综合 evidence_match_score + relation_evidence_score 判断
#   2. yes_no 问题增加"证据冲突"检测
#   3. 调整阈值：direct answer 只在"高置信度"时触发
#   4. 增加 DIRECT_GROUNDED_THRESHOLD 等常量，方便调优
# ============================================================

# direct grounded answer 触发阈值：证据分必须高于此值才直接返回
# 为什么设这么高？因为 direct answer 完全绕开 LLM，宁可不触发也不能错
DIRECT_GROUNDED_EVIDENCE_THRESHOLD = 0.92

# 关系证据对 yes_no 问题的最低要求：关系证据低于此值就不给结论
DIRECT_GROUNDED_RELATION_THRESHOLD = 0.55


def _detect_yes_no_conflict(evidence_windows: list[str]) -> str | None:
    """
    检测 yes_no 类问题中是否存在"既说支持又说不支持"的冲突证据。

    返回值：
    - "conflict"：检测到冲突
    - None：没有检测到冲突
    """
    if not evidence_windows:
        return None

    has_support = False
    has_unsupported = False

    for window in evidence_windows:
        if any(term in window for term in UNSUPPORTED_CONTEXT_TERMS):
            has_unsupported = True
        if any(term in window for term in SUPPORT_CONTEXT_TERMS):
            has_support = True

    if has_support and has_unsupported:
        return "conflict"
    return None


def build_direct_grounded_answer(question: str, context: str) -> str:
    """
    【核心接地函数】尝试根据知识库 context 直接生成高置信度简短答案。

    【分流策略】
    高置信度 → 直接返回 grounded answer（省 token + 更稳定）
    中低置信度 → 返回空串 ""，交给上层走 LLM 生成

    【yes_no 类判断流程】
    1. evidence_match_score >= 0.92（关键词+上下文线索都强）
    2. 如果有 relation，relation_evidence_score >= 0.55（关系也对得上）
    3. 检查是否存在"既支持又不支持"的冲突
    4. 无冲突才给确定性结论

    【其他类型判断流程】
    1. evidence_match_score >= 0.92
    2. 抽取知识片段拼装返回
    """
    question_type = infer_question_type(question)
    terms = extract_question_focus_terms(question)
    if not terms:
        return ""

    # 证据匹配分（关键词 + 上下文线索）
    ev_score = evidence_match_score(question, context)
    if ev_score < DIRECT_GROUNDED_EVIDENCE_THRESHOLD:
        return ""

    term = terms[0]
    evidence_window = _evidence_window(term, context)

    # ========== yes_no 类问题：加关系证据 + 冲突检测 ==========
    if question_type == "yes_no":
        # 如果问题能识别出关系词，关系证据也要够强
        rel_score = relation_evidence_score(question, context)
        intent = understand_query(question)
        if intent.relation and rel_score < DIRECT_GROUNDED_RELATION_THRESHOLD:
            # 关系证据不够，不给 direct answer，交给 LLM 谨慎处理
            return ""

        # 构建多个证据窗口用于冲突检测
        all_evidence_windows = [
            _evidence_window(t, context)
            for t in terms[:3]
            if _evidence_window(t, context)
        ]
        # 再补充全文归一化作为兜底窗口
        all_evidence_windows.append(normalize_for_grounding(context))

        # 检测冲突
        if _detect_yes_no_conflict(all_evidence_windows) == "conflict":
            # 有冲突，不给确定性结论，交给 LLM 保守表达
            return ""

        # 无冲突，判断支持/不支持
        if any(item in evidence_window for item in UNSUPPORTED_CONTEXT_TERMS):
            return f"不支持{term}。知识库上下文中有不支持或不兼容{term}的说明。"
        if any(item in evidence_window for item in SUPPORT_CONTEXT_TERMS):
            return f"支持{term}。知识库上下文已将{term}列为支持项目。"
        return ""

    # ========== 其他类型问题：抽取片段 ==========
    snippet = _extract_snippet(question, context)
    if not snippet:
        return ""
    if question_type == "frequency":
        return f"知识库中提到：{snippet}"
    if question_type == "how_to":
        return f"可以按知识库中的说明操作：{snippet}"
    if question_type == "list":
        return f"知识库中列出的相关内容是：{snippet}"
    return f"知识库中提到：{snippet}"
```

---

## 2.2 evidence_match_score 微调

### 原代码问题
1. 基础分 0.65 略高，关键词命中但上下文完全不对也给 0.65
2. 没有和 relation_evidence_score 结合的点

### 优化后代码
```python
# ============================================================
# 优化后：evidence_match_score
# 改动点：
#   1. 降低"只有关键词命中"的基础分（0.65 → 0.45）
#   2. 提高"上下文线索匹配"的权重（0.35 → 0.55）
#   3. yes_no 类问题额外引入关系证据做加权
#   4. 增加 MAX_MATCHED_TERMS 控制最多考虑几个关键词
# ============================================================

# 关键词命中基础分（只有关键词，没有上下文线索时的分数）
EVIDENCE_BASE_SCORE = 0.45
# 上下文线索匹配奖励分（有对应回答线索时加上）
EVIDENCE_CUE_REWARD = 0.55
# 最多考虑前 N 个关键词匹配，避免词过多导致虚高
MAX_MATCHED_TERMS = 3


def evidence_match_score(question: str, text: str) -> float:
    """
    【证据匹配分】判断 text 能否作为回答 question 的证据。

    【计分规则】
    - 关键词不在 text 中 → 0.0
    - 关键词命中 + 无上下文线索 → 基础分（0.45）
    - 关键词命中 + 有上下文线索 → 基础分 + 线索奖励（最高1.0）
    - yes_no 类问题额外叠加关系证据分（加权平均）

    【调整原因】
    之前只有关键词命中就给 0.65，太容易触发 direct answer。
    现在提高了"上下文线索"的权重，确保真的有答案对应才给高分。
    """
    terms = extract_question_focus_terms(question)
    if not terms:
        return 0.0

    question_type = infer_question_type(question)
    normalized_text = normalize_for_grounding(text)
    best_score = 0.0

    # 只考虑前 N 个关键词，避免匹配到太多边缘词导致分数虚高
    matched_count = 0
    for term in terms:
        if matched_count >= MAX_MATCHED_TERMS:
            break
        if term not in normalized_text:
            continue

        matched_count += 1
        window = _evidence_window(term, text)
        cue_score = _context_cue_score(question_type, window)

        # 基础分 + 线索奖励分
        term_score = EVIDENCE_BASE_SCORE + cue_score * EVIDENCE_CUE_REWARD

        # yes_no 类问题：再叠加关系证据（和关键词证据做加权平均）
        if question_type == "yes_no":
            rel_score = relation_evidence_score(question, text)
            if rel_score > 0:
                # 关键词证据权重 0.6，关系证据权重 0.4
                term_score = term_score * 0.6 + rel_score * 0.4

        best_score = max(best_score, term_score)

    return min(best_score, 1.0)
```

---

## 2.3 relation_evidence_score 保持稳定（无需大改）

当前 `relation_evidence_score` 已经实现了：
- 主体 + 客体 + 关系 局部窗口判断
- 三元组完整共现额外加分
- yes_no 问题结论词补强

**保持现有实现即可**，但建议在注释中补充：
```python
def relation_evidence_score(question: str, text: str) -> float:
    """
    关系证据分：不只看"主体/客体/关系"有没有出现，
    还看它们是不是在同一段局部上下文里一起成立。

    【典型应用场景】
    - yes_no 类问题：判断"主体是否真的支持/不支持客体"，而不是主题沾边就乱给结论
    - grounding 前置分流：关系证据太弱时，宁可走 LLM 保守回答，也不触发 direct answer

    返回值范围：0.0 ~ 1.0

    【高置信度触发建议】
    - >= 0.80：关系证据很强，基本可以确定
    - >= 0.55：关系证据中等，配合其他证据可用
    - < 0.30：关系证据很弱，不要给确定性 yes_no 结论
    """
    # 原有实现保持不变...
    intent = understand_query(question)
    normalized_text = normalize_for_grounding(text)
    if not normalized_text or not intent.relation:
        return 0.0
    return max(
        _relation_score_in_window(
            intent=intent,
            normalized_window=window,
        )
        for window in _relation_evidence_windows(
            normalized_text,
            subject_terms=intent.subject_terms,
            object_terms=intent.object_terms,
        )
    )
```

---

## 2.4 stream_answer_with_knowledge_langchain_native 分流逻辑

### 原代码问题
1. strict_mode 无 context 时直接拒答 ✓（这块已经做了）
2. 有 context 但 evidence 很弱时，没有保守回答策略
3. direct_grounded_answer 只有 strict_mode 才触发，non-strict 其实也可以走
4. chunk 之间冲突时没有特殊处理

### 优化后代码（只展示核心分流部分）
```python
# ============================================================
# 优化后：stream_answer_with_knowledge_langchain_native 核心分流段
# 改动点：
#   1. 引入预分流决策：pre_decision = {direct_answer, weak_evidence, refuse, llm_generate}
#   2. 增加证据强度计算：计算所有 chunk 的最高证据分
#   3. weak_evidence 时 Prompt 里告诉模型"证据弱，请保守"
#   4. evidence 冲突时，走 LLM 但 Prompt 里特别提醒
# ============================================================

# 低证据模式阈值：所有 chunk 的证据分都低于此值时，走"保守回答"策略
WEAK_EVIDENCE_STREAM_THRESHOLD = 0.45


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
    【LangChain 原生流式 RAG 主流程】

    【新增的生成前分流决策树】
    Step A. 检索 documents
    Step B. 计算上下文证据强度
        |
        +-- 完全无 context + strict → 直接拒答（return）
        |
        +-- direct grounded answer 命中 → 直接返回（省token）
        |
        +-- 所有 chunk 证据都很弱 → weak_evidence 模式
        |                           Prompt 要求保守回答
        |
        +-- chunk 之间有冲突 → conflict 模式
        |                     Prompt 要求保守表达，不要做绝对结论
        |
        +-- 正常 → 标准 LLM 生成
    Step C. 流式返回结果
    """
    client = client or get_llm_client()

    # ========== Step 1~4：检索、转 Document、拼 context、构建 citations ==========
    retriever = build_langchain_retriever(
        db, user_id=user_id, top_k=top_k, document_ids=document_ids, client=client,
    )
    documents = await retriever.aretrieve_documents(question)
    reranked_hits = retriever.last_reranked_hits
    context = format_documents_as_context(documents)
    citations = build_citations_from_documents(documents)
    retrieved_chunk_payloads = build_retrieved_chunk_payloads(reranked_hits)

    # ========== 新增：证据预分析 ==========
    # 计算每个 chunk 的证据分，找出最大值
    chunk_ev_scores = [
        evidence_match_score(question, doc.page_content)
        for doc in documents
    ] if documents else []
    max_ev_score = max(chunk_ev_scores) if chunk_ev_scores else 0.0

    # 检测 chunk 之间的 yes_no 冲突（例如一个说支持，一个说不支持）
    has_conflict = False
    if infer_question_type(question) == "yes_no" and len(documents) >= 2:
        all_windows = [
            normalize_for_grounding(doc.page_content)
            for doc in documents
        ]
        has_support_in_any = any(
            any(term in w for term in SUPPORT_CONTEXT_TERMS)
            for w in all_windows
        )
        has_unsupport_in_any = any(
            any(term in w for term in UNSUPPORTED_CONTEXT_TERMS)
            for w in all_windows
        )
        has_conflict = has_support_in_any and has_unsupport_in_any

    # ========== 通知前端 context_ready ==========
    yield {
        "event": "context_ready",
        "data": {
            "retrieved_chunk_count": len(retrieved_chunk_payloads),
            "citation_count": len(citations),
            "context_length": len(context),
            "query_embedding_dim": retriever.last_query_embedding_dim,
            "max_evidence_score": round(max_ev_score, 3),
            "has_conflict": has_conflict,
        },
    }

    # ========== 分流分支 1：完全无 context + strict_mode → 拒答 ==========
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
                "decision_path": "refuse_no_context",
            },
        }
        return

    # ========== 分流分支 2：direct grounded answer 命中 ==========
    # 注意：这里不再只限于 strict_mode，non-strict 下证据够强也可以走 direct answer
    direct_grounded_answer = build_direct_grounded_answer(question, context)
    if direct_grounded_answer:
        answer_text = ensure_answer_has_document_citations(direct_grounded_answer, documents)
        yield {
            "event": "done",
            "data": {
                "answer": answer_text,
                "strict_mode": strict_mode,
                "citations": citations,
                "retrieved_chunks": retrieved_chunk_payloads,
                "context": context,
                "query_embedding_dim": retriever.last_query_embedding_dim,
                "decision_path": "direct_grounded_answer",
            },
        }
        return

    # ========== 分流分支 3 & 4：证据弱 / 有冲突 → 走 LLM，但 Prompt 做特殊处理 ==========
    # 构建 chain_input 时，根据证据情况动态调整 answer_instruction
    chain = build_langchain_rag_chain(strict_mode=strict_mode, streaming=True)

    base_instruction = build_answer_instruction(context, strict_mode, documents)
    extra_instruction = ""

    # 弱证据提示
    if max_ev_score < WEAK_EVIDENCE_STREAM_THRESHOLD and context:
        extra_instruction += (
            "\n\n【特别提醒】当前检索到的内容与问题相关性整体偏弱。"
            "请使用保守语气，不要给出确定性结论。"
            "可以说"知识库中未见明确说明"或"仅找到以下弱相关信息"。"
        )

    # 冲突提示
    if has_conflict:
        extra_instruction += (
            "\n\n【冲突提醒】知识库不同段落中存在相互矛盾的表述。"
            "请不要给出绝对化结论，优先说明"知识库中有不同说法"，"
            "并客观列出不同观点的来源，不要偏向任一方。"
        )

    chain_input = {
        "question": question,
        "context": context or "未检索到相关知识库内容。",
        "answer_instruction": base_instruction + extra_instruction,
    }

    # ========== 正常流式生成 ==========
    answer_parts: list[str] = []
    async for delta in chain.astream(chain_input):
        if not delta:
            continue
        answer_parts.append(delta)
        yield {"event": "delta", "data": {"content": delta}}

    answer_text = "".join(answer_parts).strip()
    answer_text = ensure_answer_has_document_citations(answer_text, documents)

    # done 事件中新增 decision_path，方便后续调试评估
    decision_path = "llm_generate"
    if max_ev_score < WEAK_EVIDENCE_STREAM_THRESHOLD:
        decision_path = "llm_weak_evidence"
    if has_conflict:
        decision_path = "llm_with_conflict"

    yield {
        "event": "done",
        "data": {
            "answer": answer_text,
            "strict_mode": strict_mode,
            "citations": citations,
            "retrieved_chunks": retrieved_chunk_payloads,
            "context": context,
            "query_embedding_dim": retriever.last_query_embedding_dim,
            "decision_path": decision_path,
            "max_evidence_score": round(max_ev_score, 3),
        },
    }
```

---

## 阶段2 完成标准检查清单
- [ ] strict_mode 下无 context 时直接拒答，完全不调模型
- [ ] direct grounded answer 触发阈值合理（>=0.92），宁可不触发也不能错
- [ ] yes_no 类问题结合了 `relation_evidence_score`，不会只看主题
- [ ] 证据弱时，Prompt 里明确告诉模型"保守回答"
- [ ] chunk 之间冲突时，Prompt 明确告诉模型"不要做绝对结论"
- [ ] done 事件中返回了 `decision_path` 字段，方便调试和评估