import os
import uuid
from pathlib import Path
from fastapi import APIRouter, File, Depends, UploadFile, HTTPException
from sqlalchemy.orm import Session

from api.deps import get_db, get_current_user
from api.schemas.knowledge import KnowledgeDocumentResponse, KnowledgeDocumentDetailResponse, KnowledgeChunkResponse
from core.config import settings
from core.db.models import User, KnowledgeDocuments, DOCUMENT_STATUS_UPLOADED, DOCUMENT_STATUS_PARSING, \
    DOCUMENT_STATUS_CHUNKING, DOCUMENT_STATUS_READY, DOCUMENT_STATUS_FAILED, KnowledgeChunks
from core.service.chunking import chunk_text
from core.service.document_parser import parse_document

router = APIRouter()

ALLOWED_FILE_TYPES = {"txt", "pdf", "docx", "xlsx", "xls", "pptx", "ppt"}

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
    # ：创建一个 Path 对象，用 filename 作为参数传入构造函数。
    # # 字符串类
    # str(123)        # 创建字符串对象 "123"
    # list([1,2,3])   # 创建列表对象 [1,2,3]
    # dict(a=1)       # 创建字典对象 {"a": 1}
    #
    # # Path 也一样
    # Path("readme.txt")  # 创建 Path 对象，代表 "readme.txt" 这个路径
    suffix = Path(filename).suffix.lower().lstrip(".")
    return suffix




@router.post("/upload")
#  是固定写法，上传文件： file: UploadFile = File(...)
# UploadFile 提供:
# - file.read()  读取内容
# - file.write() 写入
# - file.filename 文件名
# - file.content_type MIME类型
# - file.size 文件大小
async def upload_file( file: UploadFile  = File(...),
                      db: Session = Depends(get_db),
                      user: User = Depends(get_current_user),):

    if not file.filename:
        raise HTTPException(status_code=400, detail="Filename is required")

    file_type = get_file_type(file.filename)
    if file_type not in ALLOWED_FILE_TYPES:
        raise HTTPException(status_code=400, detail="Invalid file type")

    # 保存文件到指定目录
    upload_dir = ensure_upload_dir()
    stored_name = f"{uuid.uuid4().hex}.{file_type}"
    stored_path = upload_dir / stored_name

    # 写入文件内容
    content = await file.read()
    stored_path.write_bytes(content)

    document = KnowledgeDocuments(
        user_id=user.id,
        name=file.filename,
        file_path=str(stored_path),
        file_type=file_type,
        status=DOCUMENT_STATUS_UPLOADED,
    )
    db.add(document)
    db.commit()
    db.refresh(document)

    try:
        document.status = DOCUMENT_STATUS_PARSING
        db.commit()
        # 简单说：第 85 行把文件"读出来"，第 86 行把"读出来的正文"拿出来，准备后续做文本切分（chunking）和向量化。
        parsed = parse_document(str(stored_path), file_type=file_type)
        full_text = parsed["full_text"]

        document.content_text = full_text
        document.error_message = ""
        document.status = DOCUMENT_STATUS_CHUNKING
        db.commit()
        chunks = chunk_text(
        full_text,
        chunk_size=settings.RAG_CHUNK_SIZE,
        overlap=settings.RAG_CHUNK_OVERLAP,
             )

        for item in chunks:
             db.add(
                KnowledgeChunks(
                document_id=document.id,
                user_id=user.id,
                chunk_index=item["chunk_index"],
                content=item["content"],
                start_offset=item["start_offset"],
                end_offset=item["end_offset"],
                source_page=item["source_page"],
                source_section=item["source_section"],
                )
         )

        document.chunk_count = len(chunks)
        document.status = DOCUMENT_STATUS_READY
        db.commit()
        db.refresh(document)

    except Exception as exc:
        db.rollback()

        failed_doc = (
            db.query(KnowledgeDocuments)
            .filter(KnowledgeDocuments.id == document.id, KnowledgeDocuments.user_id == user.id)
            .first()
        )
        if failed_doc:
            failed_doc.status = DOCUMENT_STATUS_FAILED
            failed_doc.error_message = str(exc)
            db.commit()
            db.refresh(failed_doc)
            document = failed_doc

    return {"data": KnowledgeDocumentResponse.model_validate(document)}



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
    return {"data": payload}