# 阶段1：Prompt与上下文组织

## 核心目标
让模型"更容易用好检索结果"，减少答偏、答散、答空泛。

## 涉及函数
- `format_documents_as_context(...)` - 统一context结构
- `build_langchain_rag_prompt(...)` - 构建Prompt模板
- `build_answer_instruction(...)` - 统一回答要求

---

## 1.1 format_documents_as_context 优化

### 原代码问题
1. header信息过长（document/chunk/page/section全部展示），占用模型注意力
2. score未提供给模型参考，模型不知道哪段更可信
3. 没有预留截断策略

### 优化后代码
```python
# ============================================================
# 优化后：format_documents_as_context
# 改动点：
#   1. 简化 chunk header，只保留关键信息
#   2. 增加 score 显示，让模型知道哪些段落更可信
#   3. 预留 MAX_CONTEXT_TOKENS 截断策略
#   4. 固定格式：[编号] 来源头 -> 正文 -> 空行
# ============================================================

# 预留的上下文最大字符数阈值（后续可根据模型窗口调整）
# 粗略估算：1中文 ≈ 1.5 tokens，这里用字符数先做保守截断
MAX_CONTEXT_CHARS = 12000

# 单个 chunk 正文最大长度，避免某一段过长挤占其他 chunk 空间
MAX_SINGLE_CHUNK_CHARS = 2000


def format_documents_as_context(documents: Sequence[Document]) -> str:
    """
    把 LangChain Documents 格式化成 LLM 可读的 context。

    【新版格式规范】
    每个 chunk 固定三行结构：
        [编号] 文档名 | 第N页 | 章节(可选) | 相关度: X.XX
        正文内容...
        <空行>

    【设计理由】
    1. header 尽量短，避免把模型注意力浪费在元数据上
    2. 保留"文档名+页码"，后续模型生成引用 [1][2] 时可以对应上
    3. 增加相关度分数（score），告诉模型哪段更值得信任
    4. 单 chunk 正文做截断，防止某一篇超长文档挤占全部上下文
    """
    if not documents:
        return ""

    blocks: list[str] = []
    total_chars = 0

    for index, doc in enumerate(documents, start=1):
        metadata = doc.metadata
        source_page = metadata.get("source_page")
        source_section = _format_user_facing_section(
            source_page,
            metadata.get("source_section"),
        )

        # ---------- 1. 构建简洁的来源头 ----------
        # 格式：[1] 用户手册.pdf | 第5页 | 章节：安装指南 | 相关度: 0.92
        header_parts = [
            metadata.get("document_name", "未知文档"),
        ]
        if source_page is not None:
            header_parts.append(f"第{source_page}页")
        if source_section:
            header_parts.append(f"章节：{source_section}")

        # score 归一化显示（保留2位小数）
        score = float(metadata.get("score") or metadata.get("final_score") or 0.0)
        if score > 0:
            header_parts.append(f"相关度:{score:.2f}")

        header = f"[{index}] " + " | ".join(header_parts)

        # ---------- 2. 正文截断 ----------
        content = doc.page_content.strip()
        if len(content) > MAX_SINGLE_CHUNK_CHARS:
            # 截断时保留前段和后段各一半，尽量不丢关键信息
            half = MAX_SINGLE_CHUNK_CHARS // 2
            content = content[:half] + "\n...[内容过长已截断]...\n" + content[-half:]

        # ---------- 3. 累计长度检查，超过总阈值就停止追加 ----------
        block_text = header + "\n" + content
        if total_chars + len(block_text) > MAX_CONTEXT_CHARS:
            # 再塞最后一个能放的 chunk，然后停止
            remaining = MAX_CONTEXT_CHARS - total_chars
            if remaining > 200:  # 剩余空间还能放至少200字才塞
                blocks.append(header)
                blocks.append(content[:remaining])
                blocks.append("")
            break

        total_chars += len(block_text)
        blocks.append(header)
        blocks.append(content)
        blocks.append("")  # chunk 之间空行隔开

    return "\n".join(blocks).strip()
```

---

## 1.2 build_langchain_rag_prompt 优化

### 原代码问题
1. system_prompt 太笼统，没有明确的"回答结构"要求
2. 没有强调"优先依据高相关度内容"
3. strict/non-strict 边界可以更明确

