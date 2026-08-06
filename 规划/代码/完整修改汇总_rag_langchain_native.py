"""
================================================================================
rag_langchain_native.py  —  整合后的修改版（阶段1~5全量改动）
================================================================================

【当前架构】LangChain-Only 生成链主文件
  - 主入口：stream_answer_with_knowledge_langchain_native(...)
  - Prompt 构建：build_langchain_rag_prompt / build_answer_instruction
  - 上下文格式化：format_documents_as_context
  - 引用与兜底：ensure_answer_has_document_citations / build_citations_from_documents

【使用说明】
  此文件是在原始代码基础上整合了：
    阶段1 - Prompt 与上下文组织
    阶段2 - Grounding 与拒答策略（分流决策树）
    阶段3 - 按问题类型差异化回答
    阶段4 - 引用与答案协同（去重+用户可读）
    阶段5 - 清理与统一注释
  仅用于参考对比，实际替换时请结合业务做适配。
================================================================================
"""

from __future__ import annotations  # 放在最前面，支持 forward reference

from collections.abc import AsyncIterator, Sequence
import re
from typing import Any

from langchain_core.documents import Document
from langchain_core.output_parsers import StrOutputParser
from langchain_core.prompts import ChatPromptTemplate
from langchain_core.runnables import Runnable
from langchain_openai import ChatOpenAI
from openai import AsyncOpenAI

from core.config import settings
from core.service.langchain_adapters import (
    ProjectEmbeddings,
    ProjectKnowledgeRetriever,
    retrieved_chunk_to_langchain_document,
    retrieved_chunks_to_langchain_documents,
)
from core.service.llm import get_default_model, get_default_temperature, get_llm_client
from core.service.retrieval import RetrievedChunk
from core.service.rag_grounding import (
    GROUNDING_INSTRUCTION,
    build_direct_grounded_answer,
    evidence_match_score,
    infer_question_type,
)


STRUCTURED_SOURCE_SECTION_RE = re.compile(r"^(page|slide|sheet)_(\d+)$", re.IGNORECASE)

# ============================================================
# 阶段1 新增常量：上下文长度控制
# ============================================================
MAX_CONTEXT_CHARS = 12000              # 上下文总字符阈值（预留截断）
MAX_SINGLE_CHUNK_CHARS = 2000          # 单 chunk 最大字符
WEAK_EVIDENCE_SCORE_THRESHOLD = 0.55   # 弱证据判断阈值（metadata score）

# ============================================================
# 阶段2 新增常量：流式生成前分流
# ============================================================
WEAK_EVIDENCE_STREAM_THRESHOLD = 0.45  # 证据分低于此值 → 弱证据模式

# ============================================================
# 阶段4 新增常量：引用相关正则
# ============================================================
CITE_NUMBER_RE = re.compile(r"\[(\d+)\]")
EXISTING_REF_BLOCK_RE = re.compile(r"(参考来源|参考文献|引用来源|资料来源)\s*[：:]", re.MULTILINE)


# ----------------------------------------------------------------
# 基础工具函数（保持不变，仅清理注释）
# ----------------------------------------------------------------
def _chunk_value(chunk: RetrievedChunk | dict, key: str, default: Any = None) -> Any:
    if isinstance(chunk, dict):
        return chunk.get(key, default)
    return getattr(chunk, key, default)


def _normalize_source_page(value: Any) -> int | None:
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _format_user_facing_section(source_page: Any, source_section: Any) -> str:
    section = str(source_section or "").strip()
    if not section:
        return ""
    match = STRUCTURED_SOURCE_SECTION_RE.fullmatch(section)
    if not match:
        return section
    kind, raw_index = match.groups()
    index = int(raw_index)
    page_number = _normalize_source_page(source_page)
    if kind.lower() == "page":
        if page_number == index:
            return ""
        return f"第{index}页"
    if kind.lower() == "slide":
        return f"第{index}张"
    if kind.lower() == "sheet":
        return f"工作表{index}"
    return section


