# evaluations 目录说明

RAG 评测体系的「本地工作台」，按评测的「Layer 金字塔」组织：

```
evaluations/
├── README.md                       ← 本文件（快速上手指南）
│
├── datasets/                       ← Layer 0~1 评测集（手工标注，迭代扩充）
│   └── testset_v1.yaml             ← 最初的20题基础版，每次迭代更新v2/v3
│
├── baseline/                       ← 基准分数（每次改动前的参照系）
│   └── baseline_v1.json            ← 第一次跑脚本生成，别手动改
│
└── results/                        ← 每次跑评测的原始结果（自动按时间戳存档）
    └── retrieval_20260812_153000.json
```

---

## 🚀 5 分钟跑通第一次评测

### Step 1：先把 datasets/testset_v1.yaml 写好（30 分钟）

1. 确定一个评测专用账号，比如 `user_id=42`，这个账号下要有至少 10 篇文档
2. 把 `testset_v1.yaml` 里的 `default_user_id: 42` 改成你的用户ID
3. 至少写 20 道题，**关键是填 `expected_chunk_ids`**：
   - 先在前端聊天界面问这道题
   - 看「引用来源」点进去，找到包含正确答案的那个 chunk
   - F12 看接口响应或者用数据库查一下这个 chunk 的 id
   - 填到 `expected_chunk_ids: [12345]` 里
4. 四类问题平均分布：事实(8道) + 流程(5道) + 对比(4道) + 总结(3道)

### Step 2：跑第一次，建立 baseline_v1.json

```bash
cd E:\02agent

# 第一次跑：存成 baseline
python scripts/evaluate_rag_retrieval.py --user-id 42 --save-baseline evaluations/baseline/baseline_v1.json
```

看到类似下面的输出就算成功：
```
📝 加载评测集: testset_v1.yaml （共 20 题）
════════════════════════════════════════════════════════════════════
【RAG 检索层评测结果汇总】
════════════════════════════════════════════════════════════════════
  Recall@5    : 78.57%
  Recall@10   : 85.71%
  MRR@10      : 0.6123
  Hit Rate@10 : 92.86%
  平均延迟      : 85.2 ms
```

**这个 baseline_v1.json 非常重要，是你所有改动的「打分参照系」，不要手动修改它。**

### Step 3：每次改代码，都和 baseline 对比

```bash
# 比如：刚加完 CrossEncoder rerank，想看看有没有用
python scripts/evaluate_rag_retrieval.py --user-id 42 --compare evaluations/baseline/baseline_v1.json
```

输出会自动告诉你：
```
📊 === 与基线版本分数对比 ===
指标             基线   当前     变化
Recall@5        78.57% 82.14%   ↑ +4.54%
Recall@10       85.71% 89.29%   ↑ +4.17%
MRR@10           0.61   0.72    ↑ +18.0%
...
🎉 进步最大的问题（按召回提升排序）:
  #q003 +100% 员工请病假需要什么材料？
⚠️ 退步最大的问题（需要重点检查）:
  #q008 -20%  企业版年付报价
```

---

## 📋 日常开发规范（每次改 RAG 相关代码必做）

```
改代码前：
    1. 切到一个干净的 git 分支
    2. 先跑一次当前 baseline_v1 的分数，确认环境没问题
        → python scripts/evaluate_rag_retrieval.py --user-id 42 --compare baseline/baseline_v1.json
        → （主要是怕 FAISS 索引坏了 / Embedding API 挂了，先确认 baseline 能复现）

改完代码：
    3. 先 Level 0 手测 5 道最没底的题（1分钟），肉眼看答案对不对
    4. 跑 Level 1 脚本：同上 --compare baseline
    5. 看 3 个核心指标：
          - Recall@10 下降 > 1% → 不许合代码，先看脚本列出的退步最大问题
          - MRR@10 下降 > 3% → 排序变差了，检查 rerank / 融合权重
          - avg_latency 翻倍 → 查是不是新写了个循环查数据库 N+1
    6. 指标稳定 → commit message 里附本次评测的 5 个数字
          例：feat(rerank): 加入 CrossEncoder 精排
              Recall@10 85.71% → 89.29% (+4.17%)
              MRR@10 0.61 → 0.72 (+18%)
              延迟 85ms → 112ms (+32%)

每月月底：
    7. 从线上真实用户的「被踩答案」里挑 5 道新题，追加进 testset_v2.yaml
    8. 跑一次脚本，存新的 baseline_v2.json
       （旧 baseline 保留不删，可追溯历史变化趋势）
```

---

## 🎯 各指标目标值（根据你的业务真实情况调整）

| 指标 | 及格线（系统基本可用） | 优秀线（接近SOTA） |
|-----|---------------------|-------------------|
| Recall@5 | ≥ 70% | ≥ 85% |
| Recall@10 | ≥ 80% | ≥ 92% |
| MRR@10 | ≥ 0.5 | ≥ 0.75 |
| Hit Rate@10 | ≥ 90% | ≥ 98% |
| 平均延迟（单题） | < 200ms | < 50ms |

**如果 5 个指标已经达到「优秀线」** → 可以升级做 Level 2（Ragas 生成层评测）。

---

## 🧪 进阶 Layer 2：Ragas 端到端评测（可选）

```bash
# 1. 先装 Ragas
pip install ragas datasets

# 2. 等我们后续补 scripts/evaluate_rag_end2end_ragas.py
#    （需要每道题的 ground_truth_answer 字段，先在 yaml 里写好就行）
```

Ragas 的 4 个指标目标：
- Faithfulness（忠实度）≥ 0.85 → **最关键**，低于 0.5 就是在瞎编
- Answer Relevance（切题度）≥ 0.80
- Context Precision ≥ 0.75
- Context Recall ≥ 0.80