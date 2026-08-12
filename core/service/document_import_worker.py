"""
文档导入异步 Worker（缺口6核心：异步化 + 逐步骤状态机 + chunk粒度失败恢复）
原来上传接口 1 个 HTTP 请求走完整个流程，大 PDF 会超时。
Worker 实现：
  A. 异步：API 立刻返回 document_id，前端轮询看进度
  B. 12 状态机：parsing→parsed→chunking→chunked→embedding→indexing→ready
  C. chunk 粒度失败：100 个 chunk 挂 1 个，只失败那 1 个，其他 99 个照常写入
  D. MD5 去重：同用户下相同内容文档，跳过重复解析+embedding
"""
from __future__ import annotations

import asyncio
import hashlib
import json
import os
from datetime import datetime, timezone
from pathlib import Path
from sqlalchemy.orm import Session

from core.config import settings
from core.db.models import (
    DOCUMENT_STATUS_CHUNKED, DOCUMENT_STATUS_CHUNKING, DOCUMENT_STATUS_CHUNK_FAILED,
    DOCUMENT_STATUS_EMBED_FAILED, DOCUMENT_STATUS_EMBEDDING, DOCUMENT_STATUS_INDEXING,
    DOCUMENT_STATUS_PARSE_FAILED, DOCUMENT_STATUS_PARSED, DOCUMENT_STATUS_PARSING,
    DOCUMENT_STATUS_READY,
    IMPORT_CHUNK_STEP_FAILED,
    KnowledgeChunkFailures, KnowledgeChunks, KnowledgeDocuments,
    KNOWLEDGE_CHUNK_ROLE_LEAF, KNOWLEDGE_CHUNK_ROLE_PARENT,
)
from core.service.hierarchical_chunking import build_hierarchical_chunks
from core.service.langchain_adapters import ProjectDocumentLoader, ProjectEmbeddings
from core.service.vector_index import rebuild_user_faiss_index


def calc_file_md5(file_bytes=None, file_path=None):
    """
    计算文件 MD5（字节流 或 磁盘路径 二选一）

    ⚠️ 为什么用 64KB 分块读取，而不是 `f.read()` 一次性吃进内存？
        因为用户可能上传 500MB 的扫描件 PDF，一次性读取会打爆 Gunicorn worker。
        64KB chunk 是 MD5 block size (64bytes) 的 1024 倍，性能最优且内存常数级。

    例:
        # 小文件（<10MB）可以直接传 bytes：
        calc_file_md5(file_bytes=b"hello world")
        → '5eb63bbbe01eeed093cb22bb8f5acdc3'

        # 大文件传路径（流式）：
        calc_file_md5(file_path="E:/uploads/annual_report_2024.pdf")
        → 'a1b2c3d4...'（32 位十六进制）
    """
    h = hashlib.md5()
    if file_bytes is not None:
        h.update(file_bytes)
    elif file_path is not None:
        with open(file_path, "rb") as f:
            for c in iter(lambda: f.read(65536), b""):
                h.update(c)
    return h.hexdigest()


def find_duplicate_document(db, *, user_id, file_md5):
    """
    MD5 去重查询：同用户下 + 同 MD5 + 已成功导入 → 返回那条旧文档

    为什么条件里还要加 `status=ready`？
        因为用户可能第一次上传某个 PDF 到一半（status=embedding）时断线了，
        重传时不应该命中那次的半成品——不然拿回来的 document.chunks 是不完整的。
        只命中 ready 的才算真正去重成功。

    例:
        # 用户 1024 上传了「年度报告.pdf」，内容 MD5 = 'd41d8c...'
        # 3 天后他改名叫「年度报告_v2_FINAL_FINAL.pdf」再次上传：
        old = find_duplicate_document(db, user_id=1024, file_md5='d41d8c...')
        if old:
            # 命中！直接把 old id 返回前端，不跑解析/embedding，省 3 分钟 + 几百 API token
            return {"is_duplicate_hit": True, "document_id": old.id}
    """
    if not file_md5:
        return None
    return (
        db.query(KnowledgeDocuments)
        .filter(
            KnowledgeDocuments.user_id == user_id,
            KnowledgeDocuments.file_md5 == file_md5,
            KnowledgeDocuments.status == DOCUMENT_STATUS_READY,
        )
        .order_by(KnowledgeDocuments.created_at.desc())
        .first()
    )


