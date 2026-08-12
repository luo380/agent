# 缺口5：文档解析增强（OCR + 表格 + 版面分析）—— 详细实施方案

> 对应文档：《检索与入库技术深化学习规划.md》缺口5
> 预计工作量：基础版（pdfplumber + 表格 + 页眉页脚）2~3 天；完整版（加 PaddleOCR）再加 2 天
> 优先级：【第一周第3步】做完缺口2后做基础版

---

## 一、当前解析能力 vs 目标能力对比

| 维度 | 当前（pypdf 基础版） | 目标（解析增强版） |
|-----|---------------------|-------------------|
| **PDF 文本抽取** | PyPDF（按页粗暴抽，表格变乱码） | pdfplumber（按行/字符级位置信息抽取） |
| **表格识别** | ❌ 完全识别不了，表格变成 `├──┼──┤` 乱线 | ✅ 单元格级识别，直接转 Markdown 表格语法 |
| **扫描件 PDF** | ❌ 返回空字符串（图片里没有文字） | ✅ PaddleOCR，图片里的中文也能抽出文字 |
| **图片嵌入** | ❌ 完全忽略 | ✅ 标记 [图片占位] + 图注上下文 |
| **页眉页脚** | ❌ 全部混进正文，污染检索 | ✅ 重复率检测，自动剔除 |
| **PDF 页码** | ❌ 分块不带页码，答案无法"定位到原文档第几页" | ✅ 每个 chunk 带 page_number，UI 可跳转 |
| **数学公式** | ❌ Latex 公式抽成乱字符 | ✅ （可选高级）Latex 保留 / 图片 OCR |

---

## 二、解析策略链设计（Fallback 多层降级）

不要一上来就上最重的 OCR，按「从快到慢、从轻到重」的顺序尝试：

```
输入 PDF 文件（本地路径 file_path）
    │
    ▼
┌─────────────────────────────────────┐
│  Step 1：pypdf 快速粗判（0.1秒）     │
│  每页文字字符数之和 ≥ 每页平均 200字  │
│   → 判定为「电子版 PDF」→ 跳 Step 2  │
│   → 判定为「扫描件 PDF」→ 跳 Step 4  │
└───────────────────┬─────────────────┘
                    │
          ┌─────────┴─────────┐
          ▼                   ▼
┌────────────────────┐  ┌────────────────────┐
│ Step 2：pdfplumber │  │ Step 4：PaddleOCR  │
│ 精准抽取（中等耗时）│  │ 扫描件识别（很慢） │
│ - 文本行按位置排序  │  │ - 按页逐张识别    │
│ - 表格区域单独提取  │  │ - 输出带坐标文字  │
│ - 页眉页脚去重     │  │ - 页脚结构和Step3一致│
└─────────┬──────────┘  └─────────┬──────────┘
          │                       │
          └───────────┬───────────┘
                      ▼
          ┌─────────────────────────────┐
          │ Step 3：结构化输出           │
          │ （所有路径最后都走这里）      │
          │ 输出:                        │
          │   - full_text: str           │
          │   - pages: list[{            │
          │       page_number,           │
          │       text,                  │
          │       tables: list[md_table],│
          │       page_images: bool      │
          │     }]                       │
          └─────────────────────────────┘
```

**为什么这样设计？**
- 大部分 PDF 都是电子版（80%以上场景），pdfplumber 已经够用，没必要每张图跑 OCR（慢 50~100 倍）
- 只有 pypdf 抽出来 <200 字/页 时，才判定为扫描件走 OCR（快速预检，不浪费时间）

---

## 三、分步实施方案

### 步骤 1：依赖安装

```bash
# 核心依赖：pdfplumber（轻量，精准 PDF 解析）
pip install pdfplumber>=0.11.0

# === 扫描件分支（可选，等基础版稳定了再加）===
# PaddleOCR：中文最强开源 OCR（GPU/CPU 都能跑）
pip install paddleocr>=2.7 paddlepaddle>=2.6
# 注意：首次运行会自动下载 ~150MB 的中英文模型
```

---

### 步骤 2：重构 `parse_pdf()`（基础版，2 天）

#### 2.1 核心代码改造（`document_parser.py`）

