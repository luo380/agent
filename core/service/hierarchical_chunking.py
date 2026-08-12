from __future__ import annotations

import os
import re
from functools import lru_cache
from typing import Any

MIN_TEXT_CHUNK_CHARS = 120
MAX_TABLE_ROWS_PER_CHUNK = 12
DEFAULT_SEMANTIC_CHUNK_MODEL = "paraphrase-multilingual-MiniLM-L12-v2"
DEFAULT_SEMANTIC_BREAKPOINT_PERCENTILE = 20.0
DEFAULT_SEMANTIC_EMBEDDING_BATCH_SIZE = 32
SENTENCE_END_CHARS = set(".!?\n\u3002\uff01\uff1f\uff1b")

#表格分割线
MARKDOWN_TABLE_SEPARATOR_RE = re.compile(r"^\|?(?:\s*:?-{3,}:?\s*\|)+\s*$")

def _normalize_text(text: str) -> str:
    return (text or "").strip()

def _validate_chunk_args(chunk_size: int, overlap: int) -> None:
    if chunk_size <= 0:
        raise ValueError("chunk_size must be > 0")
    if overlap < 0:
        raise ValueError("overlap must be >= 0")
    if overlap >= chunk_size:
        raise ValueError("overlap must be smaller than chunk_size")


def _split_paragraphs(text: str) -> list[str]:
    """
    优先按自然段切。（按段落边界切）
    这是很多产品里“轻量语义分块”的第一层：
    先尊重段落边界，再考虑长度。
    """
    clean_text = _normalize_text(text)
    if not clean_text:
        return []

    parts = re.split(r"\n\s*\n+", clean_text)
    return [part.strip() for part in parts if part.strip()]



def _split_sentences(text: str) -> list[str]:
    """
    再按句子切。
    输入文本
│
├── 逐字符扫描
│   ├── 遇到句末标点（。！？!?；;）
│   │   └── 把当前攒的字符打包 → 存入结果
│   │
│   └── 其他字符
│       └── 继续攒
│
├── 扫描结束，有剩余？
│   └── 剩余文本也存入结果
│
└── 返回句子列表（至少返回原文本）
    """
    text = _normalize_text(text)
    if not text:
        return []

    sentences: list[str] = []
    current: list[str] = []

    for char in text:
        current.append(char)
        if char in SENTENCE_END_CHARS:
            sentence = "".join(current).strip()
            if sentence:
                sentences.append(sentence)
            current = []
            continue
        if char in "。！？!?；;":
            sentence = "".join(current).strip()
            if sentence:
                sentences.append(sentence)
            current = []


    tail = "".join(current).strip()
    if tail:
        sentences.append(tail)

    return sentences or [text]

def _split_long_unit(unit: str, chunk_size: int) -> list[str]:
    """
    贪心策略：能装就装，装不下就开新箱子
    一个段落太长了，超过了 chunk_size，怎么办？
    如果单个段落太长，就继续往句子级拆。
    如果句子级还太长，再做字符兜底。
    """
    unit = _normalize_text(unit)
    if not unit:
        return []

    if len(unit) <= chunk_size:
        return [unit]

    sentences = _split_sentences(unit)
    # 如果句子数只有一个，且长度超过 chunk_size，则按字符拆分
    if len(sentences) == 1 and len(sentences[0]) > chunk_size:
        results: list[str] = []
        start = 0
        while start < len(unit):
            end = min(start + chunk_size, len(unit))
            piece = unit[start:end].strip()
            if piece:
                results.append(piece)
            if end >= len(unit):
                break
            start = end
        return results

    #贪心算法，尽量按句子切，再按字符切
    """
    物品: [6, 3, 4, 7, 2, 5]
    贪心策略：能装就装，装不下就开新箱子
    箱子1: [6, 3]         → 6+3=9，再加4就13，超了 → 关箱
    箱子2: [4]            → 4，再加7就11，超了 → 关箱
    箱子3: [7, 2]         → 7+2=9，再加5就14，超了 → 关箱
    箱子4: [5]            → 关箱
    """
    merged: list[str] = []  # 最终结果
    current: list[str] = []  # 当前正在攒的句子组
    current_length = 0  # 当前组的总字符数

    for sentence in sentences:
        # 计算加上这个句子后，总长度会是多少
        # +1 是因为句子之间要用空格拼接
        projected = current_length + len(sentence) + (1 if current else 0)

        if current and projected > chunk_size:
            # 如果已经攒了一些句子，且加上这个会超限：
            # ① 把当前攒的句子用空格拼起来，存入结果
            merged.append(" ".join(current).strip())
            # ② 这个句子作为新一组的开头
            current = [sentence]
            current_length = len(sentence)
            continue

        # 没超限，继续往当前组里加
        current.append(sentence)
        current_length = projected

    # 循环结束后，别忘了最后一组
    if current:
        merged.append(" ".join(current).strip())

    return [item for item in merged if item]


