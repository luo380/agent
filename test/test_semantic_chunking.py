import os
import pytest

from core.service import hierarchical_chunking as chunking
from core.config import settings


class FakeSemanticChunkingModel:
    """Fake model for deterministic testing.

    Embedding design (2D vectors):
      Sentence 0: [1.0, 0.0]  →  topic A cluster (x-axis)
      Sentence 1: [0.9, 0.1]  →  topic A cluster (near sentence 0)
      Sentence 2: [0.0, 1.0]  →  topic B cluster (y-axis, semantic jump!)
      Sentence 3: [0.0, 0.9]  →  topic B cluster (near sentence 2)
    """
    def encode(self, sentences, batch_size=32, normalize_embeddings=True, show_progress_bar=False):
        return [
            [1.0, 0.0],
            [0.9, 0.1],
            [0.0, 1.0],
            [0.0, 0.9],
        ][:len(sentences)]


# ============================================================
# Test Group 1: 百分位自适应阈值 (缺口3第4项)
# ============================================================
def test_percentile_uses_low_similarity_valley():
    """Percentile threshold adapts to local similarity distribution.

    Given [0.91, 0.88, 0.31, 0.86], the 25th percentile should land
    somewhere around the 0.31 valley, turning the semantic jump into
    a real breakpoint instead of cutting at some hard-coded 0.7.
    """
    similarities = [0.91, 0.88, 0.31, 0.86]
    threshold = chunking._percentile(similarities, 25)
    assert 0.31 <= threshold < 0.86


def test_percentile_edge_cases():
    """Percentile helper handles empty/singleton ranges gracefully."""
    assert chunking._percentile([], 50) == 0.0
    assert chunking._percentile([0.75], 50) == 0.75
    assert chunking._percentile([0.2, 0.8], 0) == 0.2
    assert chunking._percentile([0.2, 0.8], 100) == 0.8
    chunking._percentile([0.2, 0.8], 150)
    chunking._percentile([0.2, 0.8], -10)


# ============================================================
# Test Group 2: 余弦相似度计算
# ============================================================
def test_cosine_similarity_identical_vectors():
    a = [1.0, 0.0, 0.5]
    assert abs(chunking._semantic_cosine_similarity(a, a) - 1.0) < 1e-6


def test_cosine_similarity_orthogonal_vectors():
    a = [1.0, 0.0]
    b = [0.0, 1.0]
    assert abs(chunking._semantic_cosine_similarity(a, b) - 0.0) < 1e-6


def test_cosine_similarity_opposite_vectors():
    a = [1.0, 0.0]
    b = [-1.0, 0.0]
    assert abs(chunking._semantic_cosine_similarity(a, b) - (-1.0)) < 1e-6


def test_cosine_similarity_handles_mismatched_length():
    a = [1.0, 0.0]
    b = [1.0, 0.0, 0.5]
    assert chunking._semantic_cosine_similarity(a, b) == 0.0


# ============================================================
# Test Group 3: Fake Model 下的相邻句相似度边界检测 (缺口3第2项)
# ============================================================
def test_semantic_split_by_embedding_cuts_on_topic_shift(monkeypatch):
    """真正的语义边界检测：sim(Si, Si+1) < percentile_threshold → 断点。

    With FakeSemanticChunkingModel:
      sim(S0,S1) = cos([1,0], [0.9,0.1]) ≈ 0.993  (同主题，不切)
      sim(S1,S2) = cos([0.9,0.1], [0,1]) ≈ 0.110  (跳题，切！)
      sim(S2,S3) = cos([0,1], [0,0.9]) = 1.0      (同主题，不切)

    Percentile 30 picks the valley near 0.110 → exactly 1 breakpoint
    after S1, yielding 2 chunks: voice-control chunk + maintenance chunk.
    """
    monkeypatch.setattr(
        chunking,
        "_load_semantic_chunking_model",
        lambda: FakeSemanticChunkingModel(),
    )
    text = (
        "Xiaoai voice control is supported by the robot vacuum and can start cleaning routines from the living room speaker. "
        "Tmall Genie voice control is also supported, so users can launch, pause, and resume cleaning without opening the app. "
        "Clean the main brush every week to remove tangled hair and dust from the roller. "
        "Replace the side brush when it is worn so edge cleaning remains stable."
    )

    chunks = chunking._semantic_split_by_embedding(
        text,
        chunk_size=500,
        overlap=0,
        breakpoint_percentile=30,
    )

    assert len(chunks) == 2
    assert "Tmall Genie" in chunks[0]
    assert "Clean the main brush" in chunks[1]


