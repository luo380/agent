from __future__ import annotations

from dataclasses import dataclass

from core.service.rag_grounding import (
    QueryIntent,
    RELATION_SYNONYM_GROUPS,
    normalize_for_grounding,
    understand_query,
)

@dataclass(frozen=True)
class RewriteQuery:
    # 改写后的查询文本
    text: str
    # 这条改写在召回 / 粗排 / 精排里占多大权重
    weight: float = 1.0
    # 调试时知道这条改写来自哪种策略
    strategy: str = "original"


def _append_rewrite(
    forms: list[RewriteQuery], # 改写列表
    seen: set[str], # 避免重复
    *,
    text: str, # 待改写文本
    weight: float, # 权重
    strategy: str, # 改写策略
) -> None:
    """
    安全加入一条 rewrite：
    - 去空
    - 归一化去重
    - 保留原始可读文本
        示例1: 正常添加
        forms = []
        seen = set()

        _append_rewrite(
            forms, seen,
            text="扫地机器人 连接 5G WiFi",
            weight=0.96,
            strategy="normalized_query"
        )

        结果:
        forms = [RewriteQuery(text="扫地机器人 连接 5G WiFi", weight=0.96, strategy="normalized_query")]
        seen = {"扫地机器人连接5GWiFi"}  # 归一化后的形式
    """

    clean_text = (text or "").strip()
    normalized = normalize_for_grounding(clean_text)
    if not clean_text or not normalized or normalized in seen:
        return

    seen.add(normalized)
    forms.append(   # 加入改写
        RewriteQuery(
            text=clean_text, # 改写后的查询文本
            weight=round(weight, 4), # 权重
            strategy=strategy, # 改写策略
        )
    )


def _build_relation_rewrites(intent: QueryIntent) -> list[RewriteQuery]:
    """
    基于 subject / relation / object 生成更像“标准检索问法”的变体。

    示例:
        用户问题: "我家扫地机器人能不能连5G WiFi？"

        经过 understand_query 后得到:
        intent = QueryIntent(
            subject_terms=["扫地机器人"],
            object_terms=["5G WiFi"],
            relation="连接",
            normalized_query="扫地机器人 连接 5G WiFi"
        )

        本函数会生成以下改写:
        1. "扫地机器人 连接 5G WiFi"  (weight=0.96, strategy="normalized_query")
        2. "扫地机器人 连接 5G WiFi"  (weight=0.93, strategy="entity_relation") [可能因去重被过滤]
        3. "扫地机器人 5G WiFi"       (weight=0.86, strategy="entity_pair")
        4. "扫地机器人 接入 5G WiFi"  (weight=0.72, strategy="relation_synonym")
        5. "扫地机器人 联网 5G WiFi"  (weight=0.72, strategy="relation_synonym")
        6. "扫地机器人 配网 5G WiFi"  (weight=0.72, strategy="relation_synonym")
        7. "扫地机器人 绑定 5G WiFi"  (weight=0.72, strategy="relation_synonym")
    """

    forms: list[RewriteQuery] = []
    seen: set[str] = set() # 避免重复

    subject = intent.subject_terms[0] if intent.subject_terms else ""
    obj = intent.object_terms[0] if intent.object_terms else ""

    if intent.normalized_query:
        _append_rewrite(
            forms,
            seen,
            text=intent.normalized_query,
            weight=0.96,
            strategy="normalized_query",
        )
    if subject and obj and intent.relation:
        _append_rewrite(
            forms,
            seen,
            text=f"{subject} {intent.relation} {obj}",
            weight=0.93,
            strategy="entity_relation",
        )

        _append_rewrite(
            forms,
            seen,
            text=f"{subject} {obj}",
            weight=0.86,
            strategy="entity_pair",
        )

        # 关系同义改写：
        # 不重新算 embedding，只是为了让 BM25 / 规则匹配 / phrase match 更强
        for alias in RELATION_SYNONYM_GROUPS.get(intent.relation, ()):
            if alias == intent.relation:
                continue
            _append_rewrite(
                forms,
                seen,
                text=f"{subject} {alias} {obj}",
                weight=0.72,
                strategy="relation_synonym",
            )

    return forms