def _tail_overlap_text(text: str, overlap: int) -> str:
    """
    解决分块后的"语义断裂"问题
    生成下一块的尾部重叠文本。

    这里不直接粗暴截最后 overlap 个字符，
    而是优先保留句子尾部，尽量让上下文更自然。
    [── A 块 ──][A尾 ∩ B头][── B 块主体 ──][B尾 ∩ C头][── C 块主体 ──]
    """

    text = _normalize_text(text)
    if not text or overlap <= 0:
        return ""

    if len(text) <= overlap:
        return text

    sentences = _split_sentences(text)
    if len(sentences) <= 1:
        return text[-overlap:].strip()


    picked: list[str] = []  # 从尾部捞到的句子（倒序存放）
    total = 0  # 已捞到的总字符数

    for sentence in reversed(sentences):  # 从最后一句开始往前遍历
        picked.append(sentence)  # 把当前句子捞进来
        total += len(sentence)  # 累加字符数
        if total >= overlap:  # 够了就停
            break

    return " ".join(reversed(picked)).strip()


def _heuristic_text_chunks(text: str, chunk_size: int, overlap: int) -> list[str]:

    """
    正文块切分主逻辑。

    思路：
    1. 先按段落
    2. 段落太长再按句子
    3. 句子仍然过长才按字符兜底
    第1轮: current_units = ["AAAAAA"]       长度=6    → 没超，继续累积
    第2轮: current_units = ["AAAAAA","BBBBBB"] 长度=15  → 没超，继续累积
    ...
    第N轮: current_units 累积到长度=95
       再加新 unit 预估会到 110，超过 100！
       且 95 >= min(最小阈值, 100) ✓
       → 切块！打包存入 chunks
       → 取末尾 20 字符作为重叠
       → 新块以重叠文本开头，继续累积
    """

    paragraphs = _split_paragraphs(text)
    if not paragraphs:
        return []

    units: list[str] = []

    for paragraph in paragraphs:
        if len(paragraph) <= chunk_size:
            units.append(paragraph)
        else:
            #已经封箱好了
            units.extend(_split_long_unit(paragraph, chunk_size))


    chunks: list[str] = []
    current_units: list[str] = []
    current_length = 0

    for unit in units:
        """
        if current_units:      # 如果 current_units 不为空
        separator_length = 2   # 那么分隔符长度 = 2
        else:                      # 否则（current_units 为空）
        separator_length = 0   # 分隔符长度 = 0
        如果当前行已经有内容，加新内容前要预留 2 个字符的位置给分隔符；如果当前行是空的，就不需要分隔符，预留 0。
        """
        separator_length = 2 if current_units else 0
        projected = current_length + separator_length + len(unit)
        if (
                current_units
                and projected > chunk_size
                and current_length >= min(MIN_TEXT_CHUNK_CHARS, chunk_size)
        ):
            """
            要是取上一次的6位tttttt，这一次为15位ooooooooooooooo加起来超过了20，那么ooooooooooooooooooo 单独封箱吗
            不会拆 o，会把 [tttttt, ooooooooooooooo] 整体当一块打包
            """
            ## 贪心封箱 + overlap
            current_text = "\n\n".join(current_units).strip()
            chunks.append(current_text)
            """这一步是为了让下一个块和当前块有一小段重叠，保证上下文不丢失："""
            overlap_text = _tail_overlap_text(current_text, overlap)
            current_units = [overlap_text, unit] if overlap_text else [unit]
            # 直接打包，没有任何尺寸检查
            current_length = len("\n\n".join(current_units).strip())
            continue
        current_units.append(unit)  # ← 直接塞进去，不管多大
        current_length = len("\n\n".join(current_units).strip())

    if current_units:
        chunks.append("\n\n".join(current_units).strip())

    return [item for item in chunks if item]




