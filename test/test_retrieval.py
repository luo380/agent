from core.service.retrieval import (
    RetrievedChunk,
    build_recall_query_forms,
    coarse_recall_score,
    phrase_overlap_score,
    rerank_chunks,
    tokenize,
)


QUERY = "\u652f\u6301\u4ec0\u4e48\u8bed\u97f3\u52a9\u624b"
RELEVANT_CONTENT = (
    "\u672c\u4ea7\u54c1\u652f\u6301\u5c0f\u7231\u540c\u5b66\u3001"
    "\u5929\u732b\u7cbe\u7075\u548c Google Assistant "
    "\u7b49\u8bed\u97f3\u52a9\u624b\u3002"
)
IRRELEVANT_CONTENT = "\u7ef4\u62a4\u4fdd\u517b\u65f6\u8bf7\u5b9a\u671f\u6e05\u7406\u4e3b\u5237\u548c\u8fb9\u5237\u3002"


def test_tokenize_keeps_searchable_cjk_terms():
    tokens = tokenize(QUERY)

    assert QUERY in tokens
    assert "\u8bed\u97f3\u52a9\u624b" in tokens
    assert "\u652f\u6301" in tokens


def test_phrase_overlap_score_detects_cjk_phrase_match():
    score = phrase_overlap_score(QUERY, RELEVANT_CONTENT)

    assert score > 0


def test_build_recall_query_forms_keeps_focused_question_tail():
    forms = build_recall_query_forms("\u626b\u5730\u673a\u5668\u4eba" + QUERY)

    assert forms[0] == "\u626b\u5730\u673a\u5668\u4eba" + QUERY
    assert QUERY in forms
    assert any(form.startswith("\u652f\u6301") for form in forms[1:])


def test_build_recall_query_forms_keeps_colloquial_voice_assistant_entity():
    forms = build_recall_query_forms("\u6211\u5bb6\u91cc\u6709\u5c0f\u7231\u540c\u5b66\uff0c\u4e0d\u77e5\u9053\u53ef\u4ee5\u63a7\u626b\u5730\u673a\u5668\u4eba\u5417")

    assert any("\u5c0f\u7231\u540c\u5b66" in form for form in forms)
    assert any("\u626b\u5730\u673a\u5668\u4eba" in form for form in forms)


def test_rerank_chunks_boosts_relevant_cjk_phrase_match():
    chunks = [
        RetrievedChunk(
            document_id=1,
            document_name="robot-manual.pdf",
            chunk_id=101,
            chunk_index=0,
            content=RELEVANT_CONTENT,
            source_page=8,
            source_section="page_8",
            vector_score=0.62,
        ),
        RetrievedChunk(
            document_id=1,
            document_name="robot-manual.pdf",
            chunk_id=102,
            chunk_index=1,
            content=IRRELEVANT_CONTENT,
            source_page=6,
            source_section="page_6",
            vector_score=0.66,
        ),
    ]

    reranked = rerank_chunks(QUERY, chunks, top_k=2)

    assert reranked[0].chunk_id == 101
    assert reranked[0].final_score > reranked[1].final_score



def test_coarse_recall_score_prefers_answer_chunk_for_longer_prefixed_query():
    long_query = "\u626b\u5730\u673a\u5668\u4eba" + QUERY
    relevant_score = coarse_recall_score(long_query, RELEVANT_CONTENT, 0.62)
    generic_score = coarse_recall_score(
        long_query,
        "\u626b\u5730\u673a\u5668\u4eba\u548c\u5438\u5c18\u5668\u600e\u4e48\u9009\uff1f",
        0.76,
    )

    assert relevant_score > generic_score



def test_rerank_chunks_prefers_colloquial_voice_assistant_query_match():
    colloquial_query = "\u6211\u5bb6\u91cc\u6709\u5c0f\u7231\u540c\u5b66\uff0c\u4e0d\u77e5\u9053\u53ef\u4ee5\u63a7\u626b\u5730\u673a\u5668\u4eba\u5417"
    chunks = [
        RetrievedChunk(
            document_id=1,
            document_name="robot-manual.pdf",
            chunk_id=301,
            chunk_index=0,
            content="\u5e38\u89c1\u7684\u6709\u5c0f\u7231\u540c\u5b66\u3001\u5929\u732b\u7cbe\u7075\u3001Google Assistant \u7b49\u8bed\u97f3\u52a9\u624b\u3002",
            source_page=3,
            source_section="page_3",
            vector_score=0.56,
        ),
        RetrievedChunk(
            document_id=1,
            document_name="robot-manual.pdf",
            chunk_id=302,
            chunk_index=1,
            content="\u626b\u5730\u673a\u5668\u4eba\u4e00\u822c\u901a\u8fc7 APP \u6216\u6309\u952e\u64cd\u4f5c\uff0c\u53ef\u4ee5\u8fdb\u884c\u6e05\u626b\u548c\u8fd4\u56de\u5145\u7535\u3002",
            source_page=7,
            source_section="page_7",
            vector_score=0.68,
        ),
    ]

    reranked = rerank_chunks(colloquial_query, chunks, top_k=2)

    assert reranked[0].chunk_id == 301


def test_rerank_chunks_keeps_answer_chunk_in_top_results_for_longer_prefixed_query():
    long_query = "\u626b\u5730\u673a\u5668\u4eba" + QUERY
    chunks = [
        RetrievedChunk(
            document_id=1,
            document_name="robot-manual.pdf",
            chunk_id=201,
            chunk_index=0,
            content=RELEVANT_CONTENT,
            source_page=3,
            source_section="page_3",
            vector_score=0.5893,
        ),
        RetrievedChunk(
            document_id=1,
            document_name="robot-manual.pdf",
            chunk_id=202,
            chunk_index=1,
            content="\u626b\u5730\u673a\u5668\u4eba\u548c\u5438\u5c18\u5668\u600e\u4e48\u9009\uff1f",
            source_page=7,
            source_section="page_7",
            vector_score=0.7617,
        ),
    ]

    reranked = rerank_chunks(long_query, chunks, top_k=2)

    assert {item.chunk_id for item in reranked} == {201, 202}
    assert reranked[0].final_score >= reranked[1].final_score
