# 阶段3：Answer Synthesis（按问题类型差异化回答）

## 核心目标
让最终回答更像"整理后的答案"，而不是"把检索文本复述一遍"。

## 涉及函数
- `build_answer_instruction(...)` - 新增问题类型的回答风格指令
- `build_direct_grounded_answer(...)` - direct answer 也要区分风格
- `stream_answer_with_knowledge_langchain_native(...)` - 把问题类型传入生成链路

---

## 3.1 问题类型回答策略总览

| 问题类型 | 回答结构 | 典型例子 |
|---------|---------|---------|
| `yes_no` | 先给「是/否」结论 → 再给证据 → 最后补充细节 | "是否支持WiFi？" |
| `list` | 开头总述 → 编号列点 → 每项简单说明 | "有哪些语音助手？" |
| `how_to` | 一句话概括 → 步骤 1/2/3... → 注意事项 | "怎么连接蓝牙？" |
| `frequency` | 先给频率结论 → 再给原文依据 → 补充建议 | "多久清理一次？" |
| `fact` | 先给定义/结论 → 再补充细节解释 → 来源 | "什么是LDS激光导航？" |

---

## 3.2 build_answer_instruction 增加风格差异化

### 优化后代码
```python
# ============================================================
# 优化后：build_answer_instruction（增加问题类型风格差异化）
# 改动点：
#   1. 新增 question_type 参数
#   2. 每种问题类型提供专属的结构要求
#   3. 多 chunk 整合要求（避免机械堆叠）
# ============================================================

# 弱证据阈值
WEAK_EVIDENCE_SCORE_THRESHOLD = 0.55


def _is_context_weak(context: str, documents: Sequence[Document]) -> bool:
    if not context or not documents:
        return False
    scores = [
        float(doc.metadata.get("score") or doc.metadata.get("final_score") or 0.0)
        for doc in documents
    ]
    return max(scores) < WEAK_EVIDENCE_SCORE_THRESHOLD if scores else True


def _build_style_instruction(question_type: str) -> str:
    """
    根据问题类型返回专属的"回答结构要求"。

    【设计思路】
    每种问题类型都有用户最期待的阅读顺序：
    - yes_no 用户先想知道"支持还是不支持"，然后才关心为什么
    - list 用户想看到"清晰的列表"，而不是段落里混着
    - how_to 用户想看到"步骤化操作"，而不是说明书式的叙述
    """
    if question_type == "yes_no":
        return """
【回答结构要求 - yes_no 类】
请严格按以下三段组织回答：
  第一段：用一句话直接给出明确结论，格式为"支持xxxx。"或"不支持xxxx。"
  第二段：引用知识库原文说明判断依据，标注来源 [1][2]
  第三段（可选）：补充相关的限制条件或注意事项

示例：
  支持连接 5G WiFi。
  根据产品说明，该设备支持 2.4G/5G 双频 WiFi 连接 [1]。
  注意：首次连接时需要靠近路由器完成配网。
"""

    if question_type == "list":
        return """
【回答结构要求 - list 类】
请严格按以下结构组织回答：
  第一句：总述，如"知识库中提到的有以下X项："
  然后：使用 1. 2. 3. 编号列点，每项单独一行
  每个列点的格式：**名称** - 简要说明 [来源编号]
  最后（可选）：总结性说明

示例：
  知识库中提到的语音助手有以下3项：
  1. **小爱同学** - 米家生态默认语音助手，支持声控操作 [1]
  2. **天猫精灵** - 阿里系生态，可通过技能平台对接 [2]
  3. **小度助手** - 百度系生态，部分机型适配 [2]

  注意：不同版本支持的语音助手可能有差异，请以实际型号为准。
"""

    if question_type == "how_to":
        return """
【回答结构要求 - how_to 类】
请严格按以下结构组织回答：
  第一句：简要概括操作目标，如"可以按以下步骤完成设置："
  然后：使用 步骤1 / 步骤2 / 步骤3 编号说明
  每个步骤写一个具体动作，不要把多个动作揉在同一步
  最后（可选）：列出注意事项或常见问题

示例：
  可以按以下步骤连接蓝牙：
  步骤1：打开设备底部电源开关，长按配对键3秒至指示灯快闪
  步骤2：在手机蓝牙列表中选择"扫地机器人XXX"，点击连接 [1]
  步骤3：听到"连接成功"提示音后，表示配对完成

  注意：配对时请确保手机与设备距离不超过1米。
"""

    if question_type == "frequency":
        return """
【回答结构要求 - frequency 类】
请严格按以下结构组织回答：
  第一句：直接给出频率结论，格式为"建议每xxxx进行一次xxxx。"
  第二句：引用知识库原文说明依据，标注来源 [1]
  第三句（可选）：补充不同场景下的调整建议

示例：
  建议每 2 周清理一次尘盒。
  产品说明书中提到，日常使用频率下建议每2周清理一次 [1]。
  如果家中有宠物或环境灰尘较多，建议缩短至每周一次。
"""

    # fact 类（兜底）
    return """
【回答结构要求 - fact 类】
请严格按以下结构组织回答：
  第一句：给出定义或核心结论
  第二段：补充工作原理、参数范围、典型用途等细节
  第三段（可选）：补充相关注意事项或常见误区

示例：
  LDS 激光导航是一种通过激光雷达扫描环境构建地图的导航技术。
  该技术通过顶部 360° 旋转的激光发射器扫描周围环境，精确测量障碍物距离，
  并据此构建房间平面图和规划清扫路径 [1]。相比视觉导航，激光导航精度更高，
  暗光环境下也能正常工作。
"""


def build_answer_instruction(
    context: str,
    strict_mode: bool,
    documents: Sequence[Document] | None = None,
    question_type: str | None = None,
) -> str:
    """
    根据 context、strict_mode 和 question_type 生成【动态回答要求】。

    【新增】question_type 参数用于驱动差异化回答风格：
    - yes_no / list / how_to / frequency / fact

    【多 chunk 整合要求】（所有类型通用）
    1. 多个 chunk 提到同一主题时，先合并信息再回答，不要逐段复述
    2. 相同内容不要重复出现多次
    3. 不要出现"根据文档1...根据文档2..."这种机械堆叠式表述
    """
    has_context = bool((context or "").strip())
    is_weak = _is_context_weak(context, documents or [])

    # 如果指定了问题类型，加上风格要求
    style_instruction = ""
    if question_type:
        style_instruction = _build_style_instruction(question_type)

    # 多 chunk 整合通用要求（只在有多个文档时加上）
    multi_chunk_instruction = ""
    if documents and len(documents) >= 2:
        multi_chunk_instruction = """
【多来源整合要求】
当前检索到了多个相关文档片段，请：
1. 先合并整理所有相关信息，再组织回答
2. 相同或高度相似的内容只说一次，不要重复
3. 不要用"根据第一个文档说...第二个文档又说..."这种逐段复述的写法
4. 如果不同来源有不一致的信息，合并时请明确说明
"""

    # ---------- 情况1：有上下文且证据正常 ----------
    if has_context and not is_weak:
        return (
            "当前已检索到相关知识库内容。\n"
            + style_instruction
            + multi_chunk_instruction
            + f"\n【引用要求】用到具体段落时，在句末标注 [1][2] 来源编号。\n"
            + f"【接地规则】{GROUNDING_INSTRUCTION}"
        )

    # ---------- 情况2：有上下文但证据很弱 ----------
    if has_context and is_weak:
        if strict_mode:
            return (
                "当前检索到的知识库内容与问题相关性较低。\n"
                + style_instruction
                + "\n请保守回答：\n"
                "1. 先说明"知识库中未明确提及该问题的直接答案"\n"
                "2. 如果弱相关内容有参考价值，可以简要列出并标注"仅供参考"\n"
                "3. 不要给出确定性结论"
            )
        else:
            return (
                "当前检索到的知识库内容与问题相关性较低。\n"
                + style_instruction
                + "\n请按以下要求回答：\n"
                "1. 先说明"知识库中未找到明确答案，以下是弱相关内容"\n"
                "2. 列出弱相关内容作为参考\n"
                "3. 可以基于常识补充，但必须标注"以下为非知识库补充内容""
            )

    # ---------- 情况3：完全无上下文 + strict_mode ----------
    if strict_mode:
        return (
            "当前完全没有检索到任何相关知识库内容。\n"
            "请直接回复：知识库中没有找到相关内容。建议尝试调整提问方式，或缩小/更换文档范围后再试。\n"
            "不要编造任何信息，不要使用引用标记。"
        )

    # ---------- 情况4：完全无上下文 + non-strict ----------
    return (
        "当前完全没有检索到任何相关知识库内容。\n"
        + style_instruction
        + "\n请按以下要求回答：\n"
        "1. 先明确说明"知识库中未找到相关内容"\n"
        "2. 可以基于常识给出补充答案，但必须单独标注"以下内容非知识库信息，仅供参考"\n"
        "3. 不要使用 [1]、[2] 这类引用标记"
    )
```

