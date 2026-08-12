import json
import os
import uuid
from pathlib import Path
from fastapi import APIRouter, File, Depends, UploadFile, HTTPException, BackgroundTasks
from sqlalchemy.orm import Session

from api.deps import get_db, get_current_user
from api.schemas.knowledge import (
    KnowledgeDocumentResponse, KnowledgeDocumentDetailResponse,
    KnowledgeChunkResponse, KnowledgeDocumentImportTaskResponse,
)
from core.config import settings
from core.service.vector_index import rebuild_user_faiss_index
from core.service.document_import_worker import (
    calc_file_md5,
    find_duplicate_document,
    run_document_import_pipeline,
)

from core.db.models import (
    User,
    KnowledgeDocuments,
    KnowledgeChunkFailures,
    DOCUMENT_STATUS_UPLOADED,
    DOCUMENT_STATUS_PARSING,
    DOCUMENT_STATUS_CHUNKING,
    DOCUMENT_STATUS_READY,
    DOCUMENT_STATUS_FAILED,
    KNOWLEDGE_CHUNK_ROLE_PARENT,
    KNOWLEDGE_CHUNK_ROLE_LEAF, KnowledgeChunks, DOCUMENT_STATUS_PARSED, DOCUMENT_STATUS_CHUNKED,
    DOCUMENT_STATUS_EMBEDDING, DOCUMENT_STATUS_INDEXING,
)
router = APIRouter()


def sync_user_faiss_index(db: Session, *, user_id: int) -> None:
    try:
        rebuild_user_faiss_index(db, user_id=user_id)
    except Exception:
        # RAG can still fall back to brute-force retrieval if the index sync fails.
        return

# 这里把“允许上传的类型”与“后端实际支持解析的类型”对齐。
# 好处是接口行为更一致，避免前端能传、后端却解析失败的尴尬情况。
ALLOWED_FILE_TYPES = {"txt", "md", "pdf", "docx", "xlsx", "xls", "pptx"}

# 确保上传目录存在
def ensure_upload_dir() -> Path:
    upload_dir = Path(settings.KNOWLEDGE_UPLOAD_DIR)
    # parents=True：如果父目录也不存在，一起创建（比如 ./a/b/c，如果 a 和 b 都不存在，会全部创建）
    #
    # exist_ok=True：如果目录已经存在，不报错，直接忽略
    upload_dir.mkdir(parents=True, exist_ok=True)
    return upload_dir

# 获取文件属性
def get_file_type(filename: str) -> str:
    """
    从文件名中提取文件类型（扩展名），统一转为小写。

    这是上传文件后的第一个处理步骤，用于判断文件是否在允许上传的类型列表中。

    处理流程（以 "README.TXT" 为例）：
    ┌──────────────────────────────────────────────────────┐
    │ 1. Path("README.TXT")       → Path 对象               │
    │ 2. .suffix                    → ".TXT"（含点号）       │
    │ 3. .lower()                   → ".txt"（全小写）       │
    │ 4. .lstrip(".")               → "txt"（去掉开头的点）  │
    └──────────────────────────────────────────────────────┘

    Args:
        filename: 原始文件名，如 "report.PDF"、"data.XLSX"、"notes.md"

    Returns:
        纯小写且不含点号的扩展名，如 "pdf"、"xlsx"、"md"

    边界情况：
        - 无扩展名文件（如 "Makefile"）→ suffix 为空字符串 → 返回 ""
        - 多重点号（如 "archive.tar.gz"）→ suffix 只取最后一个 ".gz"
        - 以点号开头（如 ".gitignore"）→ suffix 为空字符串 → 返回 ""
    """
    # Path(filename): 创建 Path 对象，python 内置的跨平台路径处理类
    # .suffix: 获取文件扩展名（含点号），如 ".txt"、".PDF"
    # .lower(): 转为小写，统一大小写差异（如 ".PDF" → ".pdf"）
    # .lstrip("."): 去掉开头的点号，得到纯净的扩展名（如 ".pdf" → "pdf"）
    suffix = Path(filename).suffix.lower().lstrip(".")
    return suffix