@lru_cache(maxsize=1)
def _load_semantic_chunking_model():
    """Load the local sentence embedding model lazily.

    This function is intentionally fail-soft:
    - If sentence-transformers is not installed, return None.
    - If the model cannot be downloaded/loaded, return None.
    - The caller then falls back to the existing heuristic chunker.

    Example .env:
        SEMANTIC_CHUNKING_MODEL=paraphrase-multilingual-MiniLM-L12-v2

    Other lightweight candidates:
        all-MiniLM-L6-v2
        paraphrase-multilingual-MiniLM-L12-v2
    """

    try:
        from sentence_transformers import SentenceTransformer
    except Exception:
        return None

    model_name = os.getenv(
        "SEMANTIC_CHUNKING_MODEL",
        DEFAULT_SEMANTIC_CHUNK_MODEL,
    ).strip()
    if not model_name:
        return None

    try:
        return SentenceTransformer(model_name)
    except Exception:
        return None


def _semantic_cosine_similarity(a: Any, b: Any) -> float:
    """Cosine similarity for sentence embeddings.

    sentence-transformers may return numpy arrays, torch tensors, or plain
    lists depending on runtime settings. Iterating over them keeps this helper
    dependency-light and easy to test.
    """

    a_values = [float(value) for value in a]
    b_values = [float(value) for value in b]
    if not a_values or not b_values or len(a_values) != len(b_values):
        return 0.0

    dot = sum(x * y for x, y in zip(a_values, b_values))
    norm_a = sum(x * x for x in a_values) ** 0.5
    norm_b = sum(y * y for y in b_values) ** 0.5
    if not norm_a or not norm_b:
        return 0.0

    return dot / (norm_a * norm_b)


def _percentile(values: list[float], percentile: float) -> float:
    """Return a percentile value with linear interpolation.

    Why percentile instead of a fixed threshold?
    Different documents have different writing styles. A technical manual may
    have many short related sentences, while a meeting note may jump topics
    often. Percentile-based thresholds adapt to each document by cutting at
    the local low-similarity valleys.

    Example:
        similarities = [0.91, 0.88, 0.31, 0.86]
        percentile=25 roughly selects a low value, so the 0.31 valley becomes
        a semantic breakpoint.
    """

    if not values:
        return 0.0

    percentile = max(0.0, min(100.0, float(percentile)))
    sorted_values = sorted(values)
    if len(sorted_values) == 1:
        return sorted_values[0]

    position = (len(sorted_values) - 1) * (percentile / 100.0)
    lower_index = int(position)
    upper_index = min(lower_index + 1, len(sorted_values) - 1)
    weight = position - lower_index

    return (
        sorted_values[lower_index] * (1.0 - weight)
        + sorted_values[upper_index] * weight
    )


def _semantic_sentence_units(text: str) -> list[str]:
    """Split text into sentence units while preserving paragraph order."""

    units: list[str] = []
    for paragraph in _split_paragraphs(text):
        units.extend(
            sentence.strip()
            for sentence in _split_sentences(paragraph)
            if sentence.strip()
        )

    return units


