# 缺口7：RAG 评测体系 —— 详细实施方案

> 对应文档：《检索与入库技术深化学习规划.md》缺口7
> 预计工作量：轻量版 1~2 天，Ragas 集成版 3 天
> 优先级：【第一周第1步】所有缺口之前先做这个——先有尺子，再谈改进

---

## 一、为什么要先做评测？（没有量化 = 没有改进）

现在 RAG 开发的痛点：

```
改了分块策略："感觉答案好像更准了？" —— 不确定
加了 CrossEncoder rerank："好像排序比之前好？" —— 没数字
升级 HNSW 索引："查得更快了，但精度会不会掉？" —— 心里没底
老板问："咱们这个 RAG 准确率多少？" → 回答："呃...感觉差不多80分？"
```

**评测体系就是一把尺子**，任何改动都要拿这把尺量一下：
- Recall@5 升了还是降了？（检索层）
- MRR 分数变化了多少？（排序层）
- Ragas 4 维度有没有提升？（端到端生成层）

---

## 二、评测体系金字塔（从易到难）

```
Level 3 ────────────────────────────────────────
         Ragas 端到端评测（Answer Relevance/Faithfulness...）
         需要：LLM 调用，费用高
         每次发版前跑一次
Level 2 ────────────────────────────────────────
         生成层打分：问题 + 答案 + 参考答案 → 0~5 分
         需要：人工标注 20~30 套 "标准答案"
         每次改动 rerank/prompt 后跑一次
Level 1 ────────────────────────────────────────
         检索层打分：Recall@5 / Recall@10 / MRR
         需要：人工标注 20~30 道 "问题 ↔ 期望命中的chunk_ids"
         每次改分块/索引/过滤后跑一次
Level 0 ────────────────────────────────────────
         20~30 条标准问题评测集（手工编/用户真实问题）
         30 分钟搞定，后面所有评测的基础
─────────────────────────────────────────────────
```

**先从 Level 0 + Level 1 开始**，1 天能搞定，立刻能用。Level 2 和 Level 3 等 Level 1 稳定后再补。

---

## 三、分步实施方案

### 步骤 1：构建最小评测集（Level 0，0.5 天）

#### 1.1 新建目录结构

```
evaluations/
├── README.md                 # 评测说明
├── datasets/
│   └── testset_v1.yaml       # 【核心】标准问题 + 期望命中
├── baseline/
│   └── baseline_v1.json      # 第一次跑出来的基线分数（后续对比用）
└── results/                  # 每次跑评测的结果（自动生成，按时间戳命名）
```

#### 1.2 编写 testset_v1.yaml（20~30 条起步）

**原则**：不要自己瞎编，问题要尽量贴近真实用户会问的。最好从测试账号真实的历史对话里挑 20 条。

```yaml
# evaluations/datasets/testset_v1.yaml
version: v1
description: "RAG 检索层最小评测集（20题）—— 涵盖 产品手册 / 公司制度 / 项目报告 3 类"
embedding_model: "text-embedding-3-large"
created_at: "2026-08-12"

questions:
  # ========== 产品手册类 ==========
  - id: q001
    category: product_manual
    type: factual          # 事实类：直接对应原文某句话
    question: "华为Mate60 Pro 的屏幕尺寸是多少？"
    # 【核心】期望在检索 Top-K 里命中的 chunk_id 列表（至少写一个，写多个更好）
    # 怎么获取？先手动在问答界面问一遍，点"引用来源"查看哪个 chunk 真的包含答案，记下它的 ID
    expected_chunk_ids: [1042, 1043]
    expected_keywords: ["6.82寸", "屏幕尺寸", "Mate60 Pro"]

  - id: q002
    category: product_manual
    type: comparison       # 对比类：需要跨 chunk 找信息
    question: "Mate60 和 Mate60 Pro 在价格上差多少？"
    expected_chunk_ids: [1042, 1045]   # 两款手机各在一个 chunk
    expected_keywords: ["5499", "6499", "差1000"]

  # ========== 公司制度类 ==========
  - id: q005
    category: regulation
    type: procedural       # 流程类
    question: "员工请病假需要提前多久申请？需要提供什么材料？"
    expected_chunk_ids: [2108]
    expected_keywords: ["病假", "提前24小时", "医院证明"]

  # ========== 项目报告类 ==========
  - id: q010
    category: report
    type: summarization    # 总结类
    question: "Q2 季度华东区域营收同比增长多少？主要原因是什么？"
    expected_chunk_ids: [3450, 3455]
    expected_keywords: ["华东", "同比增长18%", "新客户拓展"]

  # ... 继续补到至少 20 条 ...
```