# ----------------------------------------------------------------
# 阶段4 优化：_shorten_document_name + 新的 _build_reference_line
# ----------------------------------------------------------------
def _shorten_document_name(name: str, max_len: int = 40) -> str:
    """文档名过长时前后保留、中间省略，避免引用列表难看。"""
    name = name or ""
    if len(name) <= max_len:
        return name
    keep_head = max_len // 2
    keep_tail = max_len - keep_head - 3
    return name[:keep_head] + "..." + name[-keep_tail:]


def _build_reference_line(
    document_name: str,
    source_page: Any,
    source_section: Any,
) -> str:
    """
    阶段4 优化版。
    输出示例：产品说明书.pdf · 第5页 · 安装步骤
    空值跳过，绝不暴露内部占位符。
    """
    page_number = _normalize_source_page(source_page)
    section_text = _format_user_facing_section(source_page, source_section)
    parts: list[str] = [_shorten_document_name(document_name or "未知文档")]
    if page_number is not None:
        parts.append(f"第{page_number}页")
    if section_text:
        parts.append(section_text)
    return " · ".join(parts)


# ----------------------------------------------------------------
# 兼容保留函数（阶段5 清理注释）
# ----------------------------------------------------------------
def chunk_to_document(chunk: RetrievedChunk | dict) -> Document:
    """
    【兼容保留】新代码请直接用 langchain_adapters.retrieved_chunk_to_langchain_document。
    """
    return retrieved_chunk_to_langchain_document(chunk)


def chunks_to_documents(chunks: Sequence[RetrievedChunk | dict]) -> list[Document]:
    """
    【兼容保留】新代码请直接用 langchain_adapters.retrieved_chunks_to_langchain_documents。
    """
    return retrieved_chunks_to_langchain_documents(chunks)


# ----------------------------------------------------------------
# 阶段1 优化：format_documents_as_context
# ----------------------------------------------------------------
def format_documents_as_context(documents: Sequence[Document]) -> str:
    """
    阶段1 优化版。
    固定格式：
      [编号] 文档名 | 第N页 | 章节(可选) | 相关度:X.XX
      正文内容
      <空行>
    预留总长度截断和单 chunk 截断。
    """
    if not documents:
        return ""
    blocks: list[str] = []
    total_chars = 0

    for index, doc in enumerate(documents, start=1):
        metadata = doc.metadata
        source_page = metadata.get("source_page")
        source_section = _format_user_facing_section(
            source_page, metadata.get("source_section"),
        )

        # ---- 简洁 header ----
        header_parts = [metadata.get("document_name", "未知文档")]
        if source_page is not None:
            header_parts.append(f"第{source_page}页")
        if source_section:
            header_parts.append(f"章节：{source_section}")
        score = float(metadata.get("score") or metadata.get("final_score") or 0.0)
        if score > 0:
            header_parts.append(f"相关度:{score:.2f}")
        header = f"[{index}] " + " | ".join(header_parts)

        # ---- 正文截断 ----
        content = doc.page_content.strip()
        if len(content) > MAX_SINGLE_CHUNK_CHARS:
            half = MAX_SINGLE_CHUNK_CHARS // 2
            content = content[:half] + "\n...[内容过长已截断]...\n" + content[-half:]

        # ---- 总长度检查 ----
        block_text = header + "\n" + content
        if total_chars + len(block_text) > MAX_CONTEXT_CHARS:
            remaining = MAX_CONTEXT_CHARS - total_chars
            if remaining > 200:
                blocks.append(header)
                blocks.append(content[:remaining])
                blocks.append("")
            break
        total_chars += len(block_text)
        blocks.append(header)
        blocks.append(content)
        blocks.append("")

    return "\n".join(blocks).strip()


