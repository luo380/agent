# 缺口8：向量库升级（pgvector / Milvus）—— 详细实施方案

> 对应文档：《检索与入库技术深化学习规划.md》缺口8
> 预计工作量：pgvector 版 2~3 天；Milvus 版 5~7 天（含运维）
> 优先级：【长期】FAISS 文件真的不够用了再上，不急

---

## 一、FAISS 文件方案的瓶颈（什么时候该升级 pgvector？）

当前 FAISS + 文件存储的极限：

| 瓶颈 | FAISS（当前） | pgvector | Milvus |
|-----|--------------|----------|--------|
| 单用户向量数 | ~500 万条（HNSW64 内存够用） | ~1 亿条（PG 表存储） | > 10 亿条（分布式分片） |
| 多服务器共享 | ❌ 文件在本地磁盘，A 服务器建了 B 服务器看不到 | ✅ 连同一个 PG 就行 | ✅ 存对象存储，分布式 |
| 增量更新性能 | ⚠️ 每次重建全量索引（100万条=分钟级） | ✅ 单条 INSERT 毫秒级 | ✅ 实时写入 |
| 多租户隔离 | ⚠️ 一个 user 一个 .faiss 文件，管理麻烦 | ✅ user_id 列过滤，SQL 原生 | ✅ Collection 隔离 |
| 元数据过滤 | ⚠️ 后置过滤（先搜再删） | ✅ WHERE 条件和向量查询组合 | ✅ 原生标量过滤 |
| 运维复杂度 | ✅ 零运维，文件而已 | ⚠️ 装 PG 扩展 + 建索引 | ❌ Kubernetes 运维，分布式集群 |
| 一致性 / ACID | ❌ 文件损坏无保护 | ✅ PG 事务 + WAL 日志 | ⚠️ 最终一致 |

**触发升级 pgvector 的信号（满足任意一个就该上）**：
1. 单用户 chunk 数突破 500 万，HNSW 内存吃满服务器 RAM
2. 开始部署多台 Web 服务器（FAISS 文件不同步，A 重建 B 看不到）
3. 需要"分钟级实时入库"（上传后 30 秒内可检索，不想等完整重建）
4. 元数据过滤的频率很高（后置过滤 + 300 条兜底还是不够 Recall）

**触发升级 Milvus 的信号（满足任意一个）**：
1. 单库向量数 > 1 亿条
2. 需要多租户 + RBAC + 资源隔离（企业级 SaaS）
3. 混合查询 QPS > 500（并发查询压力 PG 顶不住）

---

## 二、技术路线选择：先 pgvector，再考虑 Milvus

### 决策树

```
现在用的 FAISS 文件方案
    │
    ▼ 遇到瓶颈了吗？
    │
    ├─ 没瓶颈 → 别动！（FAISS 简单好用性能高，不要为了"上新技术"而上）
    │
    └─ 有瓶颈
        │
        ▼ 瓶颈是什么？
        │
        ├─ 多服务器共享 / 增量更新慢 / 元数据过滤
        │   → 先上 pgvector（和现有 PG 同一套存储，零新增组件）
        │
        └─ 单库破亿 / QPS 500+ / 多租户企业级
            → 直接上 Milvus（分布式向量库专业选手）
```

---

## 三、分步实施方案：pgvector 版（2~3 天）

### 步骤 1：安装 pgvector 扩展

```bash
# 服务器上安装（PostgreSQL 12+ 都支持）
# Ubuntu/Debian:
sudo apt-get install postgresql-15-pgvector

# macOS (Homebrew):
brew install pgvector

# 然后进入 PostgreSQL 控制台：
# CREATE EXTENSION IF NOT EXISTS vector;
```

验证安装：
```sql
-- 连到 app 数据库执行
SELECT * FROM pg_extension WHERE extname = 'vector';
-- 能查到 vector 扩展就行
```

---

### 步骤 2：数据库迁移 + 加索引

Alembic 迁移脚本：