**编写小技巧**：
- 4 种问题类型平均分布：factual（事实）40% / procedural（流程）25% / comparison（对比）20% / summarization（总结）15%
- 至少覆盖所有真实用户常用的 3~5 个文档分类
- `expected_chunk_ids` 不用写全所有可能的，写 1~2 个最核心的就够，Recall 计算会自动算「这 1~2 个有没有出现在 Top10 里」

---

### 步骤 2：写检索层评测脚本（Level 1，1 天）

新建 `scripts/evaluate_rag_retrieval.py`：

```python
"""
RAG 检索层评测脚本（Level 1）
跑 testset_v1.yaml 里的所有问题，输出 3 个核心指标：
    1. Recall@5   : 期望chunk出现在Top5的比例（越高越好）
    2. Recall@10  : 期望chunk出现在Top10的比例（越高越好）
    3. MRR@10     : 第一个命中的期望chunk的排名倒数平均值（排序质量）

用法：
    # 跑当前代码的检索质量
    python scripts/evaluate_rag_retrieval.py

    # 跑指定用户的账号（用该用户的知识库做评测）
    python scripts/evaluate_rag_retrieval.py --user-id 42

    # 和上次的 baseline 对比（自动算百分比提升）
    python scripts/evaluate_rag_retrieval.py --compare baseline/baseline_v1.json
"""

from __future__ import annotations
import argparse
import json
import time
import sys
from pathlib import Path
from datetime import datetime

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import yaml
from sqlalchemy.orm import Session

from core.config import settings
from core.db.session import SessionLocal
from core.service import retrieval
from core.service.retrieval import SearchResultChunk


EVAL_ROOT = Path(__file__).resolve().parent.parent / "evaluations"


def load_testset(path: Path):
    with open(path, "r", encoding="utf-8") as f:
        return yaml.safe_load(f)


def calc_recall_at_k(expected_ids: list[int], result_chunks: list[SearchResultChunk], k: int) -> float:
    """
    计算单个问题的 Recall@K
    Recall = （命中的期望chunk数） / （总期望chunk数）

    例子：
        expected=[1042, 1043], Top10 里出现了 1042 但没出现 1043
        → Recall = 1/2 = 0.5
    """
    if not expected_ids:
        return 1.0  # 没写期望的问题算通过（不拖累总分）

    top_k_ids = {c.chunk_id for c in result_chunks[:k]}
    hit = sum(1 for eid in expected_ids if eid in top_k_ids)
    return hit / len(expected_ids)


def calc_mrr_at_k(expected_ids: list[int], result_chunks: list[SearchResultChunk], k: int) -> float:
    """
    计算单个问题的 MRR@K（平均倒数排名）
    衡量"排序质量"——不但要命中，还要排得靠前。

    例子：
        expected=[1042]，1042 排在第 3 名
        → MRR = 1/3 ≈ 0.333
        （如果排第 1 就是 1.0，排第 10 就是 0.1，没命中就是 0）
    """
    if not expected_ids:
        return 1.0

    expected_set = set(expected_ids)
    for rank, chunk in enumerate(result_chunks[:k], start=1):
        if chunk.chunk_id in expected_set:
            return 1.0 / rank  # 找到第一个命中的就返回
    return 0.0


def run_evaluation(user_id: int, testset: dict) -> dict:
    """
    跑完整评测，返回结果字典（可序列化存 JSON）
    """
    db: Session = SessionLocal()
    questions = testset.get("questions", [])
    per_question = []
    total_r5 = 0.0
    total_r10 = 0.0
    total_mrr = 0.0
    valid_count = 0

    try:
        for q in questions:
            qid = q["id"]
            q_text = q["question"]
            expected_ids = q.get("expected_chunk_ids", [])
            category = q.get("category", "unknown")

            # 调用 hybrid_search（和生产路径一模一样，保证评测结果可信）
            t0 = time.perf_counter()
            try:
                results = retrieval.hybrid_search(
                    db,
                    user_id,
                    q_text,
                    top_k=20,   # 多取几条，方便算 Recall@10 / MRR@10
                )
                latency_ms = (time.perf_counter() - t0) * 1000

                r5 = calc_recall_at_k(expected_ids, results, 5)
                r10 = calc_recall_at_k(expected_ids, results, 10)
                mrr = calc_mrr_at_k(expected_ids, results, 10)
                top1_id = results[0].chunk_id if results else None
                top1_score = float(results[0].score) if results else 0.0

            except Exception as e:
                # 某个问题挂了不影响整体评测，记录异常并继续
                latency_ms = 0.0
                r5 = r10 = mrr = 0.0
                top1_id = None
                top1_score = 0.0
                q["_error"] = str(e)

            total_r5 += r5
            total_r10 += r10
            total_mrr += mrr
            valid_count += 1

            per_question.append({
                "id": qid,
                "category": category,
                "question": q_text,
                "expected_chunk_ids": expected_ids,
                "latency_ms": round(latency_ms, 1),
                "recall@5": round(r5, 4),
                "recall@10": round(r10, 4),
                "mrr@10": round(mrr, 4),
                "top1_chunk_id": top1_id,
                "top1_score": round(top1_score, 4),
                "hit": bool(r10 > 0),  # Top10 至少命中一个就算过
                "error": q.get("_error"),
            })

    finally:
        db.close()

    # 汇总平均
    avg = {
        "recall@5": round(total_r5 / valid_count, 4) if valid_count else 0,
        "recall@10": round(total_r10 / valid_count, 4) if valid_count else 0,
        "mrr@10": round(total_mrr / valid_count, 4) if valid_count else 0,
        "hit_rate@10": round(sum(1 for p in per_question if p["hit"]) / valid_count, 4) if valid_count else 0,
        "avg_latency_ms": round(sum(p["latency_ms"] for p in per_question) / valid_count, 1) if valid_count else 0,
    }

    # 分 category 单独统计（方便看"产品类分数高但制度类分数低"这种现象）
    by_category = {}
    for q in per_question:
        cat = q["category"]
        if cat not in by_category:
            by_category[cat] = {"count": 0, "r5": 0, "r10": 0, "mrr": 0}
        by_category[cat]["count"] += 1
        by_category[cat]["r5"] += q["recall@5"]
        by_category[cat]["r10"] += q["recall@10"]
        by_category[cat]["mrr"] += q["mrr@10"]
    for cat, stats in by_category.items():
        n = stats["count"]
        by_category[cat] = {
            "count": n,
            "avg_recall@5": round(stats["r5"] / n, 4),
            "avg_recall@10": round(stats["r10"] / n, 4),
            "avg_mrr@10": round(stats["mrr"] / n, 4),
        }

    return {
        "eval_time": datetime.now().isoformat(timespec="seconds"),
        "questions_count": valid_count,
        "avg": avg,
        "by_category": by_category,
        "per_question": per_question,
    }


def compare_with_baseline(result: dict, baseline_path: Path):
    """和上次的 baseline 做对比，输出每个指标的增减百分比"""
    baseline = json.loads(baseline_path.read_text(encoding="utf-8"))
    b_avg = baseline.get("avg", {})
    r_avg = result.get("avg", {})

    print("\n📊 === 与基线版本分数对比 ===")
    print(f"{'指标':<15}{'基线':>10}{'当前':>10}{'变化':>12}")
    print("-" * 48)
    for metric in ["recall@5", "recall@10", "mrr@10", "hit_rate@10", "avg_latency_ms"]:
        b = b_avg.get(metric, 0)
        r = r_avg.get(metric, 0)
        if metric == "avg_latency_ms":
            # 延迟：降了是好事
            diff_pct = (r - b) / b * 100 if b else 0
            arrow = "↓" if diff_pct < -0.1 else "↑" if diff_pct > 0.1 else "→"
            print(f"{metric:<15}{b:>10.2f}{r:>10.2f}  {arrow} {diff_pct:+6.1f}%")
        else:
            # 精度：升了是好事
            diff_pct = (r - b) / b * 100 if b else 0
            arrow = "↑" if diff_pct > 0.1 else "↓" if diff_pct < -0.1 else "→"
            print(f"{metric:<15}{b:>10.2%}{r:>10.2%}  {arrow} {diff_pct:+6.1f}%")

    # 列出 Top3 进步最大 和 Top3 退步最大的问题
    b_per_q = {x["id"]: x for x in baseline.get("per_question", [])}
    improved = []
    regressed = []
    for rpq in result.get("per_question", []):
        bpq = b_per_q.get(rpq["id"])
        if not bpq:
            continue
        delta = rpq["recall@10"] - bpq["recall@10"]
        if delta > 0:
            improved.append((delta, rpq["id"], rpq["question"]))
        elif delta < 0:
            regressed.append((delta, rpq["id"], rpq["question"]))

    if improved:
        print("\n🎉 进步最大的问题（按召回提升排序）:")
        for delta, qid, qtext in sorted(improved, reverse=True)[:3]:
            print(f"  #{qid} +{delta:+.0%} {qtext}")

    if regressed:
        print("\n⚠️ 退步最大的问题（需要重点检查）:")
        for delta, qid, qtext in sorted(regressed)[:3]:
            print(f"  #{qid} {delta:+.0%} {qtext}")


def main():
    parser = argparse.ArgumentParser(description="RAG 检索层评测脚本（Recall / MRR）")
    parser.add_argument("--user-id", type=int, default=42, help="评测用的用户ID（默认 42）")
    parser.add_argument("--dataset", type=str, default=str(EVAL_ROOT / "datasets" / "testset_v1.yaml"))
    parser.add_argument("--compare", type=str, default=None, help="对比指定的 baseline JSON")
    parser.add_argument("--save-baseline", type=str, default=None, help="把本次评测结果存为新的 baseline JSON")
    args = parser.parse_args()

    testset_path = Path(args.dataset)
    if not testset_path.exists():
        print(f"❌ 评测集不存在: {testset_path}")
        print("   请先在 evaluations/datasets/testset_v1.yaml 编写标准问题集")
        sys.exit(1)

    testset = load_testset(testset_path)
    print(f"📝 加载评测集: {testset_path.name} （共 {len(testset.get('questions', []))} 题）")

    result = run_evaluation(args.user_id, testset)

    # ========== 打印 Markdown 表格 ==========
    avg = result["avg"]
    print()
    print("═" * 60)
    print("【RAG 检索层评测结果汇总】")
    print("═" * 60)
    print(f"  Recall@5    : {avg['recall@5']:.2%}   ← Top5 命中")
    print(f"  Recall@10   : {avg['recall@10']:.2%}   ← Top10 命中")
    print(f"  MRR@10      : {avg['mrr@10']:.4f}   ← 排序质量")
    print(f"  Hit Rate@10 : {avg['hit_rate@10']:.2%}   ← Top10至少命中一个")
    print(f"  平均延迟      : {avg['avg_latency_ms']:.1f} ms")
    print()

    # 分分类
    print("【按文档分类拆解】:")
    for cat, stats in result["by_category"].items():
        print(f"  {cat:<15} N={stats['count']:<3} Recall@10={stats['avg_recall@10']:.2%} MRR={stats['avg_mrr@10']:.4f}")
    print()

    # 列出所有命中失败的问题（方便人工看）
    failed = [p for p in result["per_question"] if not p["hit"]]
    if failed:
        print(f"❌ Top10 完全没命中的问题（{len(failed)} 个，需要人工检查）:")
        for p in failed:
            print(f"  #{p['id']} [{p['category']}] {p['question']}")
            print(f"     期望 chunk_id: {p['expected_chunk_ids']}")
            if p["error"]:
                print(f"     错误: {p['error']}")
        print()

    # 保存结果
    results_dir = EVAL_ROOT / "results"
    results_dir.mkdir(exist_ok=True, parents=True)
    save_path = results_dir / f"retrieval_{datetime.now().strftime('%Y%m%d_%H%M%S')}.json"
    save_path.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"💾 完整结果已保存到: {save_path}")

    # 存为新的 baseline
    if args.save_baseline:
        baseline_path = Path(args.save_baseline)
        baseline_path.parent.mkdir(parents=True, exist_ok=True)
        baseline_path.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
        print(f"🎯 已作为新基线保存到: {baseline_path}")

    # 和旧 baseline 对比
    if args.compare:
        compare_with_baseline(result, Path(args.compare))


if __name__ == "__main__":
    main()
```

