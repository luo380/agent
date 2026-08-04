# RAG 问答系统的"知识接地"模块：判断知识库文本能否回答用户问题，并可直接生成简短答案。
from __future__ import annotations

import re
from dataclasses import dataclass, field

"""
这个模块是 RAG（检索增强生成）问答系统的"知识接地"模块，核心作用是：判断知识库中的文本能否回答用户的问题，并在证据充分时直接生成简短答案，无需调用大模型。
"""
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
    "\u80fd\u4e0d\u80fd",
    "\u53ef\u4e0d\u53ef\u4ee5",
    "\u80fd\u5426",
    "\u53ef\u4ee5",
    "\u63a7\u4e0d\u63a7",
    "\u80fd\u63a7",
    "\u53ef\u4ee5\u63a7",
    "\u63a7\u5236",
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
ACTION_PREFIXES = (
    "\u6dfb\u52a0",
    "\u8fde\u63a5",
    "\u8bbe\u7f6e",
    "\u7ed1\u5b9a",
    "\u66f4\u6362",
    "\u6e05\u7406",
    "\u6253\u5f00",
    "\u5173\u95ed",
    "\u4f7f\u7528",
    "\u63a7\u5236",
    "\u63a7",
)
# 属性修饰词，如"默认""自定义"，提取关键词时会被剥掉，露出真正的主体。
ATTRIBUTE_MODIFIERS = ("\u81ea\u5b9a\u4e49", "\u9ed8\u8ba4", "\u5b98\u65b9", "\u5e38\u7528")
CONVERSATIONAL_PREFIXES = (
    "\u6211\u5bb6\u91cc\u6709",
    "\u5bb6\u91cc\u6709",
    "\u6211\u8fd9\u8fb9\u6709",
    "\u6211\u6709",
    "\u73b0\u5728\u7528\u7684\u662f",
    "\u6211\u7528\u7684\u662f",
    "\u6211\u7528",
    "\u6211\u5bb6\u91cc\u7684",
    "\u6211\u5bb6\u7684",
)
CONVERSATIONAL_FILLERS = (
    "\u4e0d\u77e5\u9053",
    "\u60f3\u77e5\u9053",
    "\u8bf7\u95ee",
    "\u95ee\u4e0b",
    "\u95ee\u4e00\u4e0b",
    "\u9ebb\u70e6\u95ee\u4e0b",
    "\u9ebb\u70e6",
)
CLAUSE_SPLIT_RE = re.compile(r"[\uff0c,\u3002\uff1b;:\uff1a\u3001\uff08\uff09()\[\]\u3010\u3011]+")
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
    term = CLAUSE_SPLIT_RE.sub("", term)
    for filler in CONVERSATIONAL_FILLERS:
        term = term.replace(filler, "")
    for word in QUESTION_WORDS + YES_NO_ANCHORS + FREQUENCY_ANCHORS + HOW_TO_ANCHORS + LIST_ANCHORS:
        term = term.replace(word, "")
    for prefix in CONVERSATIONAL_PREFIXES:
        if term.startswith(prefix) and len(term) > len(prefix) + 1:
            term = term[len(prefix):]
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
            _append_term(terms, normalized[:anchor_index])
            _append_term(terms, normalized[anchor_index + len(anchor):])
        if question_type in {"frequency", "list"}:
            _append_term(terms, normalized[:anchor_index])
            _append_term(terms, normalized[anchor_index + len(anchor):])
        break

    for fragment in CLAUSE_SPLIT_RE.split(question or ""):
        _append_term(terms, fragment)

    _append_term(terms, normalized)
    return terms


"""
# ============================================================
# 【新增】结构化 Query Understanding
# 作用：
# 1. 把自然语言问题拆成 question_type / subject / object / relation
# 2. 给 query rewrite 提供更稳定的结构化输入
# 3. 给 retrieval rerank 提供“关系是否真的命中”的额外证据分
# ============================================================
"""
@dataclass
class QueryIntent:
    # 问题类型：yes_no / frequency / how_to / list / fact
    question_type: str
    # 主体实体：通常是“设备 / 产品 / 主对象”
    subject_terms: list[str] = field(default_factory=list)
    # 客体实体：通常是“能力 / 功能 / 属性 / 约束对象”
    object_terms: list[str] = field(default_factory=list)
    # 规范化关系词：支持 / 连接 / 控制 / 包含 / 设置
    relation: str = ""
    # 原有焦点词抽取结果，继续复用
    focus_terms: list[str] = field(default_factory=list)
    # 规范化后的主检索式
    normalized_query: str = ""
    # 原始问题，方便调试和兜底
    original_query: str = ""