```python
# alembic/versions/20260812_xxxxx_add_pgvector_column.py
"""
迁移目标：
1. KnowledgeChunks 表加 embedding vector(1536) 列（存储原始向量）
2. 加 HNSW 索引（余弦相似度 = inner product）
3. (可选) 加 IVFFlat 索引（更快构建，精度略低）
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSON

# 注意：pgvector 的 vector 类型要从 pgvector.sqlalchemy 导入
# 需要先 pip install pgvector
from pgvector.sqlalchemy import Vector


def upgrade():
    # Step A: 新增 embedding 列
    # 注意：如果是 text-embedding-3-small → dim=1536
    #       如果是 text-embedding-ada-002 → dim=1536
    #       如果是 bge-large-zh-v1.5 → dim=1024
    #       要和实际使用的 embedding 模型维度一致
    op.add_column(
        "knowledge_chunks",
        sa.Column("embedding", Vector(1536), nullable=True, comment="chunk的向量嵌入(pgvector)"),
    )

    # Step B: 把 metadata 字段的 JSON 类型声明迁移一下（如果还没加，对应缺口2）
    # （如果缺口2已经加过，这步跳过）

    # Step C: 建 HNSW 索引（余弦距离 = ip = inner product，因为我们的向量都 L2 归一化了）
    # 【重要】用 CONCURRENTLY 建索引，不锁表（线上零停机）
    # CONCURRENTLY 不能包在事务里，所以要手动用 autocommit，Alembic 里写法特殊：
    op.execute("COMMIT")  # 先提交当前事务
    op.execute("""
        CREATE INDEX CONCURRENTLY IF NOT EXISTS idx_knowledge_chunks_embedding_hnsw
        ON knowledge_chunks
        USING hnsw (embedding vector_cosine_ops)
        WITH (m = 64, ef_construction = 400);
    """)

    # Step D: 辅助索引（配合元数据过滤 + 用户过滤）
    op.create_index(
        "idx_knowledge_chunks_user_doc",
        "knowledge_chunks",
        ["user_id", "document_id"],
    )


def downgrade():
    op.drop_index("idx_knowledge_chunks_user_doc", table_name="knowledge_chunks")
    op.drop_index("idx_knowledge_chunks_embedding_hnsw", table_name="knowledge_chunks")
    op.drop_column("knowledge_chunks", "embedding")
```

---

### 步骤 3：SQLAlchemy 查询改写（pgvector 向量检索）

在 `vector_index.py` 新增一个 pgvector 实现，和现有的 FAISS 实现可以双轨并行（通过配置切换）：

```python
# core/service/vector_index_pg.py
from __future__ import annotations
from sqlalchemy.orm import Session
from sqlalchemy import select, and_, or_, func, case, text
from pgvector.sqlalchemy import Vector

from core.db.models import KnowledgeChunks
from core.service.retrieval import SearchResultChunk


def hybrid_search_pgvector(
    db: Session,
    user_id: int,
    query_vector: list[float],
    *,
    top_k: int = 10,
    candidate_top_n: int = 50,
    # ========== 元数据过滤参数（和 FAISS 后置过滤版保持一致的 API）==========
    document_ids: list[int] | None = None,
    upload_date_from: str | None = None,
    upload_date_to: str | None = None,
    doc_category_in: list[str] | None = None,
    file_type_in: list[str] | None = None,
    section_level_lte: int | None = None,
    metadata_filter: dict | None = None,
) -> list[SearchResultChunk]:
    """
    【pgvector 版】混合检索

    和 FAISS 版最大的不同：元数据过滤 WHERE 条件直接下推到 SQL + 向量 ANN 同时执行，
    不需要先粗搜300条再过滤，Recall 不会因为过滤而损失。
    """

    # Step 1: 组装 WHERE 条件（所有元数据过滤都下推 SQL，原生高效）
    conds = [
        KnowledgeChunks.user_id == user_id,
        KnowledgeChunks.is_deleted == False,
        KnowledgeChunks.embedding.is_not(None),  # NULL 向量跳过
    ]

    if document_ids:
        conds.append(KnowledgeChunks.document_id.in_(document_ids))

    # section_level_lte 用冗余列（如果缺口2已经加了）
    if section_level_lte is not None:
        conds.append(KnowledgeChunks.section_level <= section_level_lte)

    # 其他维度用 metadata JSON 字段过滤（PostgreSQL 的 JSONB 操作符）
    # 注意：JSON 过滤比冗余列慢，但比 FAISS 的后置过滤强多了
    if upload_date_from:
        conds.append(text("(metadata->>'upload_date') >= :ud_from").params(ud_from=upload_date_from))
    if upload_date_to:
        conds.append(text("(metadata->>'upload_date') <= :ud_to").params(ud_to=upload_date_to))
    if doc_category_in:
        conds.append(text("metadata->>'doc_category' = ANY(:dc_list)").params(dc_list=doc_category_in))
    if file_type_in:
        conds.append(text("metadata->>'file_type' = ANY(:ft_list)").params(ft_list=file_type_in))

    # 通用 metadata_filter 字典（简单版：支持等于）
    if metadata_filter:
        for k, v in metadata_filter.items():
            if isinstance(v, list):
                conds.append(text(f"metadata->>:{k} = ANY(:v_list)").bindparams(k=k, v_list=v))
            else:
                conds.append(text(f"metadata->>:{k} = :v_eq").bindparams(k=k, v_eq=v))

    # Step 2: pgvector 余弦相似度查询
    # L2 归一化后：1 - cosine_distance = 内积分数（和 FAISS 的 score 一致范围 0~1）
    stmt = (
        select(
            KnowledgeChunks.id,
            KnowledgeChunks.document_id,
            KnowledgeChunks.content,
            KnowledgeChunks.heading_path,
            # cosine_distance 返回 0（完全相同）~2（完全相反）
            # 1 - cosine_distance 转成 -1~1 的相似度分数（和 FAISS 对齐）
            (1 - KnowledgeChunks.embedding.cosine_distance(func.cast(query_vector, Vector(1532)))).label("score"),
        )
        .where(and_(*conds))
        # 直接让 PG 按相似度排序 + LIMIT（HNSW 索引会加速这里）
        .order_by(KnowledgeChunks.embedding.cosine_distance(func.cast(query_vector, Vector(1536))))
        .limit(candidate_top_n)
    )

    rows = db.execute(stmt).all()

    # Step 3: 转成 SearchResultChunk 格式（上层 rerank / 答案生成完全不用改）
    results = []
    for row in rows:
        score = float(row.score)
        if score < 0:  # 负分的基本是完全不相关，扔掉
            continue
        results.append(SearchResultChunk(
            chunk_id=row.id,
            document_id=row.document_id,
            score=score,
            content=row.content or "",
            heading_path=row.heading_path,
            metadata=None,  # 需要的话可以 SELECT 时带出来
        ))

    return results[:top_k]
```