---

### 步骤 3：跑第一次，建立 baseline_v1.json（0.5 天）

1. 部署最新代码，选一个有 20+ 文档的测试用户账号（user_id=42）
2. 花 30 分钟写 testset_v1.yaml 的 20 条问题和 expected_chunk_ids
3. 执行：

```bash
python scripts/evaluate_rag_retrieval.py \
    --user-id 42 \
    --save-baseline evaluations/baseline/baseline_v1.json
```

第一次的结果大概长这样（参考值，不是你的真实数据）：

```
【RAG 检索层评测结果汇总】
  Recall@5    : 78.57%
  Recall@10   : 85.71%
  MRR@10      : 0.6123
  Hit Rate@10 : 92.86%
  平均延迟      : 85.2 ms
```

这就是你的「基线分数」。后面改分块、加 rerank、升 ANN，跑完都和这组数字对比。

---

### 步骤 4（可选进阶）：Ragas 端到端评测（Level 2/3，2 天）

Level 1 只测「检索准不准」，但「生成的回答有没有胡说」测不到。Ragas 框架能端到端打分：

| 指标 | 含义 | 目标值 |
|-----|------|--------|
| Answer Relevance | 回答是否切题（问价格不要答尺寸） | > 0.8 |
| Faithfulness | 回答内容是否全部来自检索上下文（不瞎编） | > 0.85 |
| Context Precision | 检索上下文排序，相关的是否排前面 | > 0.75 |
| Context Recall | 回答需要的信息是否都被检索到了 | > 0.8 |