def _merge_semantic_sentences(
    sentences: list[str],
    breakpoints: set[int],
    chunk_size: int,
    overlap: int,
) -> list[str]:
    """Merge sentence runs into chunks using semantic breakpoints.

    A breakpoint index means: "cut after sentence[index]".
    Size limits still win, because chunks that are too long hurt embedding
    quality and retrieval latency. If a semantic chunk grows past chunk_size,
    the existing sentence/character fallback keeps it bounded.
    """

    chunks: list[str] = []
    current_sentences: list[str] = []

    for index, sentence in enumerate(sentences):
        current_sentences.append(sentence)
        current_text = " ".join(current_sentences).strip()

        should_cut_by_semantics = index in breakpoints
        should_cut_by_size = len(current_text) >= chunk_size
        large_enough = len(current_text) >= min(MIN_TEXT_CHUNK_CHARS, chunk_size)

        if current_sentences and large_enough and (
            should_cut_by_semantics or should_cut_by_size
        ):
            chunks.extend(_split_long_unit(current_text, chunk_size))

            overlap_text = _tail_overlap_text(current_text, overlap)
            current_sentences = [overlap_text] if overlap_text else []

    if current_sentences:
        current_text = " ".join(current_sentences).strip()
        chunks.extend(_split_long_unit(current_text, chunk_size))

    return [chunk for chunk in chunks if chunk]


def _semantic_split_by_embedding(
    text: str,
    chunk_size: int,
    overlap: int,
    *,
    breakpoint_percentile: float | None = None,
) -> list[str]:
    """Split text by embedding-based semantic boundaries.

    Pipeline:
        full text
        -> sentence split
        -> sentence embeddings
        -> adjacent sentence cosine similarity
        -> low-similarity valleys become breakpoints
        -> merge sentence runs into chunks
        -> oversized chunks fall back to _split_long_unit()

    Example:
        S1: "The product supports Xiaoai."
        S2: "It also supports Tmall Genie."
        S3: "Clean the main brush every week."

        sim(S1, S2) should be high.
        sim(S2, S3) should be lower.
        The algorithm cuts after S2 because the topic changes.
    """

    sentences = _semantic_sentence_units(text)
    if len(sentences) <= 1:
        return _heuristic_text_chunks(text, chunk_size, overlap)

    model = _load_semantic_chunking_model()
    if model is None:
        return _heuristic_text_chunks(text, chunk_size, overlap)

    try:
        batch_size = int(
            os.getenv(
                "SEMANTIC_CHUNKING_BATCH_SIZE",
                str(DEFAULT_SEMANTIC_EMBEDDING_BATCH_SIZE),
            )
        )
    except ValueError:
        batch_size = DEFAULT_SEMANTIC_EMBEDDING_BATCH_SIZE
    batch_size = max(1, batch_size)

    try:
        embeddings = model.encode(
            sentences,
            batch_size=batch_size,
            normalize_embeddings=True,
            show_progress_bar=False,
        )
    except Exception:
        return _heuristic_text_chunks(text, chunk_size, overlap)

    adjacent_similarities: list[float] = []
    for index in range(len(sentences) - 1):
        adjacent_similarities.append(
            _semantic_cosine_similarity(
                embeddings[index],
                embeddings[index + 1],
            )
        )

    if not adjacent_similarities:
        return _heuristic_text_chunks(text, chunk_size, overlap)

    if breakpoint_percentile is None:
        try:
            breakpoint_percentile = float(
                os.getenv(
                    "SEMANTIC_CHUNKING_BREAKPOINT_PERCENTILE",
                    str(DEFAULT_SEMANTIC_BREAKPOINT_PERCENTILE),
                )
            )
        except ValueError:
            breakpoint_percentile = DEFAULT_SEMANTIC_BREAKPOINT_PERCENTILE

    threshold = _percentile(adjacent_similarities, breakpoint_percentile)
    breakpoints = {
        index
        for index, similarity in enumerate(adjacent_similarities)
        if similarity <= threshold
    }

    chunks = _merge_semantic_sentences(
        sentences,
        breakpoints,
        chunk_size,
        overlap,
    )
    return chunks or _heuristic_text_chunks(text, chunk_size, overlap)