**替换原来的 pypdf `parse_pdf()` 函数**，整个函数重写：

```python
def parse_pdf(file_path: str) -> tuple[str, dict]:
    """
    【解析增强版】解析 PDF 文件

    策略链：pypdf 预检 → pdfplumber 精准抽取 → 结构化输出
    如果是扫描件（文字极少），暂时返回空 + has_images=True 标记，留待后续接 OCR

    Args:
        file_path: PDF 文件本地路径

    Returns:
        (full_text, meta)
            full_text: 合并了正文 + Markdown 表格的完整文本
            meta: 解析元信息，包含
                - page_count: 总页数
                - has_images: 是否包含图片（疑似扫描件）
                - is_scanned: 是否判定为扫描件（提示用户需要开 OCR）
                - tables_count: 识别出的表格数量
                - pages: 逐页结构化信息（page_number/tables/page_text）
    """
    # ---------- Step A: pypdf 快速预检，判断是不是扫描件 ----------
    from pypdf import PdfReader as PyPdfReader
    try:
        pypdf_reader = PyPdfReader(file_path)
        total_text_len = sum(
            len((page.extract_text() or "").strip())
            for page in pypdf_reader.pages
        )
        page_count = len(pypdf_reader.pages)
        avg_text_per_page = total_text_len / max(page_count, 1)
    except Exception:
        # pypdf 打不开就继续，让 pdfplumber 再试一次
        avg_text_per_page = 0
        page_count = 0

    # 经验阈值：平均每页 < 100 字 → 大概率是扫描件/纯图片PDF
    is_scanned = avg_text_per_page < 100 and page_count > 0
    has_tables = False
    tables_total_count = 0

    # ---------- Step B: pdfplumber 精准抽取 ----------
    import pdfplumber

    # 缓存每页的文本行和表格，后面做"页眉页脚去重"
    all_pages_header_lines = []  # list[list[str]]，每页前3行
    all_pages_footer_lines = []  # list[list[str]]，每页后3行
    pages_structured = []        # list[dict]，每页结构化信息

    # 最终拼好的全文（正文 + 表格插入到对应位置）
    final_paragraphs: list[str] = []

    with pdfplumber.open(file_path) as pdf:
        page_count = page_count or len(pdf.pages)

        for page_idx, page in enumerate(pdf.pages, start=1):
            # B-1: 抽取该页的所有表格（优先处理表格，不混进正文）
            page_tables_markdown = []
            try:
                # extract_tables() 返回 list[list[list[str]]]
                # 外层: 该页有几张表
                # 中层: 每张表有几行
                # 内层: 每行有几个单元格
                raw_tables = page.extract_tables() or []
                for table_rows in raw_tables:
                    if not table_rows or len(table_rows) < 2:
                        continue  # 空表或单行表，忽略
                    md = _table_rows_to_markdown(table_rows)
                    if md:
                        page_tables_markdown.append(md)
                        tables_total_count += 1
                        has_tables = True
            except Exception:
                # 表格抽取失败不影响整体流程
                raw_tables = []
                page_tables_markdown = []

            # B-2: 抽取该页正文文本（带行位置信息）
            # x_tolerance/y_tolerance 调参：让"同一条横线"上的字合并成一行
            try:
                page_text = page.extract_text(
                    x_tolerance=2,    # 水平方向差2像素就算同一列
                    y_tolerance=3,    # 垂直方向差3像素换行
                ) or ""
            except Exception:
                page_text = ""

            # B-3: 页眉页脚识别（先收集每页首尾3行，最后统一做去重）
            text_lines = [ln.strip() for ln in page_text.splitlines() if ln.strip()]
            all_pages_header_lines.append(text_lines[:3])
            all_pages_footer_lines.append(text_lines[-3:] if len(text_lines) >= 3 else text_lines)

            # B-4: 表格插入到对应位置（简单版：先正文、后表格；进阶版用页面坐标拼接）
            #   对于 RAG 来说，顺序对相似度影响没那么大，先简单处理
            page_final_parts = [page_text]
            if page_tables_markdown:
                page_final_parts.append("\n\n".join(page_tables_markdown))
            page_full_text = "\n\n".join(p for p in page_final_parts if p.strip())

            # B-5: 保存该页结构化信息（给后续分块 page_number 用）
            pages_structured.append({
                "page_number": page_idx,
                "text": page_full_text,
                "tables_count": len(page_tables_markdown),
            })

            final_paragraphs.append(page_full_text)

    # ---------- Step C: 页眉页脚去重（统计每页前3行/后3行的重复率） ----------
    # 逻辑：如果某一行文本在 >= 80% 的页面里都出现（而且在同样的位置），判定为页眉页脚
    if page_count >= 3:
        header_to_remove = _find_repeated_lines(all_pages_header_lines, page_count, threshold=0.8)
        footer_to_remove = _find_repeated_lines(all_pages_footer_lines, page_count, threshold=0.8)
        if header_to_remove or footer_to_remove:
            # 重新扫一遍 final_paragraphs，去掉这些行
            final_paragraphs = _strip_headers_footers(
                final_paragraphs, header_to_remove, footer_to_remove
            )
            # 同步清理 pages_structured 里的 text
            for page_info in pages_structured:
                page_info["text"] = _strip_headers_footers_single(
                    page_info["text"], header_to_remove, footer_to_remove
                )

    full_text = "\n\n".join(final_paragraphs).strip()

    return full_text, {
        "page_count": page_count,
        "has_images": is_scanned,
        "is_scanned": is_scanned,
        "tables_count": tables_total_count,
        "pages": pages_structured,
    }
```