def _set_doc_status(db, doc, new_status, *, error=None, processed_chunks=None,
                    failed_chunks=None, total_chunks=None):
    """
    状态机推进的唯一入口（每次调用都会 commit + refresh，保证前端轮询即时可见）

    为什么要单独包成函数，不直接写 `doc.status=... ; db.commit()`？
        因为 12 状态机里有 20+ 处推进状态的地方，每处都要同步 update 字段 + commit：
        - `updated_at` 每次必刷（前端靠它判断进度是否卡住）
        - `total_chunks / processed_chunks / failed_chunks` 这三个进度字段会互相联动
        如果每处都手写 6 行，一定会漏。

    例（Embedding 阶段一个批次成功 16 条）：
        doc = _set_doc_status(db, doc, DOCUMENT_STATUS_EMBEDDING,
                              processed_chunks=32,     # 已经完成 32 / 100
                              failed_chunks=0)
        # 前端轮询看到：status=embedding, processed_chunks=32, total_chunks=100
        # → 进度条 = 50% + 45% * (32/100) = 64.4%
    """
    doc.status = new_status
    if error is not None:
        doc.error_message = error
    if processed_chunks is not None:
        doc.processed_chunks = processed_chunks
    if failed_chunks is not None:
        doc.failed_chunks = failed_chunks
    if total_chunks is not None:
        doc.total_chunks = total_chunks
        # 老字段 chunk_count 和 total_chunks 保持同步，兼容旧前端/旧接口
        doc.chunk_count = total_chunks
    doc.updated_at = datetime.now(timezone.utc)
    db.commit()
    db.refresh(doc)
    return doc


def _record_chunk_failure(db, *, document_id, user_id, chunk_id, step_name, exc,
                          chunk_index_ref=0, retrieval_content_preview=""):
    """
    chunk 粒度失败记录落库（这就是缺口6的核心：失败了绝不整篇回滚）

    参数速查：
      document_id / user_id / chunk_id —— 三维外键，任何维度的查询都能走索引
      step_name                        —— 哪一步失败（parsing/chunking/embedding_api/faiss_write）
      exc                              —— Python 异常对象（会自动取 type name + message）
      chunk_index_ref                  —— chunk 在文档内的顺序号（即使 chunk_id=None 也能定位）
      retrieval_content_preview        —— 该 chunk 前 500 字，后台直接看不用再 join chunks 表

    例：
        try:
            await do_embedding_one(chunk_73_text)
        except httpx.ConnectTimeout as e:
            # 100 个里只有第 73 个因为网络超时 3 次重试仍失败
            # 记录进失败表，document.status 仍然会前进到 ready，不影响另外 99 个被检索
            _record_chunk_failure(
                db, document_id=42, user_id=1024,
                chunk_id=chunk_rows[72].id,
                step_name="embedding_api",
                exc=e,
                chunk_index_ref=73,
                retrieval_content_preview="第3章 公司主营业务构成情况 ..."[:500],
            )
    """
    row = KnowledgeChunkFailures(
        document_id=document_id, user_id=user_id, chunk_id=chunk_id,
        step_name=step_name, status=IMPORT_CHUNK_STEP_FAILED, retry_count=0,
        error_type=type(exc).__name__, error_message=str(exc),
        chunk_index_ref=chunk_index_ref,
        retrieval_content_preview=(retrieval_content_preview or "")[:500],
        last_retry_at=datetime.now(timezone.utc),
    )
    db.add(row)
    db.commit()
    db.refresh(row)
    return row


