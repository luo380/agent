import json
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
from core.service.langchain_adapters import ProjectDocumentLoader, ProjectEmbeddings, ProjectTextSplitter
router = APIRouter()

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
        # 标记文档状态为"正在解析"，前端可根据此状态显示处理进度
        document.status = DOCUMENT_STATUS_PARSING
        db.commit()

        # ========== 第一步：解析文档 ==========
        # parse_document 根据文件类型（pdf/docx/pptx/xlsx 等）选择不同的解析器，
        # 返回结构化的解析结果，典型结构：
        #   {
        #       "full_text": "完整的纯文本内容",
        #       "pages":    [{"page": 1, "text": "第1页内容"}, ...],  // PDF/PPTX 有值
        #       "sections": [{"section": "章节名", "text": "章节内容"}, ...]  // DOCX/Markdown 有值
        #   }
        # 这样后面切块时就能知道每个 chunk 来自第几页/哪个章节
        # ========== 第一步：LangChain Loader 负责把原始文件转成 Document ==========
        # 这里不再直接在路由里手写 parse_document(...)，而是交给 ProjectDocumentLoader。
        # 这样“文档读取/解析”就对应上了 LangChain 的 Document Loader 抽象。
        loader = ProjectDocumentLoader(
            str(stored_path),
            file_type=file_type,
            metadata={
                "document_id": document.id,
                "document_name": file.filename,
            },
        )
        loaded_documents = list(loader.lazy_load())
        if not loaded_documents:
            raise RuntimeError("Loader did not produce any document")

        source_document = loaded_documents[0]
        parsed = source_document.metadata.get("parsed_document") or {
            "full_text": source_document.page_content,
            "pages": [],
            "sections": [],
            "metadata": {},
        }
        full_text = source_document.page_content or ""

        # 把完整文本先落库，方便后面做全文预览和问题排查。
        document.content_text = full_text
        document.error_message = ""

        # 进入切块阶段。
        document.status = DOCUMENT_STATUS_CHUNKING
        db.commit()

        # ========== 第二步：LangChain TextSplitter 负责把 Document 切成多个 chunk ==========
        # 这里走的是 ProjectTextSplitter，它底层仍然复用你第 4 阶段的 chunk_parsed_document(...)。
        # 区别只是：现在对外暴露成了 LangChain TextSplitter 接口。
        splitter = ProjectTextSplitter(
            chunk_size=settings.RAG_CHUNK_SIZE,
            chunk_overlap=settings.RAG_CHUNK_OVERLAP,
        )
        chunk_documents = splitter.split_documents(loaded_documents)

        # ========== 第三步：LangChain Embeddings 负责给 chunk 生成向量 ==========
        # 这里走的是 ProjectEmbeddings，它底层仍然复用你自己的 embed_texts(...)。
        embeddings_service = ProjectEmbeddings()
        embeddings = await embeddings_service.aembed_documents(
            [item.page_content for item in chunk_documents]
        )

        if len(embeddings) != len(chunk_documents):
            raise RuntimeError("Embedding result count does not match chunk count")

        # ========== 第四步：把 LangChain chunk Document + embedding 一起写回知识库 ==========
        # 这一段相当于把 LangChain 的标准对象，再映射回你项目自己的 KnowledgeChunks 数据表。
        for chunk_document, embedding in zip(chunk_documents, embeddings):
            metadata = chunk_document.metadata or {}
            db.add(
                KnowledgeChunks(
                    document_id=document.id,
                    user_id=user.id,
                    chunk_index=int(metadata.get("chunk_index", 0) or 0),
                    content=chunk_document.page_content,
                    start_offset=metadata.get("start_offset"),
                    end_offset=metadata.get("end_offset"),
                    source_page=metadata.get("source_page"),
                    source_section=metadata.get("source_section") or "",
                    embedding_json=json.dumps(embedding, ensure_ascii=False),
                )
            )
        document.chunk_count = len(chunk_documents)
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
