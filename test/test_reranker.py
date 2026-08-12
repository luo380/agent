from dataclasses import dataclass, replace

from core.service.reranker import (
    RerankerConfig,
    cross_encoder_rerank,
    reciprocal_rank_fusion,
)


@dataclass(frozen=True)
class Candidate:
    name: str
    content: str
    final_score: float


class FakeCrossEncoder:
    """Small deterministic fake used instead of downloading model weights."""

    def __init__(self, scores):
        self.scores = scores
        self.received_pairs = []

    def predict(self, pairs, batch_size=16):
        self.received_pairs = list(pairs)
        return self.scores


def test_cross_encoder_can_promote_semantic_match_without_literal_overlap():
    candidates = [
        Candidate(
            name="literal",
            content="设备支持 WiFi 配网。",
            final_score=0.90,
        ),
        Candidate(
            name="semantic",
            content="首次使用时，请按照引导完成无线网络连接。",
            final_score=0.70,
        ),
    ]
    model = FakeCrossEncoder([0.10, 0.95])

    reranked = cross_encoder_rerank(
        "如何把设备连上家里的无线网络？",
        candidates,
        text_getter=lambda item: item.content,
        rule_score_getter=lambda item: item.final_score,
        score_setter=lambda item, score: replace(item, final_score=score),
        top_k=2,
        config=RerankerConfig(
            enabled=True,
            candidate_top_n=2,
            model_weight=0.8,
            rule_weight=0.2,
        ),
        model=model,
    )

    assert reranked[0].name == "semantic"
    assert model.received_pairs[0][0] == "如何把设备连上家里的无线网络？"


def test_cross_encoder_disabled_keeps_existing_rule_order():
    candidates = [
        Candidate("first", "A", 0.90),
        Candidate("second", "B", 0.50),
    ]
    model = FakeCrossEncoder([0.01, 0.99])

    reranked = cross_encoder_rerank(
        "query",
        candidates,
        text_getter=lambda item: item.content,
        rule_score_getter=lambda item: item.final_score,
        score_setter=lambda item, score: replace(item, final_score=score),
        top_k=2,
        config=RerankerConfig(enabled=False),
        model=model,
    )

    assert [item.name for item in reranked] == ["first", "second"]
    assert model.received_pairs == []


def test_reciprocal_rank_fusion_rewards_items_seen_by_multiple_retrievers():
    vector_rank = ["semantic-match", "literal-match", "other"]
    keyword_rank = ["literal-match", "semantic-match", "keyword-only"]

    scores = reciprocal_rank_fusion(
        [vector_rank, keyword_rank],
        k=60,
    )

    assert scores["semantic-match"] > scores["other"]
    assert scores["literal-match"] > scores["keyword-only"]
    assert abs(scores["semantic-match"] - scores["literal-match"]) < 1e-12
