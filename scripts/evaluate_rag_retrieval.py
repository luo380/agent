"""
RAG 检索层评测脚本（Level 1）
═══════════════════════════════════════════════════════════════════
指标：Recall@5 / Recall@10 / MRR@10 / Hit Rate@10 / Avg Latency
用法见 evaluations/README.md
"""
from __future__ import annotations

import argparse
import asyncio
import json
import sys
import time
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

try:
    import yaml
except ImportError:
    print("缺少 PyYAML: pip install pyyaml"); sys.exit(1)

PROJECT_ROOT = Path(__file__).resolve().parent.parent
EVAL_ROOT = PROJECT_ROOT / "evaluations"


def calc_recall_at_k(expected_ids, actual_ids, k):
    if not expected_ids:
        return None
    top_k = set(actual_ids[:k])
    hit = sum(1 for e in expected_ids if e in top_k)
    return hit / len(expected_ids)


def calc_mrr_at_k(expected_ids, actual_ids, k):
    if not expected_ids:
        return None
    es = set(expected_ids)
    for rank, cid in enumerate(actual_ids[:k], start=1):
        if cid in es:
            return 1.0 / rank
    return 0.0


async def run_evaluation(user_id, testset, search_top_k=30):
    from core.db.session import SessionLocal
    from core.service import embedding, retrieval

    questions = testset.get("questions", [])
    per_question = []
    sum_r5 = sum_r10 = sum_mrr = 0.0
    valid_count_r = valid_count_mrr = hit_count_10 = 0
    total_lat_ms = 0.0

    db = SessionLocal()
    try:
        for qi, q in enumerate(questions, start=1):
            qid = q["id"]
            q_text = q["question"]
            expected_ids = list(q.get("expected_chunk_ids") or [])
            category = q.get("category", "unknown")
            print(f"  [{qi}/{len(questions)}] #{qid} [{category}] {q_text[:40]}...",
                  end=" ", flush=True)
            err_str = None
            t0 = time.perf_counter()
            chunks = []
            try:
                query_emb = await embedding.embed_text(q_text)
                if not query_emb:
                    raise RuntimeError("Embedding 空向量")
                chunks = retrieval.hybrid_search(
                    db, user_id=user_id,
                    query_text=q_text, query_embedding=query_emb,
                    document_ids=None, top_k=search_top_k,
                )
            except Exception as e:
                err_str = f"{type(e).__name__}: {e}"
                chunks = []
            lat_ms = (time.perf_counter() - t0) * 1000
            total_lat_ms += lat_ms

            actual_ids = [c.chunk_id for c in chunks]
            top1 = chunks[0] if chunks else None
            top1_score = float(top1.final_score) if top1 else 0.0

            r5 = calc_recall_at_k(expected_ids, actual_ids, 5)
            r10 = calc_recall_at_k(expected_ids, actual_ids, 10)
            mrr = calc_mrr_at_k(expected_ids, actual_ids, 10)

            if r5 is not None:
                sum_r5 += r5; sum_r10 += r10; valid_count_r += 1
            if mrr is not None:
                sum_mrr += mrr; valid_count_mrr += 1
                if expected_ids and r10 > 0:
                    hit_count_10 += 1
                elif not expected_ids and len(actual_ids[:10]) == 0:
                    hit_count_10 += 1
            else:
                if len(actual_ids[:10]) == 0:
                    hit_count_10 += 1

            if expected_ids:
                hit_flag = r10 > 0 if r10 is not None else None
            else:
                hit_flag = len(actual_ids[:10]) == 0

            if err_str:
                print(f"ERROR {err_str[:60]}")
            elif expected_ids:
                s = "OK" if hit_flag else "MISS"
                print(f"{s} r5={r5:.0%} r10={r10:.0%} mrr={mrr:.3f} top1={top1.chunk_id if top1 else '-'} ({lat_ms:.1f}ms)")
            else:
                s = "OK(拒答)" if hit_flag else "误命中"
                print(f"{s} top10有 {len(actual_ids[:10])} 个 ({lat_ms:.1f}ms)")

            per_question.append({
                "id": qid, "category": category, "question": q_text,
                "expected_chunk_ids": expected_ids,
                "latency_ms": round(lat_ms, 1),
                "recall@5": round(r5, 4) if r5 is not None else None,
                "recall@10": round(r10, 4) if r10 is not None else None,
                "mrr@10": round(mrr, 4) if mrr is not None else None,
                "top1_chunk_id": top1.chunk_id if top1 else None,
                "top1_document_id": top1.document_id if top1 else None,
                "top1_score": round(top1_score, 4),
                "hit": bool(hit_flag), "error": err_str,
                "actual_top10_chunk_ids": actual_ids[:10],
            })
    finally:
        db.close()

    total = len(questions)
    avg = {
        "questions_total": total,
        "questions_for_retrieval_metrics": valid_count_r,
        "recall@5": round(sum_r5 / valid_count_r, 4) if valid_count_r else 0,
        "recall@10": round(sum_r10 / valid_count_r, 4) if valid_count_r else 0,
        "mrr@10": round(sum_mrr / valid_count_mrr, 4) if valid_count_mrr else 0,
        "hit_rate@10": round(hit_count_10 / total, 4) if total else 0,
        "avg_latency_ms": round(total_lat_ms / total, 1) if total else 0,
    }
    by_cat = {}
    for p in per_question:
        c = p["category"]
        d = by_cat.setdefault(c, {"count": 0, "r5s": 0, "r10s": 0, "mrr_s": 0, "hit": 0, "lat": 0.0, "v": 0})
        d["count"] += 1
        if p["recall@5"] is not None:
            d["r5s"] += p["recall@5"]; d["r10s"] += p["recall@10"]
            d["mrr_s"] += p["mrr@10"]; d["v"] += 1
        if p["hit"]: d["hit"] += 1
        d["lat"] += p["latency_ms"]
    for c, d in by_cat.items():
        n = d["v"] or 1; t = d["count"] or 1
        by_cat[c] = {
            "count": d["count"],
            "avg_recall@5": round(d["r5s"] / n, 4),
            "avg_recall@10": round(d["r10s"] / n, 4),
            "avg_mrr@10": round(d["mrr_s"] / n, 4),
            "hit_rate@10": round(d["hit"] / t, 4),
            "avg_latency_ms": round(d["lat"] / t, 1),
        }
    return {
        "eval_time": datetime.now().isoformat(timespec="seconds"),
        "user_id": user_id, "search_top_k": search_top_k,
        "avg": avg, "by_category": by_cat, "per_question": per_question,
    }