#### 2.2 配套 3 个工具函数

```python
def _table_rows_to_markdown(table_rows: list[list[str | None]]) -> str | None:
    """
    把 pdfplumber 抽出来的二维数组表格，转成 Markdown 表格语法

    示例输入:
        [
            ["型号", "屏幕尺寸", "价格"],
            ["Mate60",  "6.69寸", "5499"],
            ["Mate60Pro", "6.82寸", "6499"],
        ]

    输出:
        | 型号 | 屏幕尺寸 | 价格 |
        | --- | --- | --- |
        | Mate60 | 6.69寸 | 5499 |
        | Mate60Pro | 6.82寸 | 6499 |
    """
    if not table_rows or not table_rows[0]:
        return None

    # 清理 None 和多余空白
    def clean(cell):
        if cell is None:
            return ""
        return str(cell).replace("|", "\\|").strip()  # 转义管道符

    cleaned_rows = [[clean(cell) for cell in row] for row in table_rows]

    # 对齐列数（有的行可能少一个单元格，补空）
    max_cols = max(len(r) for r in cleaned_rows)
    for row in cleaned_rows:
        while len(row) < max_cols:
            row.append("")

    header = cleaned_rows[0]
    body_rows = cleaned_rows[1:] or []
    if not body_rows:
        # 只有表头的表，认为是无效表
        return None

    separator = ["---"] * max_cols
    lines = [
        "| " + " | ".join(header) + " |",
        "| " + " | ".join(separator) + " |",
    ]
    for body_row in body_rows:
        lines.append("| " + " | ".join(body_row) + " |")

    # RAG 友好：表格前加"这是一张表格"的前置描述，提升向量检索命中率
    return "【以下为表格内容】\n" + "\n".join(lines)


def _find_repeated_lines(all_lines_across_pages: list[list[str]], page_count: int, threshold: float = 0.8) -> set[str]:
    """
    找出重复的页眉/页脚行。

    原理：每页的前3行（或后3行）里，如果某句话在 >= threshold 比例的页面里都出现了，
    就认为它是页眉/页脚（不是正文内容）。

    Args:
        all_lines_across_pages: list[list[str]]，每页对应"那几行候选"
        page_count: 总页数
        threshold: 出现页面占比阈值，默认 0.8 = 80%页面出现就删

    Returns:
        set[str]，需要被删除的行集合
    """
    if page_count < 3:
        return set()  # 页数太少，没法做统计判断

    counter: dict[str, int] = {}
    for page_lines in all_lines_across_pages:
        for line in set(page_lines):  # 同一页出现多次算一次
            if len(line) < 3:
                continue  # "1" / "-" 这种单字符忽略
            counter[line] = counter.get(line, 0) + 1

    to_remove = set()
    min_pages_for_remove = int(page_count * threshold)
    for line, cnt in counter.items():
        if cnt >= min_pages_for_remove:
            to_remove.add(line)
    return to_remove


def _strip_headers_footers(
    paragraphs: list[str],
    header_to_remove: set[str],
    footer_to_remove: set[str],
) -> list[str]:
    """批量去除每页的页眉页脚行"""
    if not header_to_remove and not footer_to_remove:
        return paragraphs
    result = []
    for para in paragraphs:
        result.append(_strip_headers_footers_single(para, header_to_remove, footer_to_remove))
    return result


def _strip_headers_footers_single(
    text: str,
    header_to_remove: set[str],
    footer_to_remove: set[str],
) -> str:
    """去除单页文本的页眉页脚行（只剥去前3行和后3行，不影响正文中间）"""
    lines = text.splitlines()
    if not lines:
        return text

    # 处理前3行（页眉候选区）
    head_end = min(3, len(lines))
    for i in range(head_end):
        if lines[i].strip() in header_to_remove:
            lines[i] = "__HEADER_REMOVED__"  # 占位，后面统一删

    # 处理后3行（页脚候选区）
    tail_start = max(0, len(lines) - 3)
    for i in range(tail_start, len(lines)):
        if lines[i].strip() in footer_to_remove:
            lines[i] = "__FOOTER_REMOVED__"

    # 清理占位符和空行
    filtered = [ln for ln in lines if ln not in ("__HEADER_REMOVED__", "__FOOTER_REMOVED__")]
    return "\n".join(filtered).strip()
```