# ----------------------------------------------------------------
# 阶段4 优化：build_citations_from_documents（去重版）
# ----------------------------------------------------------------
def build_citations_from_documents(documents: Sequence[Document]) -> list[dict]:
    """
    阶段4 优化版。
    按 (document_id, source_page, 用户可读section) 去重，
    只保留每组 score 最高的那条，附带 chunk_count 表示合并了几段。
    """
    if not documents:
        return []

    dedup_map: dict[tuple, dict] = {}
    for doc in documents:
        metadata = doc.metadata
        source_page = metadata.get("source_page")
        user_section = _format_user_facing_section(
            source_page, metadata.get("source_section"),
        )
        dedup_key = (
            metadata.get("document_id"),
            _normalize_source_page(source_page),
            user_section,
        )
        score = float(metadata.get("score") or metadata.get("final_score") or 0.0)
        raw_content = doc.page_content.strip()
        clean_content = re.sub(r"\n{3,}", "\n\n", raw_content)

        entry = {
            "document_id": metadata.get("document_id"),
            "document_name": metadata.get("document_name", "未知文档"),
            "chunk_id": metadata.get("chunk_id"),
            "chunk_index": metadata.get("chunk_index"),
            "source_page": _normalize_source_page(source_page),
            "source_section": user_section,
            "score": score,
            "content": clean_content[:300],
            "_chunk_count": 1,
        }
        if dedup_key in dedup_map:
            existing = dedup_map[dedup_key]
            if score > existing["score"]:
                entry["_chunk_count"] = existing["_chunk_count"] + 1
                dedup_map[dedup_key] = entry
            else:
                existing["_chunk_count"] += 1
        else:
            dedup_map[dedup_key] = entry

    sorted_entries = sorted(dedup_map.values(), key=lambda x: x["score"], reverse=True)
    citations: list[dict] = []
    for entry in sorted_entries:
        chunk_count = entry.pop("_chunk_count")
        entry["chunk_count"] = chunk_count
        citations.append(entry)
    return citations


def build_retrieved_chunk_payloads(chunks: Sequence[RetrievedChunk | dict]) -> list[dict]:
    """把 RetrievedChunk 整理成前端 retrieved_chunks 结构（调试用）。"""
    payloads: list[dict] = []
    for chunk in chunks:
        payloads.append({
            "document_id": _chunk_value(chunk, "document_id"),
            "document_name": _chunk_value(chunk, "document_name", "未知文档"),
            "chunk_id": _chunk_value(chunk, "chunk_id"),
            "chunk_index": _chunk_value(chunk, "chunk_index"),
            "source_page": _chunk_value(chunk, "source_page"),
            "source_section": _chunk_value(chunk, "source_section", "") or "",
            "content": _chunk_value(chunk, "content", ""),
            "vector_score": float(_chunk_value(chunk, "vector_score", 0.0) or 0.0),
            "keyword_score": float(_chunk_value(chunk, "keyword_score", 0.0) or 0.0),
            "final_score": float(_chunk_value(chunk, "final_score", 0.0) or 0.0),
        })
    return payloads


# ----------------------------------------------------------------
# 阶段1 优化：build_langchain_rag_prompt（结构更清晰）
# ----------------------------------------------------------------
def build_langchain_rag_prompt(strict_mode: bool) -> ChatPromptTemplate:
    """
    阶段1 优化版。
    strict / non-strict 边界明确，内置多 chunk 整合要求和引用规范。
    """
    if strict_mode:
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
    return ChatPromptTemplate.from_messages([
        ("system", system_prompt),
        ("user",
            "用户问题：\n"
            "{question}\n\n"
            "知识库上下文：\n"
            "{context}\n\n"
            "具体回答要求：\n"
            "{answer_instruction}"),
    ])


# ----------------------------------------------------------------
# 阶段3 内部工具：_build_style_instruction
# ----------------------------------------------------------------
def _build_style_instruction(question_type: str) -> str:
    """
    阶段3 新增。
    根据 yes_no / list / how_to / frequency / fact 返回专属结构要求。
    """
    if question_type == "yes_no":
        return """
【回答结构要求 - yes_no 类】
请严格按以下三段组织回答：
  第一段：用一句话直接给出明确结论，格式为"支持xxxx。"或"不支持xxxx。"
  第二段：引用知识库原文说明判断依据，标注来源 [1][2]
  第三段（可选）：补充相关的限制条件或注意事项
"""
    if question_type == "list":
        return """
【回答结构要求 - list 类】
请严格按以下结构组织回答：
  第一句：总述，如"知识库中提到的有以下X项："
  然后：使用 1. 2. 3. 编号列点，每项单独一行
  每个列点的格式：**名称** - 简要说明 [来源编号]
  最后（可选）：总结性说明
"""
    if question_type == "how_to":
        return """
【回答结构要求 - how_to 类】
请严格按以下结构组织回答：
  第一句：简要概括操作目标，如"可以按以下步骤完成设置："
  然后：使用 步骤1 / 步骤2 / 步骤3 编号说明
  每个步骤写一个具体动作，不要把多个动作揉在同一步
  最后（可选）：列出注意事项或常见问题
"""
    if question_type == "frequency":
        return """
【回答结构要求 - frequency 类】
请严格按以下结构组织回答：
  第一句：直接给出频率结论，格式为"建议每xxxx进行一次xxxx。"
  第二句：引用知识库原文说明依据，标注来源 [1]
  第三句（可选）：补充不同场景下的调整建议
"""
    return """
【回答结构要求 - fact 类】
请严格按以下结构组织回答：
  第一句：给出定义或核心结论
  第二段：补充工作原理、参数范围、典型用途等细节
  第三段（可选）：补充相关注意事项或常见误区
"""


