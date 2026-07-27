# RAG 问答系统的"知识接地"模块：判断知识库文本能否回答用户问题，并可直接生成简短答案。
from __future__ import annotations

import re

# 给大模型的回答规则指令：必须基于已有证据回答，缺少证据时回复"知识库未提及"。
GROUNDING_INSTRUCTION = (
    "\u5982\u679c\u77e5\u8bc6\u5e93\u4e0a\u4e0b\u6587\u5df2\u7ecf\u63d0\u4f9b\u80fd\u56de\u7b54\u95ee\u9898\u7684\u8bc1\u636e\uff0c"
    "\u5fc5\u987b\u57fa\u4e8e\u8be5\u8bc1\u636e\u76f4\u63a5\u56de\u7b54\uff1b"
    "\u5217\u8868\u3001\u679a\u4e3e\u3001\u9891\u7387\u3001\u6b65\u9aa4\u548c\u53c2\u6570\u90fd\u7b97\u6709\u6548\u8bc1\u636e\u3002"
    "\u53ea\u6709\u5728\u4e0a\u4e0b\u6587\u6ca1\u6709\u76f8\u5173\u8bc1\u636e\u65f6\uff0c\u624d\u80fd\u56de\u7b54\u77e5\u8bc6\u5e93\u672a\u63d0\u53ca\u3002"
)
# 另一个别名，供"列表成员查询"场景使用。
LIST_MEMBERSHIP_GROUNDING_RULE = GROUNDING_INSTRUCTION

# 用于识别"是/否类问题"的关键词，例如"是否支持WiFi？""兼容iPhone吗？"
YES_NO_ANCHORS = (
    "\u662f\u5426\u652f\u6301",
    "\u80fd\u5426\u652f\u6301",
    "\u652f\u4e0d\u652f\u6301",
    "\u53ef\u4ee5\u652f\u6301",
    "\u80fd\u652f\u6301",
    "\u652f\u6301",
    "\u662f\u5426\u517c\u5bb9",
    "\u517c\u5bb9",
    "\u80fd\u7528",
    "\u53ef\u4ee5\u7528",
    "\u9700\u8981\u66f4\u6362",
)
# 用于识别"频率/时间类问题"的关键词，例如"多久清洗一次？"
FREQUENCY_ANCHORS = (
    "\u591a\u4e45",
    "\u591a\u957f\u65f6\u95f4",
    "\u51e0\u5929",
    "\u51e0\u6b21",
    "\u9891\u7387",
)
# 用于识别"怎么做/操作步骤类问题"的关键词，例如"如何连接WiFi？"
HOW_TO_ANCHORS = ("\u5982\u4f55", "\u600e\u4e48", "\u600e\u6837", "\u5982\u4f55\u6dfb\u52a0", "\u600e\u4e48\u6dfb\u52a0")
# 用于识别"列表/列举类问题"的关键词，例如"有哪些功能？"
LIST_ANCHORS = ("\u54ea\u4e9b", "\u6709\u54ea\u4e9b", "\u6709\u4ec0\u4e48", "\u4ec0\u4e48")
# 通用疑问词列表，后续清洗关键词时会把它们从文本中移除。
QUESTION_WORDS = ("\u54ea\u4e9b", "\u4ec0\u4e48", "\u591a\u5c11", "\u5982\u4f55", "\u600e\u4e48", "\u600e\u6837")
# 产品类前缀，如"扫地机器人"，提取关键词时会被剥掉，露出真正的主体。
PRODUCT_PREFIXES = ("\u626b\u5730\u673a\u5668\u4eba", "\u673a\u5668\u4eba", "\u672c\u4ea7\u54c1", "\u8bbe\u5907")
# 动作类前缀，如"添加""连接"，提取关键词时会被剥掉，露出真正的主体。
ACTION_PREFIXES = ("\u6dfb\u52a0", "\u8fde\u63a5", "\u8bbe\u7f6e", "\u7ed1\u5b9a", "\u66f4\u6362", "\u6e05\u7406", "\u6253\u5f00", "\u5173\u95ed", "\u4f7f\u7528")
# 属性修饰词，如"默认""自定义"，提取关键词时会被剥掉，露出真正的主体。
ATTRIBUTE_MODIFIERS = ("\u81ea\u5b9a\u4e49", "\u9ed8\u8ba4", "\u5b98\u65b9", "\u5e38\u7528")
# 知识库上下文中出现这些词，说明是"支持"的证据（用于 yes_no 类问题）。
SUPPORT_CONTEXT_TERMS = (
    "\u652f\u6301", "\u517c\u5bb9", "\u53ef\u4ee5\u4f7f\u7528", "\u53ef\u4f7f\u7528", "\u8bed\u97f3\u52a9\u624b",
    "\u5e38\u89c1\u7684\u6709", "\u5305\u62ec", "\u53ef\u901a\u8fc7", "\u80fd\u591f"
)
# 知识库上下文中出现这些词，说明是"不支持"的证据（用于 yes_no 类问题）。
UNSUPPORTED_CONTEXT_TERMS = ("\u4e0d\u652f\u6301", "\u6682\u4e0d\u652f\u6301", "\u4e0d\u517c\u5bb9", "\u65e0\u6cd5\u652f\u6301")
# 匹配"每3天""至少1次""3~5次""建议每2周"这类频率描述的正则。
FREQUENCY_CONTEXT_RE = re.compile(r"(\u6bcf|\u81f3\u5c11|\u5efa\u8bae|\u5b9a\u671f|\d+\s*[-~\u5230\u81f3]?\s*\d*\s*(\u6b21|\u5929|\u5468|\u6708|\u5e74|\u5c0f\u65f6|\u5206\u949f))")
# "怎么做"类问题上下文中出现这些词，说明是操作步骤证据（打开→点击→设置...）。
HOW_TO_CONTEXT_TERMS = ("\u6253\u5f00", "\u8fdb\u5165", "\u70b9\u51fb", "\u9009\u62e9", "\u8bbe\u7f6e", "\u6dfb\u52a0", "\u7ed1\u5b9a", "\u8fde\u63a5", "\u5f00\u59cb", "\u7136\u540e")
# "列表"类问题上下文中出现这些词，说明是列举证据（包括、以下、顿号、冒号等）。
LIST_CONTEXT_TERMS = ("\u5305\u62ec", "\u5982\u4e0b", "\u4ee5\u4e0b", "\u6709", "\u3001", "\uff1a", ":")
# 去除问题末尾语气词/标点的正则：吗、么、呢、？、。、！、，等。
QUESTION_SUFFIX_RE = re.compile(r"[\u5417\u4e48\u561b\u5462\uff1f?\u3002\.\uff0c,\uff01!]+$")


