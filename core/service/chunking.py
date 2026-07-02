


def _validate_chunk_args(chunk_size: int, overlap: int) -> None:
    """
    统一校验切块参数，避免非法配置导致死循环或错位切片。
    """
    if chunk_size <= 0:
        raise ValueError("chunk_size must be > 0")
    if overlap < 0:
        raise ValueError("overlap must be >= 0")
    if overlap >= chunk_size:
        raise ValueError("overlap must be smaller than chunk_size")


def _chunk_single_text(
    text: str,
    *,
    chunk_size: int,          # 每个 chunk 的最大字符数
    overlap: int,              # 相邻 chunk 之间重叠的字符数，防止语义在边界处被截断
    start_chunk_index: int,    # 起始编号，多段文本连续切块时保证编号不重复
    base_offset: int = 0,      # 基础偏移量，用于将 offset 映射回完整文档中的绝对位置
    source_page: int | None = None,  # 来源页码（按页切块时传入）
    source_section: str = "",        # 来源章节名（按章节切块时传入）
) -> tuple[list[dict], int]:
    """
    将一段文本切成多个 chunk。

    这里之所以写成内部函数，是为了复用到：
    - 整篇纯文本切块
    - 按页切块
    - 按章节切块

    返回值 (tuple[list[dict], int])：
        [0] list[dict]：当前文本生成的 chunk 列表，每个 chunk 为一个字典：
            - chunk_index  (int) : chunk 的全局编号，从 start_chunk_index 开始递增
            - content      (str) : chunk 的文本内容（已去首尾空白）
            - start_offset (int) : chunk 在完整文档中的起始偏移（= base_offset + start）
            - end_offset   (int) : chunk 在完整文档中的结束偏移（= base_offset + end）
            - source_page  (int|None) : 来源页码（按页切块时有效）
            - source_section (str)    : 来源章节名（按章节切块时有效）
        [1] int：下一段文本应该接着使用的 chunk_index（保证多段文本编号连续）

    示例：若 start_chunk_index=0 且切出 3 个 chunk，则返回 ([chunk0,chunk1,chunk2], 3)
    """
    # 预处理：去除首尾空白，防空字符串
    clean_text = (text or "").strip()
    if not clean_text:
        # 空文本不产生任何 chunk，直接返回空列表，chunk_index 保持不变
        return [], start_chunk_index

    chunks: list[dict] = []  # 收集所有切出的 chunk
    start = 0  # 当前窗口在文本中的起始位置
    chunk_index = start_chunk_index  # 全局递增的 chunk 编号
    text_length = len(clean_text)  # 文本总长度

    # 滑动窗口：每次取 [start, end) 范围的子串作为一个 chunk
    while start < text_length:
        # 计算当前窗口的结束位置，不能超过文本末尾
        end = min(start + chunk_size, text_length)
        # 截取子串并去除首尾空白（防止纯空白 chunk）
        content = clean_text[start:end].strip()

        if content:
            chunks.append(
                {
                    "chunk_index": chunk_index,  # chunk 的全局编号，从 start_chunk_index 开始递增
                    "content": content,  # chunk 的文本内容（已去首尾空白）
                    #start_offset / end_offset 尽量定位到 full_text 中的相对位置
                    #这样后面如果你要做"原文高亮"或"回跳定位"，数据是可用的。
                    #base_offset 让 offset 能反映该片段在完整文档中的绝对位置
                    "start_offset": base_offset + start,  # chunk 在完整文档中的起始偏移（字符位置）
                    "end_offset": base_offset + end,  # chunk 在完整文档中的结束偏移（字符位置）
                    "source_page": source_page,  # 来源页码（按页切块时有效，否则为 None）
                    "source_section": source_section,  # 来源章节名（按章节切块时有效，否则为空串）
                }
            )
            chunk_index += 1  # 编号递增，为下一个 chunk 准备

        # 如果窗口已经到达或超过文本末尾，切块完成
        if end >= text_length:
            break

        # 窗口滑动：从 end 回退 overlap 个字符，形成重叠区域
        # 这样相邻 chunk 会有 overlap 长度的公共内容，避免语义被截断
        start = end - overlap

    # 返回：chunk 列表 + 下一段文本应使用的起始编号
    return chunks, chunk_index


def chunk_text(text: str, chunk_size: int = 500, overlap: int = 100) -> list[dict]:
    """
    保留原来的简单接口，兼容旧调用方。

    适用场景：
    - 只有纯文本，没有页码/章节信息
    - 单元测试或快速验证
    """
    _validate_chunk_args(chunk_size, overlap)

    chunks, _ = _chunk_single_text(
        text,
        chunk_size=chunk_size,
        overlap=overlap,
        start_chunk_index=0,
        base_offset=0,
        source_page=None,
        source_section="",
    )
    return chunks