# 关系词分组：
# key 是“规范关系词”，value 是实际问法里可能出现的多种口语表达
RELATION_SYNONYM_GROUPS: dict[str, tuple[str, ...]] = {
    "支持": ("支持", "兼容", "适用", "能用", "可以用"),
    "连接": ("连接", "接入", "联网", "配网", "绑定", "配对", "连"),
    "控制": ("控制", "操控", "联动", "管理", "操作"),
    "包含": ("包含", "包括", "提供", "带有"),
    "设置": ("设置", "配置", "添加", "开启", "关闭", "修改"),
}

def _collect_fragment_terms(fragment: str) -> list[str]:
    """
    从“关系词前后片段”里抽更稳定的实体词。
    这里不做复杂分词，只复用当前项目已经有的清洗逻辑和 focus 逻辑。
    """
    terms: list[str] = []

    cleaned = _clean_focus(fragment)
    if cleaned:
        terms.append(cleaned)
    for term in extract_question_focus_terms(fragment):
        if term not in terms:
            terms.append(term)

    # 只保留前 3 个关键词
    return terms[:3]


def _match_relation(normalized_question: str) -> tuple[str, str]:
    """
    在问题里识别关系词。
    返回：
    - 规范关系词（例如“连接”）
    - 实际命中的原始关系词（例如“配网”）
    """
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
    """
    构建更像“标准检索问法”的查询式。
    优先级：
    1. subject + relation + object
    2. subject + object
    3. focus_terms 拼接
    4. 原始归一化问题兜底
    """
    # 优先级：subject + relation + object 主语 + 关系 + 宾语都有时，优先使用这个组合
    if subject_terms and object_terms and relation:
        return f"{subject_terms[0]} {relation} {object_terms[0]}"
    # 优先级：subject + object 主语 + 宾语都有时，优先使用这个组合
    if subject_terms and object_terms:
        return f"{subject_terms[0]} {object_terms[0]}"
    # 优先级：focus_terms 关键词组，通常包含主语、宾语、关系词
    if focus_terms:
        return " ".join(focus_terms[:3])
    # 优先级：原始归一化问题兜底
    return normalized_question


def understand_query(question: str) -> QueryIntent:
    """
    【核心函数】对用户问题做轻量结构化理解。

    目标不是做到 NLP 级完美解析，
    而是给当前项目提供“足够稳、足够便宜”的结构化输入。
    """
    # 问题归一化
    normalized_question = normalize_for_grounding(question)
    # 问题类型识别
    # 优先级：yes_no / frequency / how_to / list / fact
    # 优先级：其他问题类型
    # 优先级：兜底
    question_type = infer_question_type(question)
    # 问题主体实体识别
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

    # 如果识别到了关系词，就优先用“关系词前后切片”抽主体 / 客体
    if matched_relation and matched_relation in normalized_question:
        left, right = normalized_question.split(matched_relation, 1)
        subject_terms = _collect_fragment_terms(left)
        object_terms = _collect_fragment_terms(right)

    # 如果切片不够稳定，就退回到现有 focus_terms
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
        question_type=question_type,  # 问题类型
        subject_terms=subject_terms,  # 主语
        object_terms=object_terms,  # 宾语
        relation=relation,  # 关系
        focus_terms=focus_terms,     # 关键词组
        normalized_query=normalized_query,  # 归一化查询
        original_query=question,  # 原始问题
        )

# 关系证据窗口大小：
# 不是在全文里“只要出现过就算命中”，
# 而是围绕主体 / 客体截一个局部窗口，判断它们是不是在同一段语义范围内一起出现。
RELATION_EVIDENCE_WINDOW_SIZE = 180