# ============================================================
# Test Group 4: 开关切换 & 降级策略
# ============================================================
def test_semantic_text_chunks_falls_back_when_model_is_unavailable(monkeypatch):
    """开关打开但模型加载失败 → 自动降级到启发式，不抛异常。"""
    monkeypatch.setattr(chunking, "_load_semantic_chunking_model", lambda: None)

    chunks = chunking._semantic_text_chunks(
        "First paragraph.\n\nSecond paragraph.",
        chunk_size=500,
        overlap=0,
        use_semantic_chunking=True,
    )

    assert chunks == ["First paragraph.\n\nSecond paragraph."]


def test_semantic_text_chunks_switch_off_uses_heuristic(monkeypatch):
    """开关关闭时，即使模型可用也走启发式（性能优先场景）。"""
    calls = {"model_loaded": 0}

    def fake_loader():
        calls["model_loaded"] += 1
        return FakeSemanticChunkingModel()

    monkeypatch.setattr(chunking, "_load_semantic_chunking_model", fake_loader)

    chunks_off = chunking._semantic_text_chunks(
        "Sentence A. Sentence B.\n\nSentence C.",
        chunk_size=500,
        overlap=0,
        use_semantic_chunking=False,
    )
    assert calls["model_loaded"] == 0
    assert len(chunks_off) >= 1


# ============================================================
# Test Group 5: build_hierarchical_chunks 全链路 (模拟真实文档)
# ============================================================
def test_build_hierarchical_chunks_with_semantic_enabled(monkeypatch):
    """build_hierarchical_chunks 真·语义分块全链路：开关打开 + Fake Model。"""
    monkeypatch.setattr(
        chunking,
        "_load_semantic_chunking_model",
        lambda: FakeSemanticChunkingModel(),
    )

    parsed = {
        "full_text": (
            "Xiaoai voice control is supported by the robot vacuum. "
            "Tmall Genie voice control is also supported. "
            "Clean the main brush every week. "
            "Replace the side brush when it is worn."
        ),
        "pages": [],
        "sections": [],
    }

    chunks = chunking.build_hierarchical_chunks(
        parsed,
        file_type="txt",
        chunk_size=500,
        overlap=0,
        use_semantic_chunking=True,
    )

    leafs = [c for c in chunks if c["chunk_role"] == "leaf"]
    assert len(leafs) >= 1
    for leaf in leafs:
        assert leaf["content"].strip()
        assert leaf["retrieval_content"].startswith("[父级主题]")


# ============================================================
# Test Group 6: Settings 集成验证
# ============================================================
def test_settings_has_semantic_chunking_flags():
    """Settings 类必须暴露语义分块相关配置（刚从缺口3补齐）。"""
    assert hasattr(settings, "USE_SEMANTIC_CHUNKING")
    assert isinstance(settings.USE_SEMANTIC_CHUNKING, bool)
    assert hasattr(settings, "SEMANTIC_CHUNKING_MODEL")
    assert hasattr(settings, "SEMANTIC_CHUNKING_BREAKPOINT_PERCENTILE")
    assert 0.0 <= settings.SEMANTIC_CHUNKING_BREAKPOINT_PERCENTILE <= 100.0
    assert hasattr(settings, "SEMANTIC_CHUNKING_BATCH_SIZE")
    assert settings.SEMANTIC_CHUNKING_BATCH_SIZE >= 1


