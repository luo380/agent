from langchain_core.documents import Document

from core.service.rag_langchain_native import (
    build_citations_from_documents,
    ensure_answer_has_document_citations,
)


def test_auto_reference_block_hides_pdf_page_placeholders_and_deduplicates_locations():
    documents = [
        Document(
            page_content="First chunk on page 6",
            metadata={
                "document_id": 1,
                "document_name": "robot-manual.pdf",
                "chunk_id": 101,
                "chunk_index": 0,
                "source_page": 6,
                "source_section": "page_6",
                "score": 0.91,
            },
        ),
        Document(
            page_content="Second chunk on page 6",
            metadata={
                "document_id": 1,
                "document_name": "robot-manual.pdf",
                "chunk_id": 102,
                "chunk_index": 1,
                "source_page": 6,
                "source_section": "page_6",
                "score": 0.89,
            },
        ),
        Document(
            page_content="Chunk on page 7",
            metadata={
                "document_id": 1,
                "document_name": "robot-manual.pdf",
                "chunk_id": 103,
                "chunk_index": 2,
                "source_page": 7,
                "source_section": "page_7",
                "score": 0.88,
            },
        ),
    ]

    answer = ensure_answer_has_document_citations("知识库回答", documents)

    assert "page_6" not in answer
    assert "page_7" not in answer
    assert answer.count("robot-manual.pdf；第 6 页") == 1
    assert answer.count("robot-manual.pdf；第 7 页") == 1
    assert "[1] robot-manual.pdf；第 6 页" in answer
    assert "[2] robot-manual.pdf；第 7 页" in answer



def test_inline_citation_marks_still_get_reference_block():
    documents = [
        Document(
            page_content="Voice assistant support",
            metadata={
                "document_id": 1,
                "document_name": "robot-manual.pdf",
                "chunk_id": 301,
                "chunk_index": 0,
                "source_page": 8,
                "source_section": "page_8",
                "score": 0.92,
            },
        ),
    ]

    answer = ensure_answer_has_document_citations(
        "扫地机器人通常支持以下语音助手：[1]",
        documents,
    )

    assert "扫地机器人通常支持以下语音助手：[1]" in answer
    assert "参考来源：" in answer
    assert answer.count("[1]") == 2
    assert "robot-manual.pdf；第 8 页" in answer

def test_build_citations_from_documents_keeps_meaningful_sections_only():
    documents = [
        Document(
            page_content="PDF chunk",
            metadata={
                "document_id": 1,
                "document_name": "robot-manual.pdf",
                "chunk_id": 201,
                "chunk_index": 0,
                "source_page": 3,
                "source_section": "page_3",
                "score": 0.9,
            },
        ),
        Document(
            page_content="DOCX chunk",
            metadata={
                "document_id": 2,
                "document_name": "guide.docx",
                "chunk_id": 202,
                "chunk_index": 1,
                "source_page": None,
                "source_section": "maintenance",
                "score": 0.8,
            },
        ),
    ]

    citations = build_citations_from_documents(documents)

    assert citations[0]["source_page"] == 3
    assert citations[0]["source_section"] == ""
    assert citations[1]["source_section"] == "maintenance"