---

## 3.3 build_direct_grounded_answer 风格化优化

### 优化后代码
```python
# ============================================================
# 优化后：build_direct_grounded_answer（按问题类型风格化）
# 改动点：
#   1. yes_no 类：结论先行 + 依据
#   2. list 类：自动列点化（如果检测到顿号/逗号分隔项）
#   3. how_to 类：步骤化（如果检测到"首先/然后/最后"等词）
#   4. frequency 类：频率结论先行
# ============================================================

DIRECT_GROUNDED_EVIDENCE_THRESHOLD = 0.92
DIRECT_GROUNDED_RELATION_THRESHOLD = 0.55


def _format_list_snippet(snippet: str) -> str:
    """
    把 list 类的原始片段尽量格式化成"列点"样式。

    例：
        "支持的语音助手包括小爱同学、天猫精灵、小度。"
        → "知识库中列出的相关内容：\n1. 小爱同学\n2. 天猫精灵\n3. 小度"
    """
    # 只在明显有分隔符（顿号）且项数 >=2 时格式化
    if "、" not in snippet:
        return snippet

    # 尝试提取冒号后的内容
    colon_split = re.split(r"[：:]", snippet, maxsplit=1)
    if len(colon_split) == 2:
        prefix, body = colon_split
    else:
        prefix = "知识库中列出的相关内容"
        body = snippet

    # 按顿号切分（去掉末尾标点）
    items_raw = re.split(r"[、,，]", body.strip().rstrip("。.!！"))
    items = [it.strip() for it in items_raw if it.strip()]

    if len(items) < 2:
        return snippet

    formatted = "\n".join(f"{i+1}. {it}" for i, it in enumerate(items))
    return f"{prefix}：\n{formatted}"


def _format_howto_snippet(snippet: str) -> str:
    """
    把 how_to 类的原始片段尽量格式化成"步骤化"样式。
    如果片段里有明显的"首先/然后/最后/步骤1"等词，就做分步骤处理。
    """
    step_words = ["首先", "第一步", "步骤1", "步骤一", "1、", "1."]
    if not any(w in snippet for w in step_words):
        return snippet

    # 简单的按句号切分，每句前加"步骤X"
    sentences = [s.strip() for s in re.split(r"[。.;；]", snippet) if s.strip()]
    if len(sentences) < 2:
        return snippet

    formatted = "\n".join(f"步骤{i+1}：{s}" for i, s in enumerate(sentences[:5]))
    return f"可以按以下步骤操作：\n{formatted}"


def build_direct_grounded_answer(question: str, context: str) -> str:
    """
    按问题类型返回风格化的 direct grounded answer。
    证据不够时返回空串，交给 LLM 处理。
    """
    question_type = infer_question_type(question)
    terms = extract_question_focus_terms(question)
    if not terms:
        return ""

    ev_score = evidence_match_score(question, context)
    if ev_score < DIRECT_GROUNDED_EVIDENCE_THRESHOLD:
        return ""

    term = terms[0]
    evidence_window = _evidence_window(term, context)

    # ========== yes_no ==========
    if question_type == "yes_no":
        rel_score = relation_evidence_score(question, context)
        intent = understand_query(question)
        if intent.relation and rel_score < DIRECT_GROUNDED_RELATION_THRESHOLD:
            return ""

        all_evidence_windows = [
            _evidence_window(t, context) for t in terms[:3] if _evidence_window(t, context)
        ]
        all_evidence_windows.append(normalize_for_grounding(context))

        # 冲突检测
        has_support = False
        has_unsupported = False
        for w in all_evidence_windows:
            if any(t in w for t in UNSUPPORTED_CONTEXT_TERMS):
                has_unsupported = True
            if any(t in w for t in SUPPORT_CONTEXT_TERMS):
                has_support = True
        if has_support and has_unsupported:
            return ""

        if any(item in evidence_window for item in UNSUPPORTED_CONTEXT_TERMS):
            # 风格：结论先行 + 依据
            return (
                f"不支持{term}。\n"
                f"依据：知识库上下文中明确提到不支持或不兼容{term}。"
            )
        if any(item in evidence_window for item in SUPPORT_CONTEXT_TERMS):
            return (
                f"支持{term}。\n"
                f"依据：知识库上下文中已将{term}列为支持项目。"
            )
        return ""

    # ========== 其他类型：抽取 snippet + 格式化 ==========
    snippet = _extract_snippet(question, context)
    if not snippet:
        return ""

    if question_type == "frequency":
        # 风格：频率结论先行（从 snippet 中提取频率词，提取不到就用原文）
        freq_match = FREQUENCY_CONTEXT_RE.search(snippet)
        if freq_match:
            freq_text = freq_match.group()
            return (
                f"建议{freq_text}。\n"
                f"依据：{snippet}"
            )
        return f"知识库中提到：{snippet}"

    if question_type == "how_to":
        formatted = _format_howto_snippet(snippet)
        return f"可以按知识库中的说明操作：\n{formatted}"

    if question_type == "list":
        formatted = _format_list_snippet(snippet)
        return f"知识库中列出的相关内容：\n{formatted}"

    # fact 兜底
    return f"知识库中提到：{snippet}"
```