集成代码（Level 1 跑稳后再加）：

```python
# pip install ragas
from ragas import evaluate
from ragas.metrics import (
    answer_relevancy,
    faithfulness,
    context_precision,
    context_recall,
)
from datasets import Dataset

# 把 testset_v1 转成 Ragas 需要的格式
ragas_dataset = Dataset.from_list([
    {
        "question": q["question"],
        "ground_truth": q.get("ground_truth_answer", ""),  # 需要额外人工写参考答案
        "answer": actual_answer_from_rag(q["question"]),
        "contexts": [c.content for c in actual_chunks(q["question"])],
    }
    for q in questions
])

result = evaluate(
    ragas_dataset,
    metrics=[answer_relevancy, faithfulness, context_precision, context_recall],
)
print(result.to_pandas())
```

**注意**：Ragas 每道题要调 1~2 次 LLM，20 道题大约花费 $0.1~0.3，不适合每次提交代码都跑，建议作为「每次发版」的质量门禁就够了。

---

## 四、集成到开发流程（规范）

```
每次改 RAG 相关代码（分块/检索/索引/rerank/prompt）
    │
    ▼
本地跑 evaluate_rag_retrieval.py
    │
    ├─ 3 个核心指标全部 >= baseline（或在 ±1% 浮动范围）
    │   → ✅ 提交代码，附评测结果截图
    │
    └─ 某个指标下降超过 1%
        ├─ 人工 review 「退步最大的 Top3 问题」
        ├─ 确认是 trade-off（比如召回降1%但延迟降50%）→ 批准通过
        └─ 确认是 bug → 修完重新跑
```

---

## 五、关键注意点

1. **评测集要跟着真实问题迭代**：每个月从线上用户的提问里挑 5 条「答得不好」的新问题加进 testset，半年后评测集就从 20 条涨到 50 条，越来越接近真实分布。
2. **不要为了评测分数 hack**：比如把 expected_chunk_ids 写进代码里特殊处理。评测集必须和检索流程完全解耦，评测脚本只调用公开的 `hybrid_search()` 接口。
3. **Latency 指标也要盯**：有时候 Recall 升了 2% 但延迟翻倍了，这在产品上反而是降级。任何改动必须同时看「精度 + 速度」两个维度。
4. **先从 Level 1 做起，不要一上来就 Ragas**：Ragas 要钱要标注，Level 1 不花钱不依赖 LLM，每次代码提交都能跑，ROI 最高。