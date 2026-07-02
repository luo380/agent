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
from core.service.chunking import chunk_parsed_document
from core.service.document_parser import parse_document
from core.service.embedding import embed_texts
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
        parsed = parse_document(str(stored_path), file_type=file_type)

        # 从解析结果中提取"纯文本全文"，用于：
        #   1. 存入数据库 document.content_text 字段（方便全文预览或后续再处理）
        #   2. 如果没有 pages/sections 结构时，退化为整篇文本切块
        full_text = parsed["full_text"]

        # 将全文写入数据库，并清空错误信息（本次尝试是成功路径）
        document.content_text = full_text
        document.error_message = ""

        # 标记文档状态为"正在切块"，然后提交数据库
        document.status = DOCUMENT_STATUS_CHUNKING
        db.commit()

        # ========== 第二步：文本切块（Chunking）==========
        # 这里不再直接对 full_text 做"盲切"，而是优先使用 parse_document 返回的
        # 结构化信息（pages / sections）来切块。这样切出来的 chunk 会尽量保留：
        #   - PDF / PPTX 的页码（source_page）
        #   - DOCX 的章节名（source_section）
        #   - Excel 的工作表名（source_section）
        #
        # 最终效果：后面的检索结果和引用信息会更像"来自第X页/来自XX章节"
        #         而不是笼统的"来自某个文档"
        chunks = chunk_parsed_document(
            parsed,
            chunk_size=settings.RAG_CHUNK_SIZE,  # 每个 chunk 的最大字符数（来自配置）
            overlap=settings.RAG_CHUNK_OVERLAP,  # 相邻 chunk 的重叠字符数（来自配置）
        )

        # ========== 第三步：生成向量（Embedding）==========
        # 把所有 chunk 的文本批量调用 embedding 模型，生成对应的向量（embedding）
        # 列表推导式 [item["content"] for item in chunks] 取出每个 chunk 的纯文本组成一个字符串列表
        # await 用于等待一个异步函数（async def 定义的函数）执行完成
        embeddings = await embed_texts([item["content"] for item in chunks])

        # 安全检查：chunk 的数量必须与返回的 embedding 数量一一对应，
        # 否则说明 embedding 服务出错或丢包，直接抛出异常走回滚逻辑
        if len(embeddings) != len(chunks):
            raise RuntimeError("Embedding result count does not match chunk count")

        # 按位置一一对应遍历每一对 (chunk, embedding)，逐条写入知识库 chunk 表
        # zip 会按最短序列长度停止，配合上面的长度检查可以保证不会有遗漏或错位
        # zip() 将两个或多个可迭代对象"压缩"在一起，按位置配对：
        """chunks = [A, B, C]      # 索引0, 1, 2
            embeddings = [X, Y, Z]  # 索引0, 1, 2
            zip(chunks, embeddings) 
            # 生成: [(A, X), (B, Y), (C, Z)]"""
        for item, embedding in zip(chunks, embeddings):
            db.add(
                KnowledgeChunks(
                    document_id=document.id,                  # 外键：关联所属文档
                    user_id=user.id,                          # 用户 ID，做多租户数据隔离
                    chunk_index=item["chunk_index"],          # 该 chunk 在文档中的序号（0, 1, 2...）
                    content=item["content"],                  # chunk 的原始文本，后续用于检索后展示给用户
                    start_offset=item["start_offset"],        # 在 full_text 中的起始字符位置（用于在原文中定位
                    end_offset=item["end_offset"],            # 在 full_text 中的结束字符位置
                    source_page=item["source_page"],          # 来源页码（解析器如果支持结构化解析会提供
                    source_section=item["source_section"],    # 来源章节名（同上
                    # embedding 是一个浮点数列表，序列化为 JSON 字符串存进数据库 TEXT 字段；
                    # ensure_ascii=False 保留中文原文不被转义成 \uXXXX，减小存储体积并方便查看
                    embedding_json=json.dumps(embedding, ensure_ascii=False),
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