async def _batch_embed_with_retry(texts, *, batch_size=16, max_retries_batch=3,
                                  max_retries_item=3, backoff=1.5):
    """
    批 Embedding + 三级降级重试 + 指数退避（缺口6稳定性的灵魂）

    ══════════════════════════════════════════════════════════════
    三级降级流程（示意 20 条文本）：

    Level 1: 16 条一批（高吞吐，默认走这条）
        batch  0..15 → ✅ 全 16 条成功，直接进 result
        batch 16..19 → ❌ 失败（某一条"第7章节"里包含了一个超长表格导致 API 413 Payload too large）
            ↓ 降级！  bs//4 = 4

    Level 2: 4 条一批（能区分出是哪 4 条里面混了坏数据）
        batch 16..19 → ❌ 还是失败
            ↓ 再降级！bs//4 = 1

    Level 3: 1 条一批（精确到单条，坏数据最多只影响自己）
        chunk 16 → ✅ 成功
        chunk 17 → ✅ 成功
        chunk 18 → ❌ 3 次单条重试 + 1.5 / 2.25 / 3.375s 指数退避仍失败 → 进入 failure_idx
        chunk 19 → ✅ 成功

    返回结果：
        result[18] = []         # 失败的那条留空向量
        failure_idx = [18]      # 失败下标，外层据此写 KnowledgeChunkFailures 表

    为什么这样设计？
      1. 绝大多数批次（~95%）在 Level 1 成功，吞吐 = batch_size=16
      2. 只有 5% 的异常批次降级，且越拆越细（16→4→1），不会因为 1 条毒数据整批陪葬
      3. 指数退避（1.5^i 秒）应对 API 限流 429：第1次等1.5秒 → 第2次等2.25秒 → 第3次等3.375秒
         基本能度过限流窗口，不会和限流计数器硬撞
      4. 返回的向量数组顺序严格和输入 texts 对齐，外层不用改下标直接 zip(leaf_rows, embeddings)

    参数：
      texts                 —— 要 embedding 的文本列表（retrieval_content）
      batch_size            —— 起始批大小（默认 16，匹配大部分 Embedding 服务的单次 batch 上限）
      max_retries_batch     —— 批模式（Level1/2）最多重试次数
      max_retries_item      —— 单条模式（Level3）最多重试次数
      backoff               —— 指数退避基数（1.5 → 1.5/2.25/3.375）

    返回: (result: list[list[float]], failure_idx: list[int])
      result[i]      —— texts[i] 对应的向量；失败的位置是 []
      failure_idx    —— 真正挂了的下标集合（外层据此写失败表）
    """
    N = len(texts)
    # 预占位 N 个空列表，后面按 index 填值（保证顺序严格对齐输入 texts）
    result = [[] for _ in range(N)]
    failure_idx = []
    if N == 0:
        return result, failure_idx
    svc = ProjectEmbeddings()

    async def _try(fn, times):
        """
        通用重试器：执行 fn() 最多 times 次，每次失败按 backoff^i 指数等待。
        返回 (return_value_or_None, last_exception_or_None)
        """
        last = None
        for i in range(1, times + 1):
            try:
                return await fn(), None
            except Exception as e:
                last = e
                # 指数退避等待：i=1→1.5s, i=2→2.25s, i=3→3.375s
                await asyncio.sleep(backoff ** i)
        return None, last

    # 初始划分：按 batch_size=16 切片（range 三元组：起始下标、结束下标、当前批大小）
    ranges = []
    for s in range(0, N, batch_size):
        ranges.append((s, min(s + batch_size, N), batch_size))
    next_round = []

    while ranges:
        for s, e, bs in ranges:
            bt = texts[s:e]
            # ---- Level 3：单条模式（bs == 1 时走这里，拆到最后一层了）----
            if len(bt) == 1:
                async def _one(t=bt[0]):
                    r = await svc.aembed_documents([t])
                    return r[0] if r else []
                v, err = await _try(_one, max_retries_item)
                if err is None:
                    result[s] = v or []
                else:
                    # 单条都连续失败 max_retries_item 次 → 记入失败集合，交给外层写 DB
                    failure_idx.append(s)
                continue

            # ---- Level 1 / 2：批模式（16 or 4 条一批）----
            async def _b(batch_t=bt):
                return await svc.aembed_documents(batch_t)
            vs, err = await _try(_b, max_retries_batch)
            if err is None and vs is not None and len(vs) == len(bt):
                # 整批成功 → 原样写入对应 result 区间
                for off, v in enumerate(vs):
                    result[s + off] = v or []
            else:
                # 批失败 → 降级：把当前批拆成 4 份更小的批，推到下一轮循环继续
                #   bs=16 失败 → new_bs=4 → push 4 个小批
                #   bs=4  失败 → new_bs=1 → push 4 个单条（下一轮循环进 Level 3）
                new_bs = max(1, bs // 4)
                for sub in range(s, e, new_bs):
                    next_round.append((sub, min(sub + new_bs, e), new_bs))
        # 本轮 ranges 处理完，下一轮继续拆小的批；直到 ranges 为空才算全部收敛
        ranges = next_round
        next_round = []
    return result, failure_idx


async def run_document_import_pipeline(*, document_id, user_id, stored_path,
                                       file_type, file_name, raw_content_bytes=None):
    """
    【文档导入异步主流水线】——被 BackgroundTasks.add_task 离线调度

    ════════════════════════════════════════════════════════════════
    4 个阶段对应的状态流转（每一步都 commit 到 DB，前端轮询即时看到）：

        阶段 0：MD5 / 文件大小写入（状态还是 uploaded，进度条起点 5%）
        → 解析 ( parsing → parsed / parse_failed )            10% → 30%
        → 分块 ( chunking → chunked / chunk_failed )          30% → 50%
        → 向量化 ( embedding → 平滑进度条前进 )                50% → 95%
        → 索引 ( indexing → ready / embed_failed )            95% → 100%

    其中任何一个阶段抛出异常，会把 status 设成对应失败状态（parse_failed /
    chunk_failed / embed_failed）并立即 return。失败信息写进 error_message，
    前端轮询看到后根据具体状态展示不同的「下一步按钮」。

    典型调用链：
        api/routes/knowledge.py  POST /upload
            → 先保存文件、先 INSERT document 行（status=uploaded）
            → background_tasks.add_task(
                  run_document_import_pipeline,
                  document_id=42, user_id=1024, ...
              )
            → HTTP 立刻返回 {data: {id:42, status:"uploaded", progress:5%}}

        后台异步 Worker 跑上面 4 个阶段，前端每 1 秒 GET /{id}/status 轮询，
        直到 status 变成 ready → 前端显示"✅ 导入完成"。

    典型失败 scenario（100 个 chunk，第 73 个 Embedding API 超时）：
        阶段 3 跑完 → failed_idx=[72]（下标从 0 开始）
                    → processed_chunks=99, failed_chunks=1
        阶段 4 跑完 → status = ready（因为还有 99 个成功的，不应该整篇失败）
                    → error_message = "文档导入完成，但 1/100 个 chunk embedding 失败，
                       可点击「重试失败chunk」按钮单独重试"
                    → 前端进度条 100%，但右上角显示一个 ⚠️ 黄标，附「重试失败chunk」按钮
    """
    from core.db.session import SessionLocal
    db = SessionLocal()
    try:
        doc = db.query(KnowledgeDocuments).filter(
            KnowledgeDocuments.id == document_id,
            KnowledgeDocuments.user_id == user_id,
        ).first()
        if not doc:
            return

        # ====== 阶段 0：MD5 去重 + 文件大小记录 ======
        # （上传接口在调这个函数之前已经查过一次 MD5 了，但这里再兜底一次，
        #  因为以后换 Celery/其他任务系统时 BackgroundTasks 可能不再传 raw_content_bytes）
        if raw_content_bytes:
            md5 = calc_file_md5(file_bytes=raw_content_bytes)
            size = len(raw_content_bytes)
        else:
            md5 = calc_file_md5(file_path=stored_path)
            size = os.path.getsize(stored_path) if os.path.isfile(stored_path) else 0
        doc.file_md5 = md5
        doc.file_size_bytes = size
        db.commit()
        db.refresh(doc)

        # ====== 阶段 1：解析（parsing → parsed / parse_failed） ======
        #   PDF/Word/Excel → 全文 + pages/sections 结构
        doc = _set_doc_status(db, doc, DOCUMENT_STATUS_PARSING)
        parsed = None
        full_text = ""
        try:
            loader = ProjectDocumentLoader(
                stored_path, file_type=file_type,
                metadata={"document_id": doc.id, "document_name": file_name},
            )
            loaded = list(loader.lazy_load())
            if not loaded:
                raise RuntimeError("Loader did not produce any document")
            source = loaded[0]
            parsed = source.metadata.get("parsed_document") or {
                "full_text": source.page_content or "",
                "pages": [], "sections": [], "metadata": {},
            }
            full_text = source.page_content or ""
            doc.content_text = full_text
            # 解析完成 → 进入 parsed 过渡状态（很快会进 chunking）
            doc = _set_doc_status(db, doc, DOCUMENT_STATUS_PARSED, error="")
        except Exception as exc:
            # 例：PDF 加密 → status=parse_failed，前端显示"文档损坏请重新上传"
            _set_doc_status(db, doc, DOCUMENT_STATUS_PARSE_FAILED, error=str(exc))
            return

        # ====== 阶段 2：分块（chunking → chunked / chunk_failed） ======
        #   全文 → parent chunk（大块）+ leaf chunk（实际召回的小块，真正做 embedding）
        doc = _set_doc_status(db, doc, DOCUMENT_STATUS_CHUNKING)
        leaf_items = None
        leaf_rows = None
        try:
            chunk_items = build_hierarchical_chunks(
                parsed, file_type=file_type,
                chunk_size=settings.RAG_CHUNK_SIZE,
                overlap=settings.RAG_CHUNK_OVERLAP,
                use_semantic_chunking=settings.USE_SEMANTIC_CHUNKING,
            )
            if not chunk_items:
                raise RuntimeError("No chunk items produced")
            parent_items = [x for x in chunk_items if x["chunk_role"] == KNOWLEDGE_CHUNK_ROLE_PARENT]
            leaf_items = [x for x in chunk_items if x["chunk_role"] == KNOWLEDGE_CHUNK_ROLE_LEAF]

            # ---- 2.1 先 INSERT parent（需要先拿到 parent 行的 id 供 leaf 外键引用）----
            lp_map = {}
            for it in parent_items:
                row = KnowledgeChunks(
                    document_id=doc.id, user_id=user_id,
                    chunk_index=int(it["chunk_index"]),
                    chunk_role=it["chunk_role"], parent_chunk_id=None,
                    parent_title=it["parent_title"], block_type=it["block_type"],
                    child_index=int(it["child_index"]),
                    table_row_from=it["table_row_from"], table_row_to=it["table_row_to"],
                    content=it["content"], retrieval_content="",
                    start_offset=int(it["start_offset"]), end_offset=int(it["end_offset"]),
                    source_page=it["source_page"],
                    source_section=it["source_section"] or "",
                    embedding_json="",
                )
                db.add(row); db.flush()  # flush 不取 id，拿不到 id 就没法给 leaf 挂外键
                lp_map[it["local_parent_key"]] = row.id

            # ---- 2.2 再 INSERT leaf（真正做 embedding 的是它们）----
            leaf_rows = []
            for it in leaf_items:
                pid = lp_map.get(it["local_parent_key"])
                row = KnowledgeChunks(
                    document_id=doc.id, user_id=user_id,
                    chunk_index=int(it["chunk_index"]),
                    chunk_role=it["chunk_role"], parent_chunk_id=pid,
                    parent_title=it["parent_title"], block_type=it["block_type"],
                    child_index=int(it["child_index"]),
                    table_row_from=it["table_row_from"], table_row_to=it["table_row_to"],
                    content=it["content"],
                    retrieval_content=it["retrieval_content"],
                    start_offset=int(it["start_offset"]), end_offset=int(it["end_offset"]),
                    source_page=it["source_page"],
                    source_section=it["source_section"] or "",
                    embedding_json="",
                )
                db.add(row)
                leaf_rows.append(row)

            # 分块完成 → 状态推进到 chunked，total_chunks 此时确定（给前端做进度条分母）
            doc = _set_doc_status(
                db, doc, DOCUMENT_STATUS_CHUNKED,
                error="", total_chunks=len(chunk_items),
                processed_chunks=0, failed_chunks=0,
            )
        except Exception as exc:
            _set_doc_status(db, doc, DOCUMENT_STATUS_CHUNK_FAILED, error=str(exc))
            return

        # ====== 阶段 3：Embedding（最耗时的一步，进度条平滑推进的核心） ======
        #   把所有 leaf 的 retrieval_content 扔进 _batch_embed_with_retry，
        #   成功的写 embedding_json，失败的写进 KnowledgeChunkFailures 表
        doc = _set_doc_status(db, doc, DOCUMENT_STATUS_EMBEDDING)
        N_leaf = len(leaf_items or [])
        if N_leaf > 0 and leaf_rows:
            try:
                rtexts = [it["retrieval_content"] for it in leaf_items]
                # ★ 调用三级降级重试核心（16→4→1 + 指数退避）
                embeddings, failed_idx = await _batch_embed_with_retry(rtexts)

                # 循环 A：把成功的向量写进 chunk 行
                for off, (row, emb) in enumerate(zip(leaf_rows, embeddings)):
                    try:
                        row.embedding_json = json.dumps(emb, ensure_ascii=False) if emb else ""
                        db.add(row)
                    except Exception as _e:
                        # 单个 chunk 的 JSON 序列化失败不能让整批挂，写入失败表即可
                        _record_chunk_failure(
                            db, document_id=doc.id, user_id=user_id,
                            chunk_id=row.id, step_name="embedding_json_serialize", exc=_e,
                            chunk_index_ref=int(leaf_items[off]["chunk_index"]),
                            retrieval_content_preview=rtexts[off],
                        )

                # 循环 B：把 API 级别失败的 chunk 写成失败行（例如 3 次 429 仍挂）
                for bi in failed_idx:
                    row_ref = leaf_rows[bi]
                    _record_chunk_failure(
                        db, document_id=doc.id, user_id=user_id,
                        chunk_id=row_ref.id, step_name="embedding_api",
                        exc=RuntimeError("Embedding 连续失败 3 次（批→分→单条 全流程失败）"),
                        chunk_index_ref=int(leaf_items[bi]["chunk_index"]),
                        retrieval_content_preview=rtexts[bi],
                    )

                db.commit()
                db.refresh(doc)
                success_cnt = N_leaf - len(failed_idx)
                # 更新 processed_chunks / failed_chunks，前端下一次轮询时看到
                # progress = 50 + 45 * success_cnt / total_chunks
                doc = _set_doc_status(
                    db, doc, DOCUMENT_STATUS_EMBEDDING,
                    processed_chunks=success_cnt, failed_chunks=len(failed_idx),
                )
                if success_cnt == 0:
                    # 全部 leaf 挂了 → 这篇文档没法用，直接判 embed_failed
                    _set_doc_status(
                        db, doc, DOCUMENT_STATUS_EMBED_FAILED,
                        error=f"全部 {N_leaf} 个 leaf chunk embedding 失败，请检查 Embedding API",
                        processed_chunks=0, failed_chunks=N_leaf,
                    )
                    return
            except Exception as exc:
                _set_doc_status(db, doc, DOCUMENT_STATUS_EMBED_FAILED, error=str(exc))
                return

        # ====== 阶段 4：写 FAISS 索引（indexing → ready） ======
        doc = _set_doc_status(db, doc, DOCUMENT_STATUS_INDEXING)
        try:
            # rebuild_user_faiss_index 内部会把刚才新写的 chunk 的 embedding_json
            # 读出来，合成 numpy 数组写进 FAISS 文件（磁盘上的 .index 文件）。
            # 这里就算 FAISS 写失败了也不应该把整篇文档判失败，try/except 兜底 pass。
            rebuild_user_faiss_index(db, user_id=user_id)
        except Exception:
            pass

        # 收尾：根据 failed_chunks 给 error_message 赋值
        if doc.failed_chunks and doc.failed_chunks > 0:
            # 局部失败提示（前端展示 ⚠️ + "重试失败chunk" 按钮）
            doc.error_message = (
                f"文档导入完成，但 {doc.failed_chunks}/{doc.total_chunks or N_leaf} 个 chunk "
                f"embedding 失败，可点击「重试失败chunk」按钮单独重试"
            )
        else:
            doc.error_message = ""
        doc.status = DOCUMENT_STATUS_READY
        doc.updated_at = datetime.now(timezone.utc)
        db.commit()
    finally:
        db.close()