### 优化后代码
```python
# ============================================================
# 优化后：build_langchain_rag_prompt
# 改动点：
#   1. strict_mode 下指令更严厉，明确禁止编造
#   2. non-strict 下明确区分"知识库内容"和"补充内容"
#   3. 引入角色感 + 回答结构要求
#   4. 加入"多chunk整合"要求（提前为阶段3铺垫）
# ============================================================

def build_langchain_rag_prompt(strict_mode: bool) -> ChatPromptTemplate:
    """
    构建 LangChain Prompt 模板。

    【设计思路】
    Prompt 分三层：
    1. 角色层：告诉模型它是谁
    2. 规则层：strict/non-strict 的回答边界
    3. 输入层：用户问题 + 知识库上下文 + 动态回答指令
    """
    if strict_mode:
        # ========== strict_mode：绝对以知识库为准，缺证据就拒答 ==========
        system_prompt = """你是一个严谨的企业知识库问答助手，回答必须严格遵循以下规则：

【核心原则】
1. 回答必须100%基于提供的知识库上下文，绝不编造任何信息
2. 如果知识库上下文不足以回答用户问题，直接说明"知识库中未找到相关信息"
3. 优先参考"相关度"分数高的段落，低相关度内容只能作为补充
4. 多个知识库段落都提到同一内容时，要合并整理，不要机械堆叠复述

【引用规范】
- 引用具体内容时，在对应句子末尾使用 [1]、[2] 标记来源编号
- 一句话用到多个来源时，并列标注，如："功能支持A和B [1][3]"

【语气风格】
- 回答先给出结论，再补充细节解释
- 使用短句，避免长句绕弯
- 不使用"可能"、"大概"这类模糊词，除非知识库原文就是模糊表述
"""
    else:
        # ========== non-strict：知识库优先，允许补充但必须明确区分 ==========
        system_prompt = """你是一个以知识库优先的问答助手，回答必须遵循以下规则：

【核心原则】
1. 优先依据提供的知识库上下文回答，知识库有答案的就按知识库答
2. 如果知识库上下文不足以完整回答，可以基于常识谨慎补充
3. **重要：补充内容必须单独标注，明确说明"以下内容非知识库信息，仅供参考"**
4. 优先参考"相关度"分数高的段落
5. 多个知识库段落都提到同一内容时，要合并整理，不要机械堆叠复述

【引用规范】
- 引用知识库内容时，在对应句子末尾使用 [1]、[2] 标记来源编号
- 补充内容（非知识库）不要标注引用编号

【语气风格】
- 回答先给出结论，再补充细节解释
- 使用短句，避免长句绕弯
"""

    return ChatPromptTemplate.from_messages(
        [
            ("system", system_prompt),
            (
                "user",
                "用户问题：\n"
                "{question}\n\n"
                "知识库上下文：\n"
                "{context}\n\n"
                "具体回答要求：\n"
                "{answer_instruction}",
            ),
        ]
    )
```

---

## 1.3 build_answer_instruction 优化

### 原代码问题
1. 没有区分"有context但证据很弱"的情况
2. 没有提前告诉模型当前有没有可用的上下文
3. grounding instruction 位置可以更清晰

### 优化后代码
```python
# ============================================================
# 优化后：build_answer_instruction
# 改动点：
#   1. 引入 HAS_CONTEXT / NO_CONTEXT / WEAK_CONTEXT 三态判断
#   2. strict_mode 下无证据直接拒答
#   3. non-strict 下补充内容必须单独声明
#   4. 引用要求更明确
# ============================================================

# 弱证据阈值：所有 chunk 的 score 都低于这个值时，视为证据不足
WEAK_EVIDENCE_SCORE_THRESHOLD = 0.55


def _is_context_weak(context: str, documents: Sequence[Document]) -> bool:
    """
    判断当前检索到的上下文是否属于"弱证据"。

    判断逻辑：
    - 没有 documents 或没有 context → 不算弱证据，算无证据
    - 所有文档的 score 都低于 WEAK_EVIDENCE_SCORE_THRESHOLD → 弱证据
    - 否则 → 证据正常
    """
    if not context or not documents:
        return False

    scores = [
        float(doc.metadata.get("score") or doc.metadata.get("final_score") or 0.0)
        for doc in documents
    ]
    if not scores:
        return True

    # 最高分都低于阈值，说明整体证据都不强
    return max(scores) < WEAK_EVIDENCE_SCORE_THRESHOLD


def build_answer_instruction(
    context: str,
    strict_mode: bool,
    documents: Sequence[Document] | None = None,
) -> str:
    """
    根据 context 和 strict_mode 生成【动态回答要求】。

    【状态机】
    有 context 且 证据正常 → 正常回答 + 引用
    有 context 但 证据很弱 → 保守回答 + 提示证据弱
    无 context + strict=True → 直接拒答
    无 context + strict=False → 允许补充但必须声明
    """
    has_context = bool((context or "").strip())
    is_weak = _is_context_weak(context, documents or [])

    # ---------- 情况1：有上下文且证据正常 ----------
    if has_context and not is_weak:
        return (
            "当前已检索到相关知识库内容。\n"
            "请按以下步骤回答：\n"
            "1. 先直接给出结论性答案（不要铺垫废话）\n"
            "2. 再用知识库内容分点或分段解释细节\n"
            "3. 用到具体段落时，在句末标注 [1][2] 来源编号\n"
            f"4. {GROUNDING_INSTRUCTION}\n"
            "5. 如果知识库中有冲突表述，以相关度更高的为准，并说明"
        )

    # ---------- 情况2：有上下文但证据很弱 ----------
    if has_context and is_weak:
        if strict_mode:
            return (
                "当前检索到的知识库内容与问题相关性较低。\n"
                "请保守回答：\n"
                "1. 先说明"知识库中未明确提及该问题的直接答案"\n"
                "2. 如果弱相关内容有参考价值，可以简要列出并标注"仅供参考"\n"
                "3. 不要给出确定性结论"
            )
        else:
            return (
                "当前检索到的知识库内容与问题相关性较低。\n"
                "请按以下要求回答：\n"
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
        "请按以下要求回答：\n"
        "1. 先明确说明"知识库中未找到相关内容"\n"
        "2. 可以基于常识给出补充答案，但必须单独标注"以下内容非知识库信息，仅供参考"\n"
        "3. 不要使用 [1]、[2] 这类引用标记"
    )
```

---

## 阶段1 完成标准检查清单
- [ ] `format_documents_as_context` 输出格式固定：`[编号] 来源头 | 相关度` → 正文 → 空行
- [ ] `build_langchain_rag_prompt` strict/non-strict 边界明确，不会混淆
- [ ] `build_answer_instruction` 支持 4 种状态：正常证据/弱证据/无证据+strict/无证据+non-strict
- [ ] 所有新变量（MAX_CONTEXT_CHARS 等）定义清晰，后续可调整