def _is_context_weak(context: str, documents: Sequence[Document]) -> bool:
    """阶段1 新增：判断是否所有 chunk 的 score 都低于阈值。"""
    if not context or not documents:
        return False
    scores = [
        float(doc.metadata.get("score") or doc.metadata.get("final_score") or 0.0)
        for doc in documents
    ]
    return max(scores) < WEAK_EVIDENCE_SCORE_THRESHOLD if scores else True


# ----------------------------------------------------------------
# 阶段1 + 阶段3 优化：build_answer_instruction
# ----------------------------------------------------------------
def build_answer_instruction(
    context: str,
    strict_mode: bool,
    documents: Sequence[Document] | None = None,
    question_type: str | None = None,
) -> str:
    """
    阶段1 + 阶段3 整合版。
    支持 4 种证据状态 × 5 种问题类型 × 多 chunk 整合要求。
    """
    has_context = bool((context or "").strip())
    is_weak = _is_context_weak(context, documents or [])

    style_instruction = _build_style_instruction(question_type) if question_type else ""

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

    # ---- 情况1：有上下文且证据正常 ----
    if has_context and not is_weak:
        return (
            "当前已检索到相关知识库内容。\n"
            + style_instruction
            + multi_chunk_instruction
            + f"\n【引用要求】用到具体段落时，在句末标注 [1][2] 来源编号。\n"
            + f"【接地规则】{GROUNDING_INSTRUCTION}"
        )

    # ---- 情况2：有上下文但证据弱 ----
    if has_context and is_weak:
        if strict_mode:
            return (
                "当前检索到的知识库内容与问题相关性较低。\n"
                + style_instruction
                + "\n请保守回答：\n"
                "1. 先说明\"知识库中未明确提及该问题的直接答案\"\n"
                "2. 如果弱相关内容有参考价值，可以简要列出并标注\"仅供参考\"\n"
                "3. 不要给出确定性结论"
            )
        else:
            return (
                "当前检索到的知识库内容与问题相关性较低。\n"
                + style_instruction
                + "\n请按以下要求回答：\n"
                "1. 先说明\"知识库中未找到明确答案，以下是弱相关内容\"\n"
                "2. 列出弱相关内容作为参考\n"
                "3. 可以基于常识补充，但必须标注\"以下为非知识库补充内容\""
            )

    # ---- 情况3：无上下文 + strict ----
    if strict_mode:
        return (
            "当前完全没有检索到任何相关知识库内容。\n"
            "请直接回复：知识库中没有找到相关内容。建议尝试调整提问方式，或缩小/更换文档范围后再试。\n"
            "不要编造任何信息，不要使用引用标记。"
        )

    # ---- 情况4：无上下文 + non-strict ----
    return (
        "当前完全没有检索到任何相关知识库内容。\n"
        + style_instruction
        + "\n请按以下要求回答：\n"
        "1. 先明确说明\"知识库中未找到相关内容\"\n"
        "2. 可以基于常识给出补充答案，但必须单独标注\"以下内容非知识库信息，仅供参考\"\n"
        "3. 不要使用 [1]、[2] 这类引用标记"
    )