---

### 步骤 3：分块层透传 page_number（0.5 天）

解析已经能拿到每页的信息了，现在需要把 `page_number` 一路传到 chunk 的 metadata 里：

#### 3.1 `parse_pdf()` 返回的 pages 信息，在调用方（knowledge_service.py）里传进 chunk_document：

```python
# knowledge_service.py 原来：
text = parser.parse(uploaded_file.saved_path, file_ext)

# 改成：
text, parse_meta = parser.parse_detailed(uploaded_file.saved_path, file_ext)
# parse_meta 里有 pages（逐页结构信息）

# 传给分块模块，让分块时知道哪段文字来自哪页
chunks, titles, metadatas = chunker.chunk_document(
    document_id=doc.id,
    raw_text=text,
    file_type=file_ext,
    file_name=doc.filename,
    upload_date=upload_date_str,
    doc_category=doc.doc_category,
    parse_pages=parse_meta.get("pages"),  # 【新增】每页结构
    use_semantic_chunking=settings.ENABLE_SEMANTIC_CHUNKING,
)
```

#### 3.2 分块层根据字符偏移映射 page_number

原理：`pages` 里每页有自己的 `text`，`full_text` 是所有页拼起来的。
给 hierarchical_chunking 传的字符偏移，对应 `pages` 里哪一页，就能找到 `page_number`。

```python
# 新增 pages_index，快速查"第 N 个字符属于第几页"
class HierarchicalChunker:
    def _build_pages_index(self, pages: list[dict]) -> list[tuple[int, int, int]]:
        """
        构建 字符偏移 → 页码 的快速索引。
        返回: [(char_start, char_end, page_number), ...]
        """
        pages_index = []
        cursor = 0
        for page in pages:
            page_text = page.get("text") or ""
            pages_index.append((cursor, cursor + len(page_text), page["page_number"]))
            cursor += len(page_text) + 2  # +2 对应 "\n\n" 的分隔符
        return pages_index

    def _lookup_page_number(self, char_offset: int, pages_index: list[tuple[int, int, int]]) -> int | None:
        """根据字符偏移查找属于哪一页"""
        for start, end, page_no in pages_index:
            if start <= char_offset < end:
                return page_no
        return None
```

---

### 步骤 4（可选）：PaddleOCR 扫描件分支（2 天）

这部分工作量大，建议等基础版稳定后再加，这里只给出关键代码框架：