def print_summary(result):
    avg = result["avg"]
    print()
    print("═" * 68)
    print(" 【RAG 检索层评测结果汇总】")
    print(f"   用户ID={result['user_id']}  题目总数={avg['questions_total']}")
    print(f"   检索类问题={avg['questions_for_retrieval_metrics']}（其余拒答类）")
    print("═" * 68)
    print(f"   Recall@5       : {avg['recall@5']:>7.2%}")
    print(f"   Recall@10      : {avg['recall@10']:>7.2%}")
    print(f"   MRR@10         : {avg['mrr@10']:>7.4f}")
    print(f"   Hit Rate@10    : {avg['hit_rate@10']:>7.2%}")
    print(f"   平均检索延迟    : {avg['avg_latency_ms']:>7.1f} ms")
    print()
    cats = result["by_category"]
    if cats:
        print("【按问题分类拆解】:")
        print(f"   {'分类':<16}{'N':>4}  {'Rec@10':>7}  {'MRR@10':>7}  {'Hit':>7}  {'ms':>8}")
        for cat, s in cats.items():
            print(f"   {cat:<16}{s['count']:>4}  {s['avg_recall@10']:>6.2%}  {s['avg_mrr@10']:>7.4f}  {s['hit_rate@10']:>6.2%}  {s['avg_latency_ms']:>8.1f}")
        print()
    failed = [p for p in result["per_question"] if not p["hit"]]
    if failed:
        print(f"❌ 判定失败的问题（共 {len(failed)} 道）:")
        for p in failed:
            f = "ERR" if p["error"] else "MISS"
            print(f"   #{p['id']:<5} [{p['category']:<10}] {f} {p['question'][:55]}")
            if p["expected_chunk_ids"]:
                print(f"           期望chunk: {p['expected_chunk_ids']}")
                print(f"           实际top10: {p['actual_top10_chunk_ids']}")
            if p["error"]:
                print(f"           错误: {p['error']}")
        print()


