from fastapi import Path
try:
    from pypdf import PdfReader
except ImportError:  # pragma: no cover
    PdfReader = None


def normalize_text(text: str) -> str:
    lines = [line.rstrip() for line in text.splitlines()]
    cleaned: list[str] = []
    previous_blank = False

    for line in lines:
        is_blank = not line.strip()
        if is_blank:
            if not previous_blank:
                cleaned.append("")
            previous_blank = True
            continue

        cleaned.append(line.strip())
        previous_blank = False

    return "\n".join(cleaned).strip()


def parse_txt(file_path: str) -> dict:
    text = Path(file_path).read_text(encoding="utf-8")
    return {
        "full_text": normalize_text(text),
        "pages": [],
        "sections": [],
        "metadata": {},
    }

def parse_md(file_path: str) -> dict:
    text = Path(file_path).read_text(encoding="utf-8")
    return {
        "full_text": normalize_text(text),
        "pages": [],
        "sections": [],
        "metadata": {},
    }

def parse_pdf(file_path: str) -> dict:
    if PdfReader is None:
        raise RuntimeError("pypdf is not installed")

    reader = PdfReader(file_path)
    pages: list[dict] = []
    all_parts: list[str] = []
    # 遍历每一页，提取文本并添加到 pages 列表中，enumerate是python中的内置函数，用于迭代一个序列中的元素，同时返回元素的索引和值
    for index, page in enumerate(reader.pages, start=1):
        page_text = normalize_text(page.extract_text() or "")
        if page_text:
            pages.append({"page": index, "text": page_text})
            all_parts.append(page_text)

    return {
        "full_text": "\n\n".join(all_parts).strip(),
        "pages": pages,
        "sections": [],
        "metadata": {"page_count": len(reader.pages)},
    }


def parse_document(file_path: str, file_type: str) -> dict:
    # 转换为小写，确保文件类型是小写
    file_type = file_type.lower()

    if file_type == "txt":
        return parse_txt(file_path)
    if file_type == "md":
        return parse_md(file_path)
    if file_type == "pdf":
        return parse_pdf(file_path)

    raise ValueError(f"Unsupported file type: {file_type}")