def _enrich_doc_with_progress(doc: KnowledgeDocuments) -> dict:
    """
    ★ 进度条计算函数 ★（把 DB 对象 → 前端可直接渲染的 dict，核心是 import_progress_percent）

    ════════════════════════════════════════════════════════════════
    进度分配（为啥这么拆？按各阶段实际耗时占比，embedding 占 60% 是合理的）：

      Phase 权重  起点    终点     状态
      ──────┬─────┬───────┬───────┬─────────────────────────────
       上传  │  5% │   5%  │   5%  │ uploaded
       解析  │  5% │   5%  │  10%  │ parsing → parse_failed 停在 10%
       分块  │ 20% │  10%  │  30%  │ chunking → chunk_failed 停在 25%
    ★ embedding │ 60% │  30%  │  90%  │ embedding（用 processed/total 线性插值）
       索引  │  5% │  90%  │  95%  │ indexing
       完成  │  5% │  95%  │ 100%  │ ready

    注意：embedding 占 60% 权重是因为它是最耗时的一步（要调 N 次 API + 每次都有 RTT），
         也是唯一能拿到"processed/total"精确计数的阶段，所以进度条在这一段是最丝滑的。

    例（100 个 chunk，embedding 阶段成功了 72 个）：
        processed_chunks = 72, total_chunks = 100
        → pct = 30.0 + (72/100) * 60.0 = 30 + 43.2 = 73.2%
        → 前端进度条显示 73% ✓
    """
    data = KnowledgeDocumentImportTaskResponse.model_validate(doc).model_dump()
    total = max(1, doc.total_chunks or 0)

    # ---- 1. 正常分支 ----
    if doc.status in {DOCUMENT_STATUS_UPLOADED, DOCUMENT_STATUS_PARSING,
                      DOCUMENT_STATUS_PARSED, DOCUMENT_STATUS_CHUNKING}:
        # uploaded → parsing → parsed → chunking 这几步都没精确进度，统一展示 5%
        # （如果卡住超过 20s 还是 5%，前端可以根据 updated_at 没变化来判断"疑似卡住"）
        data["import_progress_percent"] = 5.0
    elif doc.status == DOCUMENT_STATUS_CHUNKED:
        # chunk 分完了 → 相当于 30% 完成
        data["import_progress_percent"] = 30.0
    elif doc.status == DOCUMENT_STATUS_EMBEDDING:
        # ★ 丝滑进度条的核心：30% + 60% * (已完成 / 总数)，保留 1 位小数
        pct = 30.0 + min(60.0, (doc.processed_chunks / total) * 60.0) if total else 30.0
        data["import_progress_percent"] = round(pct, 1)
    elif doc.status == DOCUMENT_STATUS_INDEXING:
        # FAISS 写入磁盘一般很快（< 1s），用固定 95% 占位
        data["import_progress_percent"] = 95.0
    elif doc.status == DOCUMENT_STATUS_READY:
        data["import_progress_percent"] = 100.0

    # ---- 2. 失败分支：进度条停在对应阶段的中间点，前端可以红色高亮 ----
    else:
        if doc.status == "parse_failed":
            # 解析阶段大概占 5%，所以失败后停在 10% 附近
            data["import_progress_percent"] = 10.0
        elif doc.status == "chunk_failed":
            # 分块阶段占 20%，中间点大约 25%
            data["import_progress_percent"] = 25.0
        elif doc.status == "embed_failed":
            # embedding 失败 → 用当时的 processed_chunks 展示（和 embedding 阶段同一套插值）
            # 例：100 个只跑成功 40 个 → 30 + 40%*60 = 54% 处红条停止
            pct = 30.0 + min(60.0, (doc.processed_chunks / total) * 60.0) if total else 30.0
            data["import_progress_percent"] = round(pct, 1)
        else:
            # 兜底（老版本的 failed 状态）→ 不猜进度，给 None，前端显示"未知"
            data["import_progress_percent"] = None
    return data