---

### 步骤 4：embedding 回写 + 增量索引（不需要再全量 rebuild_user_faiss_index）

pgvector 是单条 `INSERT / UPDATE embedding 列`，每向量化完一条 chunk 就能立刻写进去，不需要等所有 chunk 都完了再「重建整个索引」：

```python
# knowledge_service.py 中写 chunk 时，embedding 字段同步写入
chunk = KnowledgeChunks(
    document_id=doc.id,
    chunk_index=i,
    content=content,
    section_level=section_level,
    metadata=metadata_dict,
    embedding=embeddings[i],  # 【新增】直接写进 PG，立刻可检索
)
db.add(chunk)

# 每写一批 COMMIT 一次（100条一提交），用户可以边上传边搜到
if i % 100 == 0:
    db.commit()
```

对比 FAISS 版的差异：

| 环节 | FAISS（旧） | pgvector（新） |
|-----|------------|----------------|
| 写完 chunk 能搜到吗？ | ❌ 要等全部写完 + rebuild_user_faiss_index 原子切换 | ✅ COMMIT 后立刻可以搜到（增量实时） |
| 第 500 条失败 | 前 499 条白写了（索引没建） | 前 499 条已经 COMMIT，在检索里立刻可见 |
| 重建耗时 | 100万条 ~ 分钟级 | ❌ 不需要重建！HNSW 索引 PG 自动维护（单条INSERT毫秒级） |

---

### 步骤 5：双轨切换开关（配置化，平滑升级）

`core/config.py` 加：

```python
# 向量存储后端：FAISS 本地文件 / PGVECTOR PostgreSQL 原生
VECTOR_BACKEND: str = os.getenv("VECTOR_BACKEND", "FAISS").upper()  # "FAISS" | "PGVECTOR"
```

`retrieval.py` 做路由：

```python
def hybrid_search(db, user_id, query_text, **kwargs):
    # 1. 生成 query_vector（两种后端共用）
    query_vector = embed(query_text)
    top_k = kwargs["top_k"]

    # 2. 根据配置路由到不同后端
    if settings.VECTOR_BACKEND == "PGVECTOR":
        return vector_index_pg.hybrid_search_pgvector(db, user_id, query_vector, **kwargs)
    else:
        # 现有 FAISS 流程完全不变
        faiss_results = _vector_search_faiss(user_id, query_vector, ...)
        bm25_results = _bm25_search(db, user_id, query_text, ...)
        merged = _reciprocal_rank_fusion(faiss_results, bm25_results)
        filtered = _apply_metadata_filter(merged, ...)
        return filtered[:top_k]
```