def _build_question_type_rewrites(intent: QueryIntent) -> list[RewriteQuery]:
    """
    按问题类型生成更自然、更像知识库文档写法的检索改写。

    这一步的目标不是“语言更花哨”，而是：
    把用户口语问题改成更像文档标题 / FAQ 标题 / 说明书小节标题的形式。

    为什么这很重要：
    用户会问：
        - "我家扫地机器人能不能连5G WiFi？"
        - "这个定时清扫怎么设？"
        - "它都有哪些功能？"

    但知识库里更常见的写法是：
        - "扫地机器人 5G WiFi 支持情况"
        - "定时清扫 设置方法"
        - "扫地机器人 功能列表"

    所以我们在问题类型层面再补一层更自然的 rewrite。

    示例1：yes_no
        原问题：
            "我家扫地机器人能不能连5G WiFi？"
        可能生成：
            - "扫地机器人 5G WiFi 支持情况"
            - "5G WiFi 支持情况"

    示例2：how_to
        原问题：
            "扫地机器人的定时清扫怎么设置？"
        可能生成：
            - "扫地机器人 定时清扫 操作方法"
            - "定时清扫 设置方法"

    示例3：list
        原问题：
            "扫地机器人有哪些清洁模式？"
        可能生成：
            - "扫地机器人 清洁模式 列表"
            - "扫地机器人 有哪些功能"

    示例4：frequency
        原问题：
            "滤网多久清理一次？"
        可能生成：
            - "滤网清理 频率"
    """
    forms: list[RewriteQuery] = []
    seen: set[str] = set()

    subject = intent.subject_terms[0] if intent.subject_terms else ""
    obj = intent.object_terms[0] if intent.object_terms else ""

    # =========================
    # 1. yes/no 类问题
    # =========================
    # 用户问“能不能 / 支不支持 / 可不可以”，
    # 文档里往往写成“支持情况 / 兼容性 / 是否支持”
    if intent.question_type == "yes_no" and subject and obj:
        _append_rewrite(
            forms,
            seen,
            text=f"{subject} {obj} 支持情况",
            weight=0.62,
            strategy="yes_no_entity_status",
        )

    if intent.question_type == "yes_no" and obj:
        _append_rewrite(
            forms,
            seen,
            text=f"{obj} 支持情况",
            weight=0.58,
            strategy="yes_no_status",
        )

    # =========================
    # 2. how_to 类问题
    # =========================
    # 用户问“怎么设置 / 如何操作”，
    # 文档里更常写成“操作方法 / 设置方法 / 使用方法”
    if intent.question_type == "how_to" and subject and obj:
        _append_rewrite(
            forms,
            seen,
            text=f"{subject} {obj} 操作方法",
            weight=0.62,
            strategy="how_to_entity_method",
        )

    if intent.question_type == "how_to" and obj:
        _append_rewrite(
            forms,
            seen,
            text=f"{obj} 设置方法",
            weight=0.58,
            strategy="how_to_method",
        )

    # =========================
    # 3. list 类问题
    # =========================
    # 用户问“有哪些 / 有什么”，
    # 文档里更像“功能列表 / 模式列表 / 支持项列表”
    if intent.question_type == "list" and subject and obj:
        _append_rewrite(
            forms,
            seen,
            text=f"{subject} {obj} 列表",
            weight=0.59,
            strategy="list_entity_catalog",
        )

    if intent.question_type == "list" and subject:
        _append_rewrite(
            forms,
            seen,
            text=f"{subject} 有哪些功能",
            weight=0.55,
            strategy="list_features",
        )

    # =========================
    # 4. frequency 类问题
    # =========================
    # 用户问“多久一次 / 多长时间清理一次”，
    # 文档里更常写成“频率 / 周期 / 间隔”
    if intent.question_type == "frequency" and obj:
        _append_rewrite(
            forms,
            seen,
            text=f"{obj} 频率",
            weight=0.55,
            strategy="frequency",
        )

    return forms

def _build_focus_term_rewrites(intent: QueryIntent) -> list[RewriteQuery]:
    """
    保留现有项目已经验证过有效的 focus term 思路，
    但把它变成 rewrite 体系的一部分。
        示例3: 最多取4个焦点词
        用户问题: "小米扫地机器人Pro版支持自动回充和断点续扫功能吗？"
        intent = QueryIntent(
            focus_terms=["小米", "扫地机器人", "Pro版", "自动回充", "断点续扫", "功能"]
        )

        生成改写 (只取前4个):
        - "小米"         [长度=2 < 4, 被过滤]
        - "扫地机器人"   (weight=0.64, strategy="focus_term")
        - "Pro版"        [长度=3 < 4, 被过滤]
        - "自动回充"     (weight=0.64, strategy="focus_term")

        实际结果: 只有"扫地机器人"和"自动回充"被添加
    """
    forms: list[RewriteQuery] = []
    seen: set[str] = set()

    for term in intent.focus_terms[:4]:
        if len(term) < 4:
            continue
        _append_rewrite(
            forms,
            seen,
            text=term,
            weight=0.64,
            strategy="focus_term",
        )

    return forms


def build_weighted_rewrite_queries(question: str, *, max_forms: int = 8) -> list[RewriteQuery]:
    """
    【主入口】生成一组“带权重的 query rewrite”。

    这版是当前项目可落地版本：
    - 不重新发明一整套检索引擎
    - 不额外引入 async embedding 风险
    - 先把 rewrite 真正接进 BM25 / coarse recall / rerank
    """
    clean_question = (question or "").strip()
    if not clean_question:
        return []

    intent = understand_query(clean_question)

    forms: list[RewriteQuery] = []
    seen: set[str] = set()

    # 1. 原问题永远保留，权重最高
    _append_rewrite(
        forms,
        seen,
        text=clean_question,
        weight=1.0,
        strategy="original",
    )

    # 2. 结构化改写
    for form in _build_relation_rewrites(intent):
        _append_rewrite(
            forms,
            seen,
            text=form.text,
            weight=form.weight,
            strategy=form.strategy,
        )

    # 3. 按问题类型生成标准检索问法
    for form in _build_question_type_rewrites(intent):
        _append_rewrite(
            forms,
            seen,
            text=form.text,
            weight=form.weight,
            strategy=form.strategy,
        )

    # 4. 保留焦点词变体
    for form in _build_focus_term_rewrites(intent):
        _append_rewrite(
            forms,
            seen,
            text=form.text,
            weight=form.weight,
            strategy=form.strategy,
        )

    return forms[:max_forms]