def chunk_parsed_document(parsed: dict, chunk_size: int = 500, overlap: int = 100) -> list[dict]:
    """
    按"解析后的结构化结果"切块。

    优先级（从高到低）：
    1. 如果有 pages，就按页切块，并把页码写进 source_page
    2. 否则如果有 sections，就按 section 切块，并把章节名写进 source_section
    3. 都没有时，退化成整篇 full_text 切块

    这样做的价值：
    - PDF / PPTX 可以得到页级引用
    - DOCX / Excel 可以得到章节/工作表级引用
    - 最终 RAG 回答更像真实知识库，而不是"只会说来自某个文档"

    参数：
        parsed (dict)     : 解析后的文档结构，期望包含以下字段（可选）：
            - full_text (str)                : 完整文本内容
            - pages (list[dict])             : 按页划分的内容，每项应含 "text" 和 "page"
            - sections (list[dict])          : 按章节划分的内容，每项应含 "text" 和 "section"
        chunk_size (int)  : 每个 chunk 的最大字符数，默认 500
        overlap (int)     : 相邻 chunk 的重叠字符数，默认 100

    返回：
        list[dict]：统一格式的 chunk 列表，每个 chunk 包含内容、偏移、来源页码/章节等信息
    """
    # 统一校验 chunk_size 和 overlap，避免非法配置导致死循环或错位切片
    _validate_chunk_args(chunk_size, overlap)

    # 从解析结果中提取关键数据：完整文本、页列表、章节列表
    full_text = (parsed.get("full_text") or "").strip()  # 完整文本（去首尾空白）
    pages = parsed.get("pages") or []                    # 页列表（如 PDF/PPTX 解析结果）
    sections = parsed.get("sections") or []              # 章节列表（如 DOCX/Markdown 解析结果）

    # 空文档直接返回空列表，避免后续空循环
    if not full_text:
        return []

    chunks: list[dict] = []       # 收集所有切出的 chunk，最终作为返回值
    next_chunk_index = 0          # 下一个 chunk 的起始编号，保证多段文本编号连续递增

    # search_cursor 用于在 full_text 中大致定位当前 page/section 的起始位置，
    # 这样生成的 start_offset / end_offset 会更接近真实全文位置（方便"原文高亮"）。
    search_cursor = 0

    # ========== 策略一：按页切块（优先级最高） ==========
    if pages:
        for item in pages:
            # 提取当前页的文本内容，防空字符串
            page_text = (item.get("text") or "").strip()
            if not page_text:
                continue  # 空页跳过，不浪费 chunk 编号

            # 尝试在全文中找到当前页文本的位置（从上次搜索位置开始，保证顺序匹配）
            # 如果找不到（比如文本被清洗后不一致），就退回到 search_cursor 位置作为估算
            found_at = full_text.find(page_text, search_cursor)
            if found_at == -1:
                found_at = search_cursor

            # 调用底层切块函数，为当前页生成 chunk
            # - base_offset=found_at：让 chunk 的 offset 反映在全文中的位置
            # - source_page：记录来源页码，方便后续 RAG 引用时说"第X页"
            # - source_section：如果当前页恰好属于某个章节，也记录下来
            page_chunks, next_chunk_index = _chunk_single_text(
                page_text,
                chunk_size=chunk_size,
                overlap=overlap,
                start_chunk_index=next_chunk_index,
                base_offset=found_at,
                source_page=item.get("page"),
                source_section=item.get("section", "") or "",
            )
            # 将当前页的 chunk 追加到总列表
            chunks.extend(page_chunks)

            # 更新搜索游标，下一页从当前页结束位置开始搜索，保证顺序匹配
            search_cursor = found_at + len(page_text)

        # 按页切块完成，直接返回
        return chunks

    # ========== 策略二：按章节切块 ==========
    if sections:
        for item in sections:
            # 提取当前章节的文本内容，防空字符串
            section_text = (item.get("text") or "").strip()
            if not section_text:
                continue  # 空章节跳过

            # 同样在全文中定位章节起始位置，失败则用 search_cursor 作为估算
            found_at = full_text.find(section_text, search_cursor)
            if found_at == -1:
                found_at = search_cursor

            # 调用底层切块函数，为当前章节生成 chunk
            # - source_page=None：按章节切块时不区分页码
            # - source_section：记录来源章节名，方便后续 RAG 引用时说"来自XX章节"
            section_chunks, next_chunk_index = _chunk_single_text(
                section_text,
                chunk_size=chunk_size,
                overlap=overlap,
                start_chunk_index=next_chunk_index,
                base_offset=found_at,
                source_page=None,
                source_section=item.get("section", "") or "",
            )
            # 将当前章节的 chunk 追加到总列表
            chunks.extend(section_chunks)

            # 更新搜索游标，下一章节从当前章节结束位置开始搜索
            search_cursor = found_at + len(section_text)

        # 按章节切块完成，直接返回
        return chunks

    # ========== 策略三：降级为整篇文本切块 ==========
    # 没有 pages / sections 时，退回到最基础的全文切块逻辑
    # - start_chunk_index=0：从头开始编号
    # - base_offset=0：不需要偏移校正
    # - source_page/source_section 为空：没有更细粒度的来源信息
    fallback_chunks, _ = _chunk_single_text(
        full_text,
        chunk_size=chunk_size,
        overlap=overlap,
        start_chunk_index=0,
        base_offset=0,
        source_page=None,
        source_section="",
    )
    return fallback_chunks