

def chunk_text(text: str, chunk_size: int = 500, overlap: int = 100) -> list[dict]:
    text = (text or "").strip()
    if not text:
        return []

    if chunk_size <= 0:
        raise ValueError("chunk_size must be > 0")
    if overlap < 0:
        raise ValueError("overlap must be >= 0")
    if overlap >= chunk_size:
        raise ValueError("overlap must be smaller than chunk_size")

    chunks: list[dict] = []
    start = 0
    chunk_index = 0
    text_length = len(text)

    while start < text_length:
        end = min(start + chunk_size, text_length)
        content = text[start:end].strip()

        if content:
            chunks.append(
                {
                    "chunk_index": chunk_index,
                    "content": content,
                    "start_offset": start,
                    "end_offset": end,
                    "source_page": None,
                    "source_section": "",
                }
            )
            chunk_index += 1

        if end >= text_length:
            break

        start = end - overlap

    return chunks