def _semantic_text_chunks(
    text: str,
    chunk_size: int,
    overlap: int,
    *,
    use_semantic_chunking: bool = False,
) -> list[str]:
    """Choose between heuristic and embedding-based semantic chunking.

    Default behavior stays unchanged:
        use_semantic_chunking=False -> paragraph/sentence/character heuristic.

    Experiment mode:
        use_semantic_chunking=True -> embedding boundary detection first,
        with automatic fallback to the heuristic chunker.
    """

    if not use_semantic_chunking:
        return _heuristic_text_chunks(text, chunk_size, overlap)

    return _semantic_split_by_embedding(text, chunk_size, overlap)

def _looks_like_markdown_table_line(line: str) -> bool:
    line = (line or "").strip()
    return "|" in line and len([part for part in line.split("|") if part.strip()]) >= 2


def _split_markdown_section_blocks(section_title: str, section_text: str) -> list[dict]:
    """
    把 markdown section 再拆成 text block 和 table block。

    这样 markdown 表格不会和正文混在一起切。
    """
    lines = (section_text or "").splitlines()
    blocks: list[dict] = []

    text_buffer: list[str] = []
    index = 0

    while index < len(lines):
        current_line = lines[index].rstrip()
        next_line = lines[index + 1].rstrip() if index + 1 < len(lines) else ""

        is_table_start = (
            _looks_like_markdown_table_line(current_line)
            and MARKDOWN_TABLE_SEPARATOR_RE.match(next_line.strip()) is not None
        )

        if is_table_start:
            text_text = _normalize_text("\n".join(text_buffer))
            if text_text:
                blocks.append(
                    {
                        "block_type": "text",
                        "parent_title": section_title,
                        "source_section": section_title,
                        "text": text_text,
                    }
                )
            text_buffer = []

            table_lines = [current_line, next_line]
            index += 2

            while index < len(lines):
                row_line = lines[index].rstrip()
                if not _looks_like_markdown_table_line(row_line):
                    break
                table_lines.append(row_line)
                index += 1

            table_text = _normalize_text("\n".join(table_lines))
            if table_text:
                blocks.append(
                    {
                        "block_type": "table",
                        "parent_title": section_title,
                        "source_section": section_title,
                        "text": table_text,
                    }
                )
            continue

        text_buffer.append(current_line)
        index += 1

    text_text = _normalize_text("\n".join(text_buffer))
    if text_text:
        blocks.append(
            {
                "block_type": "text",
                "parent_title": section_title,
                "source_section": section_title,
                "text": text_text,
            }
        )

    return blocks


def _build_parent_segments(parsed: dict, file_type: str) -> list[dict]:
    """
    把解析结果统一转换成 parent segment。

    parent segment 是“父块候选”，后面会进一步切出 leaf chunk。
    """

    full_text = _normalize_text(parsed.get("full_text") or "")
    pages = parsed.get("pages") or []
    sections = parsed.get("sections") or []

    if not full_text:
        return []

    if file_type in {"pdf", "pptx"} and pages:
        segments: list[dict] = []
        for item in pages:
            page_text = _normalize_text(item.get("text") or "")
            if not page_text:
                continue
            page_no = item.get("page")
            segments.append(
                {
                    "block_type": "text",
                    "parent_title": f"第 {page_no} 页" if page_no is not None else "页面",
                    "source_page": page_no,
                    "source_section": item.get("section", "") or f"page_{page_no}",
                    "text": page_text,
                }
            )
        return segments

    if file_type in {"xlsx", "xls"} and sections:
        segments = []
        for item in sections:
            sheet_text = _normalize_text(item.get("text") or "")
            if not sheet_text:
                continue
            sheet_name = (item.get("section") or "工作表").strip()
            segments.append(
                {
                    "block_type": "table",
                    "parent_title": sheet_name,
                    "source_page": None,
                    "source_section": sheet_name,
                    "text": sheet_text,
                }
            )
        return segments

    if file_type == "md" and sections:
        segments = []
        for item in sections:
            section_title = (item.get("section") or "正文").strip()
            section_text = _normalize_text(item.get("text") or "")
            if not section_text:
                continue
            segments.extend(_split_markdown_section_blocks(section_title, section_text))
        return segments

    if sections:
        segments = []
        for item in sections:
            section_title = (item.get("section") or "正文").strip()
            section_text = _normalize_text(item.get("text") or "")
            if not section_text:
                continue
            segments.append(
                {
                    "block_type": "text",
                    "parent_title": section_title,
                    "source_page": None,
                    "source_section": section_title,
                    "text": section_text,
                }
            )

        return segments
    """"
    输出结果例子：  
    [
    {
        "block_type": "text",
        "parent_title": "第一章 引言",
        "source_page": None,
        "source_section": "第一章 引言",
        "text": "本章介绍研究背景和意义..."
    },
    {
        "block_type": "text", 
        "parent_title": "第二章 方法",
        "source_page": None,
        "source_section": "第二章 方法",
        "text": "本研究采用以下方法..."
    }
]
    """
    return [
        {
            "block_type": "text",
            "parent_title": "正文",
            "source_page": None,
            "source_section": "",
            "text": full_text,
        }
    ]