def _relation_evidence_windows(
    normalized_text: str,
    *,
    subject_terms: list[str],
    object_terms: list[str],
) -> list[str]:
    """
    围绕主体或客体截取关系证据窗口，避免把全文任意位置的词误判为同一关系。

    为什么需要这个函数：
    以前的逻辑是：
    - 只要全文里出现了主体
    - 全文里出现了客体
    - 全文里出现了关系词
    就给高分

    但这会有误判。

    误判例子：
        文本前面写：
            "扫地机器人支持蓝牙连接"
        文本后面另起一段写：
            "5G WiFi 连接路由器时建议靠近路由器"

        这两个句子虽然都出现了：
        - 主体：扫地机器人
        - 客体：5G WiFi
        - 关系：连接

        但它们根本不是一个关系事实，
        不能证明“扫地机器人连接5G WiFi”。

    所以这里的做法是：
    - 优先围绕 object_terms 取窗口（因为客体一般区分度更高）
    - 再围绕 subject_terms 取窗口
    - 后续只在这些局部窗口里判断关系是否成立
    """
    windows: list[str] = []
    seen: set[str] = set()

    # 客体一般更具体，例如“5G WiFi”“小爱同学”“自动回充”
    # 所以优先用客体来定位局部上下文。
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

    # 如果一个实体都没定位到，仍然保留全文兜底，
    # 避免关系规则过严导致完全打成 0 分。
    return windows or [normalized_text]


def _relation_score_in_window(
    *,
    intent: QueryIntent,
    normalized_window: str,
) -> float:
    """
    计算单个局部窗口内的关系证据分。

    基础分规则：
    - 主体命中：+0.25
    - 客体命中：+0.35
    - 关系命中：+0.40

    额外增强：
    - 如果主体 + 客体 + 关系 三者在同一个窗口内同时出现，再额外 +0.15
      这代表它更像“真正的一条关系事实”
    - yes_no 问题里，如果还出现“支持 / 不支持 / 兼容 / 不兼容”这类结论词，再补一点分
    """
    # 主体命中：只检查前两个主体词，避免词过多引入噪声
    subject_hit = any(term in normalized_window for term in intent.subject_terms[:2])

    # 客体命中：同样只检查前两个客体词
    object_hit = any(term in normalized_window for term in intent.object_terms[:2])

    # 关系命中：既检查规范关系词，也检查它的同义表达
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

    # 三元组完整共现，说明这个窗口更可能真的是“主体 - 关系 - 客体”闭环
    if subject_hit and object_hit and relation_hit:
        score += 0.15

    # yes/no 问题里，如果出现了结论性词汇，再额外补强
    if intent.question_type == "yes_no" and object_hit:
        if any(term in normalized_window for term in SUPPORT_CONTEXT_TERMS + UNSUPPORTED_CONTEXT_TERMS):
            score += 0.15

    return min(score, 1.0)



def relation_evidence_score(question: str, text: str) -> float:
    """
    关系证据分：
    不只看“主体 / 客体 / 关系”有没有出现，
    还看它们是不是在同一段局部上下文里一起成立。

    这会明显改善一种常见误排：
    - 主题相关，但关系不对
    - 或者主体、客体、关系散落在全文不同位置，被误当成一条证据

    返回值范围：0.0 ~ 1.0

    使用例子1：真正匹配
        question = "扫地机器人能不能连接5G WiFi？"
        text = "该扫地机器人支持 5G WiFi 双频连接。"
        => 分数会很高，通常接近 1.0

    使用例子2：主题像，但关系不完整
        question = "扫地机器人能不能连接5G WiFi？"
        text = "扫地机器人支持蓝牙连接，可与手机配对。"
        => 虽然主体和“连接”关系沾边，但没有命中“5G WiFi”，分数不会高
    """
    intent = understand_query(question)
    normalized_text = normalize_for_grounding(text)

    # 没有文本，或者问题里根本没识别出关系词，就不给关系证据分
    if not normalized_text or not intent.relation:
        return 0.0

    # 在多个局部窗口里分别计算，取最高分
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