@router.post("/upload", response_model=dict)
async def upload_file(
    background_tasks: BackgroundTasks,
    file: UploadFile = File(...),
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """
    异步上传（缺口6改造）：
      1. 接收文件 → 校验扩展名 → 落盘
      2. 立刻计算 MD5 → 如果同用户已有相同 MD5 且 status=ready，直接返回旧文档（is_duplicate_hit=true）
      3. 否则 INSERT knowledge_documents (status=uploaded)
      4. 把真正耗时的「解析→分块→embedding→重建FAISS」丢进 BackgroundTasks
         （FastAPI 会等 HTTP 响应发出去再慢慢跑）
      5. 立刻 HTTP 200 返回 document_id + status=uploaded
         前端轮询 GET /api/knowledge/{id}/status 直到 status == ready / *_failed / failed

    前端体验变化：
      - 以前：上传 50MB PDF → 转圈 45 秒 + 偶尔超时
      - 现在：1 秒内返回 document_id + 进度条百分比，用户可以切页面做别的
    """
    if not file.filename:
        raise HTTPException(status_code=400, detail="Filename is required")

    file_type = get_file_type(file.filename)
    if file_type not in ALLOWED_FILE_TYPES:
        raise HTTPException(status_code=400, detail="Invalid file type")

    upload_dir = ensure_upload_dir()
    stored_name = f"{uuid.uuid4().hex}.{file_type}"
    stored_path = upload_dir / stored_name
    content = await file.read()
    stored_path.write_bytes(content)

    # 阶段A：先算 MD5，做去重（避免相同文件重复解析/embedding 浪费钱）
    file_md5 = calc_file_md5(file_bytes=content)
    file_size = len(content)
    dup = find_duplicate_document(db, user_id=user.id, file_md5=file_md5)
    if dup is not None:
        resp = _enrich_doc_with_progress(dup)
        resp["is_duplicate_hit"] = True
        resp["duplicate_of_document_id"] = dup.id
        resp["error_message"] = f"检测到重复文件，命中已有文档 #{dup.id}，跳过重复导入"
        return {"data": resp}

    # 阶段B：写 DB 行（status=uploaded），立刻返回
    document = KnowledgeDocuments(
        user_id=user.id,
        name=file.filename,
        file_path=str(stored_path),
        file_type=file_type,
        status=DOCUMENT_STATUS_UPLOADED,
        file_md5=file_md5,
        file_size_bytes=file_size,
    )
    db.add(document)
    db.commit()
    db.refresh(document)

    # 阶段C：把耗时工作加入后台（响应发送后才会执行）
    #   注意：这里用 copy()，因为 fastapi 在响应发送后可能释放 content 的引用
    background_tasks.add_task(
        run_document_import_pipeline,
        document_id=document.id,
        user_id=user.id,
        stored_path=str(stored_path),
        file_type=file_type,
        file_name=file.filename,
        raw_content_bytes=content,  # 内容已经有了，避免 Worker 再读一次文件
    )

    return {"data": _enrich_doc_with_progress(document)}


@router.get("/{document_id}/status", response_model=dict)
def get_document_import_status(
    document_id: int,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """
    前端每 1 秒轮询一次这个接口，获取异步导入进度。

    返回示例（正在 embedding 阶段）:
    {
      "data": {
        "id": 42,
        "status": "embedding",
        "total_chunks": 100,
        "processed_chunks": 72,
        "failed_chunks": 0,
        "import_progress_percent": 73.2
      },
      "failed_chunk_rows": [
        // 如果有失败会把 KnowledgeChunkFailures 列出来，前端可展示"第73个chunk embedding失败"
        {"id": 9, "chunk_index_ref": 73, "step_name": "embedding_api",
         "retry_count": 3, "error_message": "..."}
      ]
    }
    """
    doc = db.query(KnowledgeDocuments).filter(
        KnowledgeDocuments.id == document_id,
        KnowledgeDocuments.user_id == user.id,
    ).first()
    if not doc:
        raise HTTPException(status_code=404, detail="Document not found")

    failed_rows = (
        db.query(KnowledgeChunkFailures)
        .filter(KnowledgeChunkFailures.document_id == document_id)
        .order_by(KnowledgeChunkFailures.created_at.asc())
        .all()
    )
    failed_json = [
        {
            "id": f.id, "chunk_id": f.chunk_id, "chunk_index_ref": f.chunk_index_ref,
            "step_name": f.step_name, "status": f.status,
            "retry_count": f.retry_count,
            "error_type": f.error_type, "error_message": f.error_message[:300],
            "retrieval_content_preview": f.retrieval_content_preview[:120],
            "created_at": f.created_at.isoformat(),
            "last_retry_at": f.last_retry_at.isoformat() if f.last_retry_at else None,
        }
        for f in failed_rows
    ]

    return {
        "data": _enrich_doc_with_progress(doc),
        "failed_chunk_rows": failed_json,
    }


@router.get("/list")
def list_documents(
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    documents = (
        db.query(KnowledgeDocuments)
        .filter(KnowledgeDocuments.user_id == user.id)
        .order_by(KnowledgeDocuments.created_at.desc())
        .all()
    )
    return {"data": [KnowledgeDocumentResponse.model_validate(doc) for doc in documents]}

@router.get("/{document_id}")
def get_document_detail(
    document_id: int,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    document = (
        db.query(KnowledgeDocuments)
        .filter(KnowledgeDocuments.id == document_id, KnowledgeDocuments.user_id == user.id)
        .first()
    )
    if not document:
        raise HTTPException(status_code=404, detail="Document not found")

    chunks = (
        db.query(KnowledgeChunks)
        .filter(KnowledgeChunks.document_id == document.id, KnowledgeChunks.user_id == user.id)
        .order_by(KnowledgeChunks.chunk_index.asc())
        .all()
    )

    data = KnowledgeDocumentDetailResponse(
        **KnowledgeDocumentResponse.model_validate(document).model_dump(),
        chunks=[KnowledgeChunkResponse.model_validate(item) for item in chunks],
    )

    return {"data": data}

@router.delete("/{document_id}")
def delete_document(
    document_id: int,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    document = (
        db.query(KnowledgeDocuments)
        .filter(KnowledgeDocuments.id == document_id, KnowledgeDocuments.user_id == user.id)
        .first()
    )
    if not document:
        raise HTTPException(status_code=404, detail="Document not found")
    payload = KnowledgeDocumentResponse.model_validate(document)

    if document.file_path and os.path.exists(document.file_path):
        os.remove(document.file_path)

    db.delete(document)
    db.commit()
    sync_user_faiss_index(db, user_id=user.id)
    return {"data": payload}