# 把文本归一化：去除所有空白、转小写，方便后续字符串匹配。
def normalize_for_grounding(text: str) -> str:
    return re.sub(r"\s+", "", (text or "")).lower()


# 根据问题中的关键词识别问题类型，返回 frequency/how_to/list/yes_no/fact 之一。
def infer_question_type(question: str) -> str:
    normalized = normalize_for_grounding(question)
    if any(anchor in normalized for anchor in FREQUENCY_ANCHORS):
        return "frequency"
    if any(anchor in normalized for anchor in HOW_TO_ANCHORS):
        return "how_to"
    if any(anchor in normalized for anchor in LIST_ANCHORS):
        return "list"
    if any(anchor in normalized for anchor in YES_NO_ANCHORS) or normalized.endswith(("\u5417", "?", "\uff1f")):
        return "yes_no"
    return "fact"


# 去除产品类前缀（如"扫地机器人xxx" → "xxx"），让关键词更聚焦。
def _strip_product_prefix(term: str) -> str:
    for prefix in PRODUCT_PREFIXES:
        if term.startswith(prefix) and len(term) > len(prefix) + 1:
            return term[len(prefix):]
    return term


# 清洗候选关键词：去掉语气词/标点、去掉疑问词、去掉产品前缀。
def _clean_focus(term: str) -> str:
    term = QUESTION_SUFFIX_RE.sub("", term or "")
    for word in QUESTION_WORDS + YES_NO_ANCHORS + FREQUENCY_ANCHORS + HOW_TO_ANCHORS + LIST_ANCHORS:
        term = term.replace(word, "")
    return _strip_product_prefix(term.strip())


# 把 value 加入 terms：长度限制 2~40，并且去重。
def _add_unique_term(terms: list[str], value: str) -> None:
    if 2 <= len(value) <= 40 and value not in terms:
        terms.append(value)


# 对 value 做"变体展开"（去掉动作前缀、修饰词、尾部的"一次"），然后逐一加入 terms。
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
        if candidate.endswith("\u4e00\u6b21") and len(candidate) > 4:
            candidates.append(candidate[:-2])

    for candidate in candidates:
        _add_unique_term(terms, candidate)


# 【核心函数】从用户问题中提取用于匹配知识库的关键词列表。先归一化、识别类型，
# 再围绕锚定词前后切片提取关键词，并兜底用整句再提取一次。
def extract_question_focus_terms(question: str) -> list[str]:
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
        if question_type in {"yes_no", "how_to"}:
            _append_term(terms, normalized[anchor_index + len(anchor):])
        if question_type in {"frequency", "list"}:
            _append_term(terms, normalized[:anchor_index])
            _append_term(terms, normalized[anchor_index + len(anchor):])
        break

    _append_term(terms, normalized)
    return terms


# 在知识库中找到 term 的位置后，截取前后 ±120 字符的"证据窗口"——只有关键词附近的上下文才重要。
def _evidence_window(term: str, context: str) -> str:
    normalized_context = normalize_for_grounding(context)
    term_index = normalized_context.find(term)
    if term_index < 0:
        return ""
    return normalized_context[max(0, term_index - 120): term_index + len(term) + 120]