def _build_retrieval_content(parent_title: str, block_type: str, leaf_text: str) -> str:
    """
    给 leaf chunk 生成检索文本。

    retrieval_content 比 content 多带一点“结构上下文”，
    这样 embedding 和 BM25 更容易理解这段 leaf 属于哪个主题。
    核心思想：分块必然会破坏文档结构连续性，通过 _build_retrieval_content 在每个叶子块上"粘回"父级主题信息，用最小代价换取检索准确率的显著提升。这是 RAG 系统中常用且非常有效的工程优化技巧。
    """

    parts: list[str] = []

    title = (parent_title or "").strip()

    if title:
        parts.append(f"[父级主题] {title}")

    if block_type == "table":
        parts.append("[内容类型] 表格")
    else:
        parts.append("[内容类型] 正文")
    leaf_text = _normalize_text(leaf_text)
    if leaf_text:
        parts.append(leaf_text)

    return "\n".join(parts).strip()



def _safe_find_from(text: str, fragment: str, start: int) -> int:
    if not fragment:
        return start
    index = text.find(fragment, start)
    if index != -1:
        return index
    return start


def _chunk_table_text(
    table_text: str,
    *,
    chunk_size: int,
) -> list[dict]:

    """
    表格专属切块。

    规则：
    1. 第一行视为表头
    2. 每个 leaf chunk 都重复表头
    3. 按行数分组，而不是按字符随便切
    """

    lines = [line.strip() for line in table_text.splitlines() if line.strip()]

    if not lines:
        return []
    header = lines[0]
    separator = lines[1] if len(lines) > 1 and MARKDOWN_TABLE_SEPARATOR_RE.match(lines[1]) else ""
    data_rows = lines[2:] if separator else lines[1:]

    if not data_rows:
        return [
            {
                "text": table_text,
                "row_from": 1,
                "row_to": 1,
            }
        ]

    average_row_length = max(1, sum(len(row) for row in data_rows) // len(data_rows))
    rows_per_chunk = max(3, min(MAX_TABLE_ROWS_PER_CHUNK, chunk_size // average_row_length))

    chunks: list[dict] = []
    start_row = 0

    while start_row < len(data_rows):
        end_row = min(start_row + rows_per_chunk, len(data_rows))
        chunk_rows = data_rows[start_row:end_row]

        parts = [header]
        if separator:
            parts.append(separator)
        parts.extend(chunk_rows)

        chunks.append(
            {
                "text": "\n".join(parts).strip(),
                "row_from": start_row + 1,
                "row_to": end_row,
            }
        )
        start_row = end_row

    return chunks



def build_hierarchical_chunks(
    parsed: dict,
    *,
    file_type: str,
    chunk_size: int = 500,
    overlap: int = 100,
    use_semantic_chunking: bool = False,
) -> list[dict]:
    """
    生成“完整层级 chunk”。

    这是整个分层分块模块的对外主入口函数，串联所有子步骤：
    1. 参数校验
    2. 构建父块（parent segment）
    3. 对每个父块做子块切分（leaf chunk）
    4. 统一输出扁平的 chunk 列表

    输出是一个扁平列表，但语义上分两层：
    - parent chunk：大上下文块，供 small-to-big expand 检索策略使用
    - leaf chunk：   小召回块，供 embedding / BM25 / FAISS 向量检索

    流程示意：
    ┌─────────────────────────────────────────────────┐
    │ parsed (解析结果: {full_text, pages, sections})  │
    └────────────────────┬────────────────────────────┘
                         │
                         ▼
    ┌─────────────────────────────────────────────────┐
    │ _build_parent_segments() → 按章节/页面分父块     │
    │ 例: [父块1: "第一章 引言", 父块2: "第二章 方法"]  │
    └────────────────────┬────────────────────────────┘
                         │
                         ▼
    ┌─────────────────────────────────────────────────┐
    │ 对每个父块:                                       │
    │   - 表格父块 → _chunk_table_text() 按行切          │
    │   - 正文父块 → _semantic_text_chunks() 语义切      │
    │   每个叶子块再通过 _build_retrieval_content()      │
    │   注入父级主题前缀，生成增强检索文本                   │
    └────────────────────┬────────────────────────────┘
                         │
                         ▼
    ┌─────────────────────────────────────────────────┐
    │ 扁平列表输出:                                    │
    │ [parent_chunk_0, leaf_0_1, leaf_0_2,             │
    │  parent_chunk_1, leaf_1_1, leaf_1_2, ...]       │
    │ 通过 local_parent_key 关联父子关系               │
    └─────────────────────────────────────────────────┘

    返回的每个 dict 都已经带好了入库所需字段。
    """
    # ========== 1. 参数校验 ==========
    _validate_chunk_args(chunk_size, overlap)

    # ========== 2. 获取全文，空文本直接返回 ==========
    full_text = _normalize_text(parsed.get("full_text") or "")
    if not full_text:
        return []

    # ========== 3. 构建父块候选（按文件类型分策略） ==========
    # PDF/PPTX → 按页切；Excel → 按工作表切；Markdown → 按章节切；其他 → 通用兜底
    segments = _build_parent_segments(parsed, file_type)
    if not segments:
        return []

    # ========== 4. 初始化输出列表和游标 ==========
    chunk_items: list[dict] = []

    # search_cursor: 在 full_text 中搜索父块文本的起始游标位置
    # 每次找到一个父块后，游标推进到该父块的末尾，避免重复搜索
    search_cursor = 0

    # next_chunk_index: 全局递增的 chunk 序号，用于最终排序
    next_chunk_index = 0

    # ========== 5. 遍历每个父块，生成 parent + leaf 结构 ==========
    #这个for循环 前面输出两个元素，第一个是索引，第二个是元素本身
    for segment_index, segment in enumerate(segments):
        # ----- 5.1 提取父块基本信息 -----
        block_type = segment["block_type"]  # "text" 或 "table"
        parent_title = (segment.get("parent_title") or "正文").strip()
        source_page = segment.get("source_page")  # 来源页码（PDF类才有）
        source_section = (segment.get("source_section") or "").strip()
        parent_text = _normalize_text(segment.get("text") or "")
        if not parent_text:
            continue  # 空父块跳过

        # ----- 5.2 生成父块的唯一标识 key -----
        # 后续入库时通过 local_parent_key 把子块关联回父块
        local_parent_key = f"parent_{segment_index}"

        # ----- 5.3 在全文文本中定位父块的位置 -----
        # found_at 记录父块在 full_text 中的字符偏移量，
        # 用于后续计算每个子块在原文中的精确位置（start_offset / end_offset）
        found_at = full_text.find(parent_text, search_cursor)
        if found_at == -1:
            # 兜底：如果找不到（理论上不应该，但做防御），从当前游标继续
            found_at = search_cursor

        # ----- 5.4 构建 parent chunk 并加入输出列表 -----
        # parent chunk 自身不参与 embedding 检索（retrieval_content 为空），
        # 它在 small-to-big 策略中作为"大上下文块"供后续展开使用
        parent_item = {
            "local_parent_key": local_parent_key,
            "chunk_role": "parent",  # 标记为父块
            "chunk_index": next_chunk_index,
            "parent_chunk_id": None,  # 入库后由数据库回填
            "parent_title": parent_title,
            "block_type": block_type,
            "child_index": 0,  # 父块没有子序号
            "table_row_from": None,
            "table_row_to": None,
            "content": parent_text,  # 父块的完整文本
            "retrieval_content": "",  # 父块不参与检索，留空
            "start_offset": found_at,  # 父块在原文中的起始偏移
            "end_offset": found_at + len(parent_text),  # 父块在原文中的结束偏移
            "source_page": source_page,
            "source_section": source_section,
        }
        chunk_items.append(parent_item)
        next_chunk_index += 1

        # ----- 5.5 对父块做子块切分 -----
        # local_cursor: 在父块文本内部搜索子块位置的游标
        local_cursor = 0

        # ===== 分支A：表格类型父块 → 按行切分 =====
        if block_type == "table":
            # 表格切分使用专属算法，且 chunk_size 至少 700 以保证表格可读性
            table_leafs = _chunk_table_text(
                parent_text,
                chunk_size=max(chunk_size, 700),
            )
            for child_index, leaf in enumerate(table_leafs, start=1):
                leaf_text = _normalize_text(leaf["text"])
                # 在父块文本中定位该叶子块的位置
                local_start = _safe_find_from(parent_text, leaf_text, local_cursor)
                local_end = local_start + len(leaf_text)

                chunk_items.append(
                    {
                        "local_parent_key": local_parent_key,
                        "chunk_role": "leaf",  # 标记为叶子块（参与检索）
                        "chunk_index": next_chunk_index,
                        "parent_chunk_id": None,
                        "parent_title": parent_title,
                        "block_type": block_type,
                        "child_index": child_index,  # 该叶子在父块中的序号
                        "table_row_from": leaf["row_from"],  # 表格行号范围
                        "table_row_to": leaf["row_to"],
                        "content": leaf_text,  # 叶子块文本（含重复表头）
                        # retrieval_content: 注入父级主题和内容类型的增强检索文本
                        "retrieval_content": _build_retrieval_content(parent_title, block_type, leaf_text),
                        "start_offset": found_at + local_start,  # 在原文中的绝对偏移
                        "end_offset": found_at + local_end,
                        "source_page": source_page,
                        "source_section": source_section,
                    }
                )
                next_chunk_index += 1
                local_cursor = local_end  # 游标推进到当前叶子块末尾

            # 更新搜索游标，跳过已处理的父块
            search_cursor = found_at + len(parent_text)
            continue

        # ===== 分支B：正文类型父块 → 语义切分 =====
        # 先按段落边界切，再按句子边界切，超长句子按字符兜底切
        leaf_text_chunks = _semantic_text_chunks(
            parent_text,
            chunk_size,
            overlap,
            use_semantic_chunking=use_semantic_chunking,
        )
        for child_index, leaf_text in enumerate(leaf_text_chunks, start=1):
            local_start = _safe_find_from(parent_text, leaf_text, local_cursor)
            local_end = local_start + len(leaf_text)

            chunk_items.append(
                {
                    "local_parent_key": local_parent_key,
                    "chunk_role": "leaf",
                    "chunk_index": next_chunk_index,
                    "parent_chunk_id": None,
                    "parent_title": parent_title,
                    "block_type": block_type,
                    "child_index": child_index,
                    "table_row_from": None,
                    "table_row_to": None,
                    "content": leaf_text,
                    # 正文叶子块同样注入父级主题，让检索时能感知上下文
                    "retrieval_content": _build_retrieval_content(parent_title, block_type, leaf_text),
                    "start_offset": found_at + local_start,
                    "end_offset": found_at + local_end,
                    "source_page": source_page,
                    "source_section": source_section,
                }
            )
            next_chunk_index += 1
            local_cursor = local_end

        # 更新搜索游标
        search_cursor = found_at + len(parent_text)

    return chunk_items