# ----------------------------------------------------------------
# LangChain 模型 / 链 / Retriever 构建（保持不变，仅清理注释）
# ----------------------------------------------------------------
def build_langchain_chat_model(*, streaming: bool) -> ChatOpenAI:
    return ChatOpenAI(
        model=get_default_model(),
        temperature=get_default_temperature(),
        api_key=settings.OPENAI_API_KEY,
        base_url=settings.OPENAI_BASE_URL,
        streaming=streaming,
    )


def build_langchain_retriever(
    db,
    *,
    user_id: int,
    top_k: int = 5,
    document_ids: Sequence[int] | None = None,
    client: AsyncOpenAI | None = None,
    candidate_multiplier: int = 5,
) -> ProjectKnowledgeRetriever:
    return ProjectKnowledgeRetriever(
        db=db,
        user_id=user_id,
        top_k=top_k,
        candidate_multiplier=candidate_multiplier,
        document_ids=list(document_ids) if document_ids else None,
        embeddings=ProjectEmbeddings(client=client),
    )


def build_langchain_rag_chain(*, strict_mode: bool, streaming: bool = False) -> Runnable:
    prompt = build_langchain_rag_prompt(strict_mode)
    llm = build_langchain_chat_model(streaming=streaming)
    return prompt | llm | StrOutputParser()


# ----------------------------------------------------------------
# 阶段4 内部工具：_extract_cited_numbers
# ----------------------------------------------------------------
def _extract_cited_numbers(answer_text: str) -> list[int]:
    """从答案中提取 [1][3] 这种实际出现过的引用编号。"""
    return sorted({
        int(m) for m in CITE_NUMBER_RE.findall(answer_text or "") if m.isdigit()
    })


# ----------------------------------------------------------------
# 阶段4 优化：ensure_answer_has_document_citations（三档兜底）
# ----------------------------------------------------------------
def ensure_answer_has_document_citations(
    answer_text: str,
    documents: Sequence[Document],
) -> str:
    """
    阶段4 优化版。
    档1：已有完整参考来源块 → 不动
    档2：有 [1][2] 但没列表 → 只补出现过的编号
    档3：完全没引用 → 完整追加
    """
    clean_answer = (answer_text or "").strip()
    if not documents:
        return clean_answer
    if not clean_answer:
        clean_answer = "我根据知识库整理了相关信息。"
    if EXISTING_REF_BLOCK_RE.search(clean_answer):
        return clean_answer

    # 构建去重参考列表（按文档+页码粒度）
    reference_lines: list[str] = []
    seen_rough_keys: set[tuple] = set()
    for doc in documents:
        metadata = doc.metadata
        document_name = metadata.get("document_name", "未知文档")
        source_page = metadata.get("source_page")
        section_text = _format_user_facing_section(
            source_page, metadata.get("source_section"),
        )
        rough_key = (metadata.get("document_id"), _normalize_source_page(source_page))
        if rough_key in seen_rough_keys:
            continue
        seen_rough_keys.add(rough_key)
        reference_lines.append(
            _build_reference_line(document_name, source_page, section_text)
        )
    if not reference_lines:
        return clean_answer

    # ---- 档2：有 [1][2] 编号 ----
    cited_numbers = _extract_cited_numbers(clean_answer)
    if cited_numbers:
        valid_refs = [
            f"[{num}] {reference_lines[num - 1]}"
            for num in cited_numbers
            if 1 <= num <= len(reference_lines)
        ]
        if valid_refs:
            return f"{clean_answer}\n\n参考来源：\n" + "\n".join(valid_refs)

    # ---- 档3：完整追加 ----
    numbered_lines = [
        f"[{i+1}] {line}" for i, line in enumerate(reference_lines)
    ]
    return f"{clean_answer}\n\n参考来源：\n" + "\n".join(numbered_lines)


