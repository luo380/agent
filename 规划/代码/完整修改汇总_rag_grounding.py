"""
================================================================================
rag_grounding.py  —  整合后的修改版（阶段1~5全量改动）
================================================================================

【当前架构】证据与规则判断层
  - Query 轻量结构化理解：infer_question_type / understand_query / extract_question_focus_terms
  - 证据匹配分：evidence_match_score
  - 关系证据分：relation_evidence_score
  - 高置信度直接回答：build_direct_grounded_answer

【修改说明】
  主要改动集中在：
    阶段2 - 证据匹配分权重调整 + direct grounded answer 边界强化 + 关系证据
    阶段3 - direct answer 按问题类型风格化（列点/步骤化）

  原有的 QueryIntent / relation_evidence_score 核心逻辑保持稳定，
  不做大改，只补充注释和微调阈值。
================================================================================
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field


# ============================================================
# 接地规则常量
# ============================================================
GROUNDING_INSTRUCTION = (
    "如果知识库上下文已经提供能回答问题的证据，"
    "必须基于该证据直接回答；"
    "列表、枚举、频率、步骤和参数都算有效证据。"
    "只有在上下文没有相关证据时，才能回答\"知识库未提及\"。"
)
LIST_MEMBERSHIP_GROUNDING_RULE = GROUNDING_INSTRUCTION


# ============================================================
# 问题类型锚定词
# ============================================================
YES_NO_ANCHORS = (
    "是否支持", "能否支持", "支不支持", "可以支持", "能支持", "支持",
    "是否兼容", "兼容", "能用", "可以用", "能不能", "可不可以",
    "能否", "可以", "控不控", "能控", "可以控", "控制", "需要更换",
)
FREQUENCY_ANCHORS = ("多久", "多长时间", "几天", "几次", "频率")
HOW_TO_ANCHORS = ("如何", "怎么", "怎样", "如何添加", "怎么添加")
LIST_ANCHORS = ("哪些", "有哪些", "有什么", "什么")
QUESTION_WORDS = ("哪些", "什么", "多少", "如何", "怎么", "怎样")
PRODUCT_PREFIXES = ("扫地机器人", "机器人", "本产品", "设备")
ACTION_PREFIXES = (
    "添加", "连接", "设置", "绑定", "更换", "清理", "打开", "关闭",
    "使用", "控制", "控",
)
ATTRIBUTE_MODIFIERS = ("自定义", "默认", "官方", "常用")
CONVERSATIONAL_PREFIXES = (
    "我家里有", "家里有", "我这边有", "我有",
    "现在用的是", "我用的是", "我用", "我家里的", "我家的",
)
CONVERSATIONAL_FILLERS = (
    "不知道", "想知道", "请问", "问下", "问一下", "麻烦问下", "麻烦",
)
CLAUSE_SPLIT_RE = re.compile(r"[，,。；;:：、（）()\[\]【】]+")
SUPPORT_CONTEXT_TERMS = (
    "支持", "兼容", "可以使用", "可使用", "语音助手",
    "常见的有", "包括", "可通过", "能够",
)
UNSUPPORTED_CONTEXT_TERMS = ("不支持", "暂不支持", "不兼容", "无法支持")
FREQUENCY_CONTEXT_RE = re.compile(
    r"(每|至少|建议|定期|\d+\s*[-~到至]?\s*\d*\s*(次|天|周|月|年|小时|分钟))"
)
HOW_TO_CONTEXT_TERMS = (
    "打开", "进入", "点击", "选择", "设置", "添加", "绑定", "连接", "开始", "然后",
)
LIST_CONTEXT_TERMS = ("包括", "如下", "以下", "有", "、", "：", ":")
QUESTION_SUFFIX_RE = re.compile(r"[吗么呢啊？?。.，,!！]+$")


# ============================================================
# 阶段2 新增常量：direct grounded answer 触发阈值
# ============================================================
DIRECT_GROUNDED_EVIDENCE_THRESHOLD = 0.92
DIRECT_GROUNDED_RELATION_THRESHOLD = 0.55

# evidence_match_score 权重（阶段2 调整）
EVIDENCE_BASE_SCORE = 0.45
EVIDENCE_CUE_REWARD = 0.55
MAX_MATCHED_TERMS = 3


def normalize_for_grounding(text: str) -> str:
    """归一化：去所有空白 + 转小写，方便字符串匹配。"""
    return re.sub(r"\s+", "", (text or "")).lower()


def infer_question_type(question: str) -> str:
    """
    根据关键词识别问题类型。
    返回：frequency / how_to / list / yes_no / fact
    （优先级从上到下）
    """
    normalized = normalize_for_grounding(question)
    if any(anchor in normalized for anchor in FREQUENCY_ANCHORS):
        return "frequency"
    if any(anchor in normalized for anchor in HOW_TO_ANCHORS):
        return "how_to"
    if any(anchor in normalized for anchor in LIST_ANCHORS):
        return "list"
    if (any(anchor in normalized for anchor in YES_NO_ANCHORS)
            or normalized.endswith(("吗", "?", "？"))):
        return "yes_no"
    return "fact"


def _strip_product_prefix(term: str) -> str:
    for prefix in PRODUCT_PREFIXES:
        if term.startswith(prefix) and len(term) > len(prefix) + 1:
            return term[len(prefix):]
    return term


def _clean_focus(term: str) -> str:
    term = QUESTION_SUFFIX_RE.sub("", term or "")
    term = CLAUSE_SPLIT_RE.sub("", term)
    for filler in CONVERSATIONAL_FILLERS:
        term = term.replace(filler, "")
    all_anchors = (
        QUESTION_WORDS + YES_NO_ANCHORS + FREQUENCY_ANCHORS
        + HOW_TO_ANCHORS + LIST_ANCHORS
    )
    for word in all_anchors:
        term = term.replace(word, "")
    for prefix in CONVERSATIONAL_PREFIXES:
        if term.startswith(prefix) and len(term) > len(prefix) + 1:
            term = term[len(prefix):]
    return _strip_product_prefix(term.strip())


def _add_unique_term(terms: list[str], value: str) -> None:
    if 2 <= len(value) <= 40 and value not in terms:
        terms.append(value)


def _append_term(terms: list[str], value: str) -> None:
    value = _clean_focus(value)
    candidates = [value]
    for prefix in ACTION_PREFIXES:
        if value.startswith(prefix) and len(value) > len(prefix) + 1:
            candidates.append(value[len(prefix):])
    for candidate in list(candidates):
        for modifier in ATTRIBUTE_MODIFIERS:
            if modifier in candidate and len(candidate) > len(modifier) + 1:
                candidates.append(candidate.replace(modifier, ""))
        if candidate.endswith("一次") and len(candidate) > 4:
            candidates.append(candidate[:-2])
    for candidate in candidates:
        _add_unique_term(terms, candidate)


def extract_question_focus_terms(question: str) -> list[str]:
    """从用户问题中提取用于匹配知识库的关键词列表。"""
    normalized = normalize_for_grounding(question)
    if not normalized:
        return []
    question_type = infer_question_type(normalized)
    terms: list[str] = []

    anchor_groups = {
        "yes_no": YES_NO_ANCHORS,
        "frequency": FREQUENCY_ANCHORS,
        "how_to": HOW_TO_ANCHORS,
        "list": LIST_ANCHORS,
    }
    anchors = anchor_groups.get(question_type, ())
    for anchor in anchors:
        anchor_index = normalized.find(anchor)
        if anchor_index < 0:
            continue
        if question_type in {"yes_no", "how_to", "frequency", "list"}:
            _append_term(terms, normalized[:anchor_index])
            _append_term(terms, normalized[anchor_index + len(anchor):])
        break

    for fragment in CLAUSE_SPLIT_RE.split(question or ""):
        _append_term(terms, fragment)
    _append_term(terms, normalized)
    return terms


# ============================================================
# 结构化 Query Understanding
# ============================================================
@dataclass
class QueryIntent:
    """
    轻量结构化 Query 理解结果。

    当前用途：
      1. relation_evidence_score：判断"主体-关系-客体"是否真的共现
      2. build_direct_grounded_answer：yes_no 问题的关系证据补强
    """
    question_type: str
    subject_terms: list[str] = field(default_factory=list)
    object_terms: list[str] = field(default_factory=list)
    relation: str = ""
    focus_terms: list[str] = field(default_factory=list)
    normalized_query: str = ""
    original_query: str = ""


RELATION_SYNONYM_GROUPS: dict[str, tuple[str, ...]] = {
    "支持": ("支持", "兼容", "适用", "能用", "可以用"),
    "连接": ("连接", "接入", "联网", "配网", "绑定", "配对", "连"),
    "控制": ("控制", "操控", "联动", "管理", "操作"),
    "包含": ("包含", "包括", "提供", "带有"),
    "设置": ("设置", "配置", "添加", "开启", "关闭", "修改"),
}


def _collect_fragment_terms(fragment: str) -> list[str]:
    terms: list[str] = []
    cleaned = _clean_focus(fragment)
    if cleaned:
        terms.append(cleaned)
    for term in extract_question_focus_terms(fragment):
        if term not in terms:
            terms.append(term)
    return terms[:3]


def _match_relation(normalized_question: str) -> tuple[str, str]:
    if not normalized_question:
        return "", ""
    for canonical_relation, aliases in RELATION_SYNONYM_GROUPS.items():
        for alias in sorted(aliases, key=len, reverse=True):
            if alias in normalized_question:
                return canonical_relation, alias
    return "", ""


def _build_normalized_query(
    normalized_question: str,
    relation: str,
    subject_terms: list[str],
    object_terms: list[str],
    focus_terms: list[str],
) -> str:
    if subject_terms and object_terms and relation:
        return f"{subject_terms[0]} {relation} {object_terms[0]}"
    if subject_terms and object_terms:
        return f"{subject_terms[0]} {object_terms[0]}"
    if focus_terms:
        return " ".join(focus_terms[:3])
    return normalized_question


def understand_query(question: str) -> QueryIntent:
    """【核心函数】对用户问题做轻量结构化理解。"""
    normalized_question = normalize_for_grounding(question)
    question_type = infer_question_type(question)
    focus_terms = extract_question_focus_terms(question)
    if not normalized_question:
        return QueryIntent(
            question_type=question_type,
            focus_terms=focus_terms,
            normalized_query="",
            original_query=question,
        )

    relation, matched_relation = _match_relation(normalized_question)
    subject_terms: list[str] = []
    object_terms: list[str] = []

    if matched_relation and matched_relation in normalized_question:
        left, right = normalized_question.split(matched_relation, 1)
        subject_terms = _collect_fragment_terms(left)
        object_terms = _collect_fragment_terms(right)

    if not subject_terms and focus_terms:
        subject_terms = [focus_terms[0]]
    if not object_terms and len(focus_terms) >= 2:
        object_terms = focus_terms[1:3]

    normalized_query = _build_normalized_query(
        normalized_question=normalized_question,
        relation=relation,
        subject_terms=subject_terms,
        object_terms=object_terms,
        focus_terms=focus_terms,
    )
    return QueryIntent(
        question_type=question_type,
        subject_terms=subject_terms,
        object_terms=object_terms,
        relation=relation,
        focus_terms=focus_terms,
        normalized_query=normalized_query,
        original_query=question,
    )


# ============================================================
# 关系证据分
# ============================================================
RELATION_EVIDENCE_WINDOW_SIZE = 180


def _relation_evidence_windows(
    normalized_text: str,
    *,
    subject_terms: list[str],
    object_terms: list[str],
) -> list[str]:
    """
    围绕主体/客体截取局部窗口。
    避免"主体在A段、客体在B段、关系词在C段"被误判为同一关系。
    """
    windows: list[str] = []
    seen: set[str] = set()
    anchor_terms = object_terms[:2] + subject_terms[:2]
    for term in anchor_terms:
        start = normalized_text.find(term)
        if start < 0:
            continue
        window = normalized_text[
            max(0, start - RELATION_EVIDENCE_WINDOW_SIZE):
            start + len(term) + RELATION_EVIDENCE_WINDOW_SIZE
        ]
        if window and window not in seen:
            seen.add(window)
            windows.append(window)
    return windows or [normalized_text]


def _relation_score_in_window(
    *,
    intent: QueryIntent,
    normalized_window: str,
) -> float:
    subject_hit = any(term in normalized_window for term in intent.subject_terms[:2])
    object_hit = any(term in normalized_window for term in intent.object_terms[:2])
    relation_aliases = RELATION_SYNONYM_GROUPS.get(intent.relation, ())
    relation_hit = (
        intent.relation in normalized_window
        or any(alias in normalized_window for alias in relation_aliases)
    )
    score = 0.0
    if subject_hit:
        score += 0.25
    if object_hit:
        score += 0.35
    if relation_hit:
        score += 0.40
    if subject_hit and object_hit and relation_hit:
        score += 0.15
    if intent.question_type == "yes_no" and object_hit:
        if any(term in normalized_window
               for term in SUPPORT_CONTEXT_TERMS + UNSUPPORTED_CONTEXT_TERMS):
            score += 0.15
    return min(score, 1.0)


def relation_evidence_score(question: str, text: str) -> float:
    """
    关系证据分：检查"主体-关系-客体"在局部窗口内是否共现。

    分值建议：
      >= 0.80 强；>= 0.55 中；< 0.30 弱
    """
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


# ============================================================
# 证据匹配分（阶段2 调整权重）
# ============================================================
def _evidence_window(term: str, context: str) -> str:
    normalized_context = normalize_for_grounding(context)
    term_index = normalized_context.find(term)
    if term_index < 0:
        return ""
    return normalized_context[
        max(0, term_index - 120): term_index + len(term) + 120
    ]


def _context_cue_score(question_type: str, evidence_window: str) -> float:
    if not evidence_window:
        return 0.0
    if question_type == "yes_no":
        return 1.0 if any(
            term in evidence_window
            for term in SUPPORT_CONTEXT_TERMS + UNSUPPORTED_CONTEXT_TERMS
        ) else 0.0
    if question_type == "frequency":
        return 1.0 if FREQUENCY_CONTEXT_RE.search(evidence_window) else 0.0
    if question_type == "how_to":
        return 1.0 if any(
            term in evidence_window for term in HOW_TO_CONTEXT_TERMS
        ) else 0.0
    if question_type == "list":
        return 1.0 if any(
            term in evidence_window for term in LIST_CONTEXT_TERMS
        ) else 0.0
    return 0.5


def evidence_match_score(question: str, text: str) -> float:
    """
    阶段2 优化版。
    基础分下调（0.45），线索奖励上调（0.55）。
    yes_no 类问题额外叠加关系证据分。
    """
    terms = extract_question_focus_terms(question)
    if not terms:
        return 0.0

    question_type = infer_question_type(question)
    normalized_text = normalize_for_grounding(text)
    best_score = 0.0

    matched_count = 0
    for term in terms:
        if matched_count >= MAX_MATCHED_TERMS:
            break
        if term not in normalized_text:
            continue
        matched_count += 1
        window = _evidence_window(term, text)
        cue_score = _context_cue_score(question_type, window)

        term_score = EVIDENCE_BASE_SCORE + cue_score * EVIDENCE_CUE_REWARD

        # yes_no：叠加关系证据
        if question_type == "yes_no":
            rel_score = relation_evidence_score(question, text)
            if rel_score > 0:
                term_score = term_score * 0.6 + rel_score * 0.4

        best_score = max(best_score, term_score)

    return min(best_score, 1.0)


# ============================================================
# 阶段3 新增：list / how_to 片段格式化
# ============================================================
def _format_list_snippet(snippet: str) -> str:
    """把顿号分隔的 list 片段格式化成编号列点。"""
    if "、" not in snippet:
        return snippet
    colon_split = re.split(r"[：:]", snippet, maxsplit=1)
    if len(colon_split) == 2:
        prefix, body = colon_split
    else:
        prefix = "知识库中列出的相关内容"
        body = snippet
    items_raw = re.split(r"[、,，]", body.strip().rstrip("。.!！"))
    items = [it.strip() for it in items_raw if it.strip()]
    if len(items) < 2:
        return snippet
    formatted = "\n".join(f"{i+1}. {it}" for i, it in enumerate(items))
    return f"{prefix}：\n{formatted}"


def _format_howto_snippet(snippet: str) -> str:
    """把含"首先/然后/步骤"的 how_to 片段格式化成步骤化。"""
    step_words = ["首先", "第一步", "步骤1", "步骤一", "1、", "1."]
    if not any(w in snippet for w in step_words):
        return snippet
    sentences = [s.strip() for s in re.split(r"[。.;；]", snippet) if s.strip()]
    if len(sentences) < 2:
        return snippet
    formatted = "\n".join(
        f"步骤{i+1}：{s}" for i, s in enumerate(sentences[:5])
    )
    return f"可以按以下步骤操作：\n{formatted}"


def _extract_snippet(question: str, context: str) -> str:
    """抽取含命中关键词的第一行作为答案片段（最多220字）。"""
    terms = extract_question_focus_terms(question)
    lines = [line.strip() for line in (context or "").splitlines() if line.strip()]
    if not lines:
        return ""
    for term in terms:
        for line in lines:
            if term in normalize_for_grounding(line):
                return line[:220]
    return lines[0][:220]


def _detect_yes_no_conflict(evidence_windows: list[str]) -> str | None:
    """yes_no 类问题是否同时出现支持和不支持的表述。"""
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


# ============================================================
# 阶段2 + 阶段3 优化：build_direct_grounded_answer
# ============================================================
def build_direct_grounded_answer(question: str, context: str) -> str:
    """
    尝试根据知识库直接生成高置信度答案。
    证据不够时返回空串，交给上层走 LLM。

    阶段2 改动：
      - 综合 evidence_match_score + relation_evidence_score
      - yes_no 增加冲突检测
    阶段3 改动：
      - yes_no：结论先行 + 依据
      - list：自动列点化
      - how_to：自动步骤化
      - frequency：频率结论先行
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

    # ---------- yes_no ----------
    if question_type == "yes_no":
        rel_score = relation_evidence_score(question, context)
        intent = understand_query(question)
        if intent.relation and rel_score < DIRECT_GROUNDED_RELATION_THRESHOLD:
            return ""

        all_evidence_windows = [
            _evidence_window(t, context)
            for t in terms[:3]
            if _evidence_window(t, context)
        ]
        all_evidence_windows.append(normalize_for_grounding(context))

        if _detect_yes_no_conflict(all_evidence_windows) == "conflict":
            return ""  # 有冲突，不给确定性结论

        if any(item in evidence_window for item in UNSUPPORTED_CONTEXT_TERMS):
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

    # ---------- 其他类型：抽取 snippet + 格式化 ----------
    snippet = _extract_snippet(question, context)
    if not snippet:
        return ""

    if question_type == "frequency":
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

    return f"知识库中提到：{snippet}"


# ============================================================
# 向后兼容别名（阶段5：加提醒）
# 新代码请直接使用上面的正式函数名。
# ============================================================
SUPPORT_QUERY_ANCHORS = YES_NO_ANCHORS
LIST_MEMBERSHIP_GROUNDING_RULE = GROUNDING_INSTRUCTION
extract_support_question_item = (
    lambda question: (extract_question_focus_terms(question) or [""])[0]
)
support_item_in_text = lambda question, text: bool(evidence_match_score(question, text))
build_direct_support_answer = build_direct_grounded_answer