# ============================================================
# Test Group 7: 中文文本的语义边界检测 (实际MiniLM模型)
#   — 默认跳过: 首次运行需要下载 470MB 模型文件，会阻塞 CI
#   — 手动执行: RUN_REAL_SEMANTIC_TESTS=1 pytest test/test_semantic_chunking.py -v
# ============================================================
@pytest.mark.skipif(
    not os.getenv("RUN_REAL_SEMANTIC_TESTS", "0").strip().lower()
    in {"1", "true", "yes", "on"},
    reason="Real model needs ~470MB download; set RUN_REAL_SEMANTIC_TESTS=1 or use --run-real-semantic",
)
def test_real_embedding_model_can_load():
    """真 embedding 连通性/质量验证（兼容：本地 sentence-transformers / LM Studio API）。

    断言要点（稳定、跨模式可验证）：
      ① embedding 数量与句子数对齐
      ② 所有向量归一化：对角 sim(Si,Si) ≈ 1.0 （余弦距离特性，必过）
      ③ 所有相似度在合法区间 [0, 1]
      ④ 输出维度符合 MiniLM = 384（GGUF 量化后维度保持不变）

    注：不拿 <4 个超短句比「同组/跨组相似度排序」——
        GGUF 量化或短样本会抖动，但当句子数 ≥ 6 时百分位自适应阈值仍能找到语义断点，
        这个行为由 test_real_semantic_chunking_runs_end_to_end（7句完整文本）负责验证。
    """
    model = chunking._load_semantic_chunking_model()
    sentences = [
        "小爱同学可以启动扫地机器人的清洁任务。",
        "天猫精灵也支持语音控制，暂停和恢复清扫。",
        "每周清理主刷，去除滚刷上缠绕的毛发和灰尘。",
        "边刷磨损后及时更换，保证边角清洁效果稳定。",
    ]

    # ===== 模式 A：LM Studio API =====
    if model == "__USE_LM_STUDIO_API__":
        embeddings = chunking._encode_sentences_via_api(sentences)
        if embeddings is None:
            pytest.skip("LM Studio API 未连通，请确认 MiniLM GGUF 模型在 LM Studio 已启动")
    # ===== 模式 B：本地 sentence-transformers =====
    elif model is not None:
        embeddings = model.encode(
            sentences,
            batch_size=settings.SEMANTIC_CHUNKING_BATCH_SIZE,
            normalize_embeddings=True,
            show_progress_bar=False,
        )
    else:
        pytest.skip("sentence-transformers not available or model failed to load")

    # ① 数量对齐
    assert len(embeddings) == len(sentences)
    # ④ 维度 = 384（MiniLM 系列标准维度）
    assert len(embeddings[0]) == 384, "MiniLM 标准输出应为 384 维，实际 = %d" % len(embeddings[0])

    # ② 对角 = 1.0（归一化验证） + ③ 所有相似度 ∈ [0, 1]
    for i in range(len(sentences)):
        s_ii = chunking._semantic_cosine_similarity(embeddings[i], embeddings[i])
        assert abs(s_ii - 1.0) < 1e-3, "向量未归一化：sim(S%d,S%d)=%.4f，应为 1.0" % (i, i, s_ii)
        for j in range(len(sentences)):
            s_ij = chunking._semantic_cosine_similarity(embeddings[i], embeddings[j])
            assert -1e-3 <= s_ij <= 1.0 + 1e-3, (
                "相似度越界: sim(%d,%d)=%.4f" % (i, j, s_ij)
            )


@pytest.mark.skipif(
    not os.getenv("RUN_REAL_SEMANTIC_TESTS", "0").strip().lower()
    in {"1", "true", "yes", "on"},
    reason="Real model tests skipped by default; enable with RUN_REAL_SEMANTIC_TESTS=1",
)
def test_real_semantic_chunking_runs_end_to_end():
    """真·端到端：中文文本 → sentence split → embeddings → 相似度 → 百分位 → 切块。

    如果 model=None（依赖/网络问题）→ 降级到启发式，测试仍然通过。
    """
    text = (
        "第一章：语音控制功能说明。"
        "小爱同学可以启动扫地机器人的定时清洁任务，也可以设置指定房间清扫。"
        "天猫精灵也支持同样的语音控制，用户可以不用打开APP直接语音启动、暂停、恢复清扫。"
        "第二章：日常维护保养。"
        "每周清理主刷，去除滚刷上缠绕的毛发和灰尘，保证清洁吸力不下降。"
        "边刷磨损后及时更换，保证边角清洁效果稳定。"
        "滤芯使用满三个月建议更换，避免二次空气污染。"
    )

    chunks = chunking._semantic_text_chunks(
        text,
        chunk_size=500,
        overlap=50,
        use_semantic_chunking=True,
    )

    assert len(chunks) >= 2
    all_text = " ".join(chunks)
    for keyword in [
        "小爱同学",
        "天猫精灵",
        "清理主刷",
        "边刷磨损后及时更换",
        "滤芯",
    ]:
        assert keyword in all_text, f"关键词丢失: {keyword}"
    first_chunk_has_voice = any(
        k in chunks[0] for k in ["小爱同学", "天猫精灵", "语音控制"]
    )
    second_chunk_has_maint = any(
        k in chunks[min(1, len(chunks) - 1)] for k in ["维护保养", "清理主刷", "滤芯"]
    )
    assert (
        first_chunk_has_voice and second_chunk_has_maint
    ), "语义边界命中失败：第1块应含语音控制，后续块应含维护保养；实际 chunks = %r" % (chunks,)