# ----------------------------------------------------------------
# 阶段2 + 阶段3 主入口：stream_answer_with_knowledge_langchain_native
# ----------------------------------------------------------------
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
    LangChain 原生流式 RAG 主流程。

    【生成前分流决策树】
    Step 1~3. 构建 Retriever → 检索 → 拼 context
    Step 4~6. 构建 citations + retrieved_chunks
    Step 7.   通知 context_ready
    Step 8A.  无 context + strict → 拒答 return
    Step 8B.  direct_grounded_answer 命中 → 直接 return
    Step 8C.  证据弱 / 有冲突 → LLM 但 Prompt 特别提醒
    Step 9~11. LangChain LCEL 流式生成
    Step 12.  done 事件输出（带 decision_path / question_type）
    """
    # Step 1：LLM 客户端
    client = client or get_llm_client()

    # 阶段3：识别问题类型（驱动差异化回答风格）
    question_type = infer_question_type(question)

    # Step 2：构建 Retriever
    retriever = build_langchain_retriever(
        db, user_id=user_id, top_k=top_k,
        document_ids=document_ids, client=client,
    )

    # Step 3：执行检索
    documents = await retriever.aretrieve_documents(question)
    reranked_hits = retriever.last_reranked_hits

    # Step 4：格式化 context
    context = format_documents_as_context(documents)

    # Step 5：构建 citations（用户可读 + 去重）
    citations = build_citations_from_documents(documents)

    # Step 6：构建调试用 retrieved_chunks
    retrieved_chunk_payloads = build_retrieved_chunk_payloads(reranked_hits)

    # ---- 阶段2 新增：证据预分析 ----
    chunk_ev_scores = (
        [evidence_match_score(question, doc.page_content) for doc in documents]
        if documents else []
    )
    max_ev_score = max(chunk_ev_scores) if chunk_ev_scores else 0.0

    has_conflict = False
    if question_type == "yes_no" and len(documents) >= 2:
        from core.service.rag_grounding import (
            SUPPORT_CONTEXT_TERMS, UNSUPPORTED_CONTEXT_TERMS,
        )
        all_norms = [normalize_for_grounding_local(doc.page_content) for doc in documents]
        s = any(any(t in w for t in SUPPORT_CONTEXT_TERMS) for w in all_norms)
        u = any(any(t in w for t in UNSUPPORTED_CONTEXT_TERMS) for w in all_norms)
        has_conflict = s and u

    # Step 7：通知前端检索完成
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

    # Step 8A：无 context + strict → 拒答
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
                "question_type": question_type,
            },
        }
        return

    # Step 8B：direct grounded answer 命中（不再限 strict_mode）
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
                "question_type": question_type,
            },
        }
        return

    # Step 9 & 10：构建链 + 组装输入（含弱证据/冲突提醒）
    chain = build_langchain_rag_chain(strict_mode=strict_mode, streaming=True)

    base_instruction = build_answer_instruction(
        context, strict_mode, documents, question_type=question_type,
    )
    extra = ""
    if max_ev_score < WEAK_EVIDENCE_STREAM_THRESHOLD and context:
        extra += (
            "\n\n【特别提醒】当前检索到的内容与问题相关性整体偏弱。"
            "请使用保守语气，不要给出确定性结论。"
            "可以说\"知识库中未见明确说明\"或\"仅找到以下弱相关信息\"。"
        )
    if has_conflict:
        extra += (
            "\n\n【冲突提醒】知识库不同段落中存在相互矛盾的表述。"
            "请不要给出绝对化结论，优先说明\"知识库中有不同说法\"，"
            "并客观列出不同观点的来源，不要偏向任一方。"
        )

    chain_input = {
        "question": question,
        "context": context or "未检索到相关知识库内容。",
        "answer_instruction": base_instruction + extra,
    }

    # Step 11：LangChain 原生流式生成
    answer_parts: list[str] = []
    async for delta in chain.astream(chain_input):
        if not delta:
            continue
        answer_parts.append(delta)
        yield {"event": "delta", "data": {"content": delta}}

    # Step 12：最终 done
    answer_text = "".join(answer_parts).strip()
    answer_text = ensure_answer_has_document_citations(answer_text, documents)

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
            "question_type": question_type,
        },
    }


# ----------------------------------------------------------------
# 临时本地 helper（避免循环 import 的 normalize_for_grounding）
# ----------------------------------------------------------------
def normalize_for_grounding_local(text: str) -> str:
    """
    这里内联一份 rag_grounding.normalize_for_grounding 的简化副本，
    避免在函数中间 import 带来的可读性问题。
    生产环境建议直接从 rag_grounding import。
    """
    return re.sub(r"\s+", "", (text or "")).lower()