def compare_with_baseline(result, baseline_path):
    b = json.loads(baseline_path.read_text(encoding="utf-8")).get("avg", {})
    r = result.get("avg", {})
    print()
    print("📊" + "=" * 60)
    print(f" 【与基线对比：{baseline_path.name} → 当前】")
    print("═" * 68)
    print(f"  {'指标':<18}  {'基线':>10}  {'当前':>10}  {'变化':>12}")
    print("  " + "-" * 64)
    for metric in ["recall@5", "recall@10", "mrr@10", "hit_rate@10", "avg_latency_ms"]:
        bv = b.get(metric, 0) or 0
        rv = r.get(metric, 0) or 0
        dp = (rv - bv) / bv * 100 if bv else 0.0
        if metric == "avg_latency_ms":
            arrow = "↓" if dp < -0.1 else "↑" if dp > 0.1 else "→"
            print(f"  {metric:<18} {bv:>10.2f} {rv:>10.2f}  {arrow} {dp:+7.1f}%")
        else:
            arrow = "↑" if dp > 0.1 else "↓" if dp < -0.1 else "→"
            print(f"  {metric:<18} {bv:>9.2%} {rv:>9.2%}  {arrow} {dp:+7.1f}%")

    b_per_q = {x["id"]: x for x in json.loads(baseline_path.read_text(encoding="utf-8")).get("per_question", [])}
    improved, regressed = [], []
    for p in result["per_question"]:
        bp = b_per_q.get(p["id"])
        if not bp or p["recall@10"] is None:
            continue
        d = p["recall@10"] - (bp.get("recall@10") or 0)
        if d > 0:
            improved.append((d, p["id"], p["question"]))
        elif d < 0:
            regressed.append((d, p["id"], p["question"]))
    if improved:
        print("\n🎉 进步最大 Top3:")
        for d, qid, q in sorted(improved, reverse=True)[:3]:
            print(f"   #{qid:<5} {d:+.0%} → {q[:55]}")
    if regressed:
        print("\n⚠️  退步最大 Top3（重点检查）:")
        for d, qid, q in sorted(regressed)[:3]:
            print(f"   #{qid:<5} {d:+.0%} → {q[:55]}")
    print()


def main():
    ap = argparse.ArgumentParser(description="RAG 检索层评测脚本")
    ap.add_argument("--user-id", type=int, default=None)
    ap.add_argument("--dataset", type=str, default=str(EVAL_ROOT / "datasets" / "testset_v1.yaml"))
    ap.add_argument("--search-top-k", type=int, default=30)
    ap.add_argument("--compare", type=str, default=None)
    ap.add_argument("--save-baseline", type=str, default=None)
    args = ap.parse_args()

    tp = Path(args.dataset)
    if not tp.exists():
        print(f"❌ 评测集不存在: {tp}，请先写 evaluations/datasets/testset_v1.yaml"); sys.exit(1)
    testset = yaml.safe_load(tp.read_text(encoding="utf-8")) or {}
    if not testset.get("questions"):
        print(f"❌ {tp.name} 里 questions 为空，请至少写 20 道真实题"); sys.exit(1)

    user_id = args.user_id or testset.get("default_user_id")
    if not user_id:
        print("❌ 必须指定 --user-id 或在 yaml 里填 default_user_id"); sys.exit(1)
    print(f"📝 评测集 {tp.name}（{len(testset['questions'])}题, uid={user_id}, top_k={args.search_top_k}）\n")

    try:
        result = asyncio.run(run_evaluation(user_id=user_id, testset=testset, search_top_k=args.search_top_k))
    except KeyboardInterrupt:
        print("\n中断"); sys.exit(130)

    print_summary(result)

    rd = EVAL_ROOT / "results"
    rd.mkdir(exist_ok=True, parents=True)
    sp = rd / f"retrieval_{datetime.now().strftime('%Y%m%d_%H%M%S')}.json"
    sp.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"💾 结果保存: {sp}")

    if args.save_baseline:
        bl_path = Path(args.save_baseline)
        bl_path.parent.mkdir(parents=True, exist_ok=True)
        slim = {**result, "per_question": [
            {k: v for k, v in p.items() if k != "actual_top10_chunk_ids"} for p in result["per_question"]
        ]}
        bl_path.write_text(json.dumps(slim, ensure_ascii=False, indent=2), encoding="utf-8")
        print(f"🎯 已作为新基线保存: {bl_path}")

    if args.compare:
        compare_with_baseline(result, Path(args.compare))


if __name__ == "__main__":
    main()