# 根据问题类型 + 证据窗口打分：窗口中出现对应关键词则返回 1.0，无则 0.0，事实类兜底 0.5。
def _context_cue_score(question_type: str, evidence_window: str) -> float:
    if not evidence_window:
        return 0.0
    if question_type == "yes_no":
        return 1.0 if any(term in evidence_window for term in SUPPORT_CONTEXT_TERMS + UNSUPPORTED_CONTEXT_TERMS) else 0.0
    if question_type == "frequency":
        return 1.0 if FREQUENCY_CONTEXT_RE.search(evidence_window) else 0.0
    if question_type == "how_to":
        return 1.0 if any(term in evidence_window for term in HOW_TO_CONTEXT_TERMS) else 0.0
    if question_type == "list":
        return 1.0 if any(term in evidence_window for term in LIST_CONTEXT_TERMS) else 0.0
    return 0.5


# 【对外核心函数】判断 text 能否作为回答 question 的证据，返回 0~1 分数。
# 计分规则：关键词不在 text 中 → 0；关键词在 text 中 → 基础分 0.65 + 上下文线索奖励 0.35。
def evidence_match_score(question: str, text: str) -> float:
    terms = extract_question_focus_terms(question)
    if not terms:
        return 0.0

    question_type = infer_question_type(question)
    normalized_text = normalize_for_grounding(text)
    best_score = 0.0
    for term in terms:
        if term not in normalized_text:
            continue
        cue_score = _context_cue_score(question_type, _evidence_window(term, text))
        best_score = max(best_score, 0.65 + cue_score * 0.35)
    return min(best_score, 1.0)


# 从知识库中抽取命中关键词的第一行作为答案片段（最多 220 字），都没命中则返回第一段。
def _extract_snippet(question: str, context: str) -> str:
    terms = extract_question_focus_terms(question)
    lines = [line.strip() for line in (context or "").splitlines() if line.strip()]
    if not lines:
        return ""

    for term in terms:
        for line in lines:
            if term in normalize_for_grounding(line):
                return line[:220]

    return lines[0][:220]


# 【对外核心函数】尝试根据知识库 context 直接生成问题 question 的简短答案。
# 若证据分 < 0.9 则返回空字符串（交给上层走大模型）；
# yes_no 类根据证据窗口判断"支持/不支持"；其他类抽取知识库片段拼装回答。
def build_direct_grounded_answer(question: str, context: str) -> str:
    question_type = infer_question_type(question)
    terms = extract_question_focus_terms(question)
    if not terms or evidence_match_score(question, context) < 0.9:
        return ""

    term = terms[0]
    evidence_window = _evidence_window(term, context)
    if question_type == "yes_no":
        if any(item in evidence_window for item in UNSUPPORTED_CONTEXT_TERMS):
            return f"\u4e0d\u652f\u6301{term}\u3002\u77e5\u8bc6\u5e93\u4e0a\u4e0b\u6587\u4e2d\u6709\u4e0d\u652f\u6301\u6216\u4e0d\u517c\u5bb9{term}\u7684\u8bf4\u660e\u3002"
        if any(item in evidence_window for item in SUPPORT_CONTEXT_TERMS):
            return f"\u652f\u6301{term}\u3002\u77e5\u8bc6\u5e93\u4e0a\u4e0b\u6587\u4e2d\u5df2\u5c06{term}\u5217\u4e3a\u652f\u6301\u7684\u9879\u76ee\u3002"
        return ""

    snippet = _extract_snippet(question, context)
    if not snippet:
        return ""
    if question_type == "frequency":
        return f"\u77e5\u8bc6\u5e93\u4e2d\u63d0\u5230\uff1a{snippet}"
    if question_type == "how_to":
        return f"\u53ef\u4ee5\u6309\u77e5\u8bc6\u5e93\u4e2d\u7684\u8bf4\u660e\u64cd\u4f5c\uff1a{snippet}"
    if question_type == "list":
        return f"\u77e5\u8bc6\u5e93\u4e2d\u5217\u51fa\u7684\u76f8\u5173\u5185\u5bb9\u662f\uff1a{snippet}"
    return f"\u77e5\u8bc6\u5e93\u4e2d\u63d0\u5230\uff1a{snippet}"


# Backward-compatible aliases for older call sites while the rest of the app migrates.
SUPPORT_QUERY_ANCHORS = YES_NO_ANCHORS
LIST_MEMBERSHIP_GROUNDING_RULE = GROUNDING_INSTRUCTION
extract_support_question_item = lambda question: (extract_question_focus_terms(question) or [""])[0]
support_item_in_text = lambda question, text: bool(evidence_match_score(question, text))
build_direct_support_answer = build_direct_grounded_answer