```python
def parse_scanned_pdf_paddleocr(file_path: str) -> tuple[str, dict]:
    """
    【扫描件分支】用 PaddleOCR 解析纯图片 PDF（文字嵌在图片里）

    步骤：
        1. pdf2image 把 PDF 每页转成 PIL.Image
        2. PaddleOCR 逐张图片识别（返回 文字 + 位置坐标）
        3. 按坐标从上到下从左到右排序，拼成文本
        4. 最后走和 Step 3 一样的结构化输出（page_number/表格暂不支持）
    """
    from paddleocr import PaddleOCR
    from pdf2image import convert_from_path

    # use_angle_cls=True：处理扫描件歪了的情况（自动旋转校正）
    # lang='ch'：中英文混合模型
    ocr = PaddleOCR(use_angle_cls=True, lang='ch', show_log=False)

    images = convert_from_path(file_path, dpi=200)  # 200dpi 平衡精度和速度

    final_paragraphs = []
    pages_structured = []
    for page_idx, img in enumerate(images, start=1):
        result = ocr.ocr(img, cls=True)
        # OCR 结果格式：[[ [x1,y1,x2,y2,x3,y3,x4,y4], (text, confidence) ], ...]
        text_lines = []
        if result and result[0]:
            for line in result[0]:
                box, (txt, score) = line
                if score > 0.5:  # 置信度低于0.5的扔掉（避免乱码）
                    # 按 y 坐标(行)和 x 坐标(列)排序，pdfplumber 类似
                    text_lines.append((box[0][1], box[0][0], txt))  # (y, x, text)
        text_lines.sort()  # 先按 y 排序（从上到下），同一 y 差不多按 x 排序
        page_text = "\n".join(t for _, _, t in text_lines)

        pages_structured.append({
            "page_number": page_idx,
            "text": page_text,
            "tables_count": 0,  # OCR 版的表格识别需要 PP-Structure，这里先不做
        })
        final_paragraphs.append(page_text)

    return "\n\n".join(final_paragraphs), {
        "page_count": len(images),
        "has_images": True,
        "is_scanned": True,
        "tables_count": 0,
        "pages": pages_structured,
        "ocr_confidence_avg": ...,  # 可以算平均置信度作为质量指标
    }
```

然后在 `parse_pdf()` 的开头加上判断：
```python
    # 如果判定为扫描件，走 OCR 分支
    if is_scanned:
        try:
            return parse_scanned_pdf_paddleocr(file_path)
        except Exception as e:
            # OCR 依赖没装 / 模型下载失败，打个 warning 继续走 pdfplumber
            import warnings
            warnings.warn(f"PaddleOCR 解析扫描件失败，降级为普通 PDF：{e}")
```

---

## 四、集成测试验证清单

| 测试场景 | 期望结果 |
|---------|---------|
| 电子版 PDF（纯文字） | 文字完整抽取，顺序正确，比 pypdf 版本少乱码 |
| PDF 带简单表格（3列10行） | 输出带 Markdown 表格语法，表格内容可被检索命中 |
| 带复杂表格（合并单元格） | 表格不会变乱线，缺合并单元格信息至少文字是可读的 |
| 10 页 PDF，每页页眉 "XX公司机密文档" + 页脚 "第 X 页 / 共 10 页" | 页眉页脚自动被删除，不污染检索 |
| PDF 带页码 5~50 | chunk.metadata.page_number 能对得上真实页码 |
| 扫描件 PDF（纯图片，没有文字层） | pypdf 版返回空字符串，OCR 版能抽出正确中文 |

---

## 五、关键注意点

1. **先上基础版**：pdfplumber + 表格 + 页眉页脚 三件套，覆盖 80% 以上真实场景，PaddleOCR 等用户真的会传扫描件再上。
2. **表格位置对齐**：进阶需求可以用 pdfplumber 的 `page.find_tables()` 拿到每张表的 `bbox` 坐标（left/top/right/bottom），然后根据坐标把表格插入到正文的对应位置（而不是"先正文后表格"拼到最后），RAG 效果会更好。
3. **PP-Structure 是大招**：Paddle 生态的 PP-Structure 可以直接识别「标题/正文/表格/图片」四类区域，比手写坐标判断准得多，但是模型更大（首次下载 300MB+），对 GPU 要求高，放到长期规划。
4. **性能监控**：pdfplumber 比 pypdf 慢 2~5 倍（因为解析的更精细），一个 100 页 PDF 大概 2~5 秒。**这也是缺口6（异步导入）必须先做的原因之一**——同步解析用户会在那儿转圈半天。