**升级路径**（完全可回滚）：
1. 先开双写：写 chunk 时同时写 FAISS（原流程）+ 写 PG embedding 列
2. 跑一次脚本：把历史所有 chunk 的 embedding 回写 PG embedding 列
3. 单用户测试：对 user_id=42 临时切 `VECTOR_BACKEND=PGVECTOR`，问几题对比结果
4. 全量切换：.env 改 `VECTOR_BACKEND=PGVECTOR`，重启
5. 稳定一周后：停掉 FAISS 的 rebuild_user_faiss_index 任务，释放磁盘空间
6. 出现问题随时切回 FAISS，零风险

---

## 四、Milvus 路线简述（等 PG 也不够再看）

Milvus 架构和 pgvector 差异比较大，需要新增一套分布式存储组件：

```
当前架构（单机）：
    FastAPI ←→ PostgreSQL（元数据 + pgvector 向量 + HNSW索引）

Milvus 架构（分布式）：
    FastAPI ←→ Milvus SDK / PyMilvus
                     ↕
            Milvus Cluster
            ├─ DataNode  ──→ MinIO / S3（向量存在对象存储，不占本地盘）
            ├─ QueryNode ──→ 分布式查询，水平扩容加机器就行
            ├─ IndexNode ──→ 后台异步建 HNSW/IVF 索引
            ├─ Etcd      ──→ 元数据协调
            └─ RootCoord / DataCoord / QueryCoord（调度大脑）
```

**什么时候真的要上 Milvus？**
- 数据量：> 1 亿条，pgvector 表 100GB+，备份一次都几小时
- 并发：RAG 查询 QPS 稳定 > 500，加 pg 索引还是顶不住
- 业务：企业级 SaaS 产品，要支持 1000+ 租户每个百万级数据

**工作量提醒**：Milvus 运维复杂度比 pgvector 高 5~10 倍，建议独立出 1~2 周专门做压测和稳定性测试，不要贸然接业务。

---

## 五、集成测试验证清单

| 测试场景 | 期望结果 |
|---------|---------|
| 10 万条向量 HNSW 索引构建时间 | PG HNSW 索引 < 10 分钟（CONCURRENTLY 期间不阻塞写入） |
| 单用户 10 万条向量的 Top10 查询延迟 | < 10ms（和 FAISS HNSW 差不多） |
| 检索准确率 | 和 FAISS 版 Recall@10 差距在 ±2% 内 |
| 元数据过滤（只搜8月份的PDF） | WHERE 条件下推 SQL，结果 100% 正确且比 FAISS 后置过滤快 |
| 增量写入后实时可见 | INSERT chunk + COMMIT → 立刻能通过 pgvector 检索到（30秒内） |
| 旧数据迁移脚本 | 所有历史 embedding >99% 都正确回写 PG embedding 列，NULL 率 <1% |
| FAISS ↔ PGVECTOR 双轨切换 | 同一个问题切两边结果分数排序大体一致，核心测试题差距 <3 名 |

---

## 六、关键注意点

1. **不要为了上技术而上**：FAISS + ANN（缺口4）单用户能撑到 500 万条，大部分中小场景一辈子用不到 Milvus。pgvector 也要等真遇到「多服务器共享」或者「实时入库」再上。
2. **pgvector 索引参数和 FAISS 对齐**：`m=64`（HNSW 邻居数）对应 FAISS 的 `HNSW64`，`ef_construction=400` 也一样。两套后端的参数对齐后，检索精度才会在同一水平线上。
3. **先双写再切读**：至少双写一周，确保两边数据 100% 对齐了再切读流量。切读第一天也要保留 FAISS 文件索引的回滚开关。
4. **NULL 向量保护**：部分历史 chunk 可能还没回写 embedding（NULL），查询时必须加 `embedding IS NOT NULL`，否则 pgvector 会报错。
5. **pgvector 的 IVFFlat 索引作为备选**：如果 HNSW 构建实在太慢（亿级），可以先上 IVFFlat（`lists=16384, probes=32`），构建快 5~10 倍，精度降 3% 左右。