---

## 3.4 主流程中传递 question_type

### 修改点
在 `stream_answer_with_knowledge_langchain_native` 中：
1. 一开始就调用 `infer_question_type(question)` 识别类型
2. 把类型传给 `build_answer_instruction(...)`
3. 把类型写入 done 事件的 data，方便评估

```python
# ========== 在 stream_answer_with_knowledge_langchain_native 函数开头增加 ==========
async def stream_answer_with_knowledge_langchain_native(...):
    # ...原有代码...

    # 【新增】识别问题类型，用于后续回答风格差异化
    question_type = infer_question_type(question)

    # ...检索、构建 context 等步骤不变...

    # 【修改】构建 chain_input 时，把 question_type 传给 build_answer_instruction
    base_instruction = build_answer_instruction(
        context, strict_mode, documents,
        question_type=question_type,  # 新增这一行
    )

    # ...LLM 流式生成不变...

    # 【修改】done 事件里带上 question_type，方便评估
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
            "question_type": question_type,  # 新增：问题类型
        },
    }
```

---

## 阶段3 完成标准检查清单
- [ ] `build_answer_instruction` 接收 `question_type` 参数
- [ ] 5 种问题类型（yes_no/list/how_to/frequency/fact）都有专属结构要求
- [ ] 多个 chunk 命中时，Prompt 明确要求"先合并再回答，不要机械堆叠"
- [ ] direct grounded answer 中 yes_no 是"结论+依据"两段式
- [ ] direct grounded answer 中 list 类做了顿号分隔项的列点化
- [ ] 主流程的 done 事件返回了 `question_type` 字段