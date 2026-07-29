import json
import os
import uuid
from pathlib import Path
from fastapi import APIRouter, File, Depends, UploadFile, HTTPException
from sqlalchemy.orm import Session

from api.deps import get_db, get_current_user
from api.schemas.knowledge import KnowledgeDocumentResponse, KnowledgeDocumentDetailResponse, KnowledgeChunkResponse
from core.config import settings
from core.service.vector_index import rebuild_user_faiss_index

from core.db.models import (
    User,
    KnowledgeDocuments,
    DOCUMENT_STATUS_UPLOADED,
    DOCUMENT_STATUS_PARSING,
    DOCUMENT_STATUS_CHUNKING,
    DOCUMENT_STATUS_READY,
    DOCUMENT_STATUS_FAILED,
    KnowledgeChunks,
    KNOWLEDGE_CHUNK_ROLE_PARENT,
    KNOWLEDGE_CHUNK_ROLE_LEAF,
)
from core.service.hierarchical_chunking import build_hierarchical_chunks
from core.service.langchain_adapters import ProjectDocumentLoader, ProjectEmbeddings
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




@router.post("/upload")
async def upload_file(
    file: UploadFile = File(...),
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """
    上传文件 → 解析 → 分块 → 向量化 → 入库 → 重建索引，一个接口走完。

    这是知识库最核心的上传接口，完整链路如下：

    ┌──────────────────────────────────────────────────────────────────┐
    │ 阶段1: 文件校验                                                    │
    │  - 文件名非空检查                                                  │
    │  - 扩展名白名单校验（txt, md, pdf, docx, xlsx, xls, pptx）         │
    └──────────────────────┬───────────────────────────────────────────┘
                           │
                           ▼
    ┌──────────────────────────────────────────────────────────────────┐
    │ 阶段2: 文件落盘                                                    │
    │  - 生成唯一文件名: {uuid}.{ext}，如 "a1b2c3d4.pdf"                 │
    │  - 写入 upload_dir 目录                                           │
    └──────────────────────┬───────────────────────────────────────────┘
                           │
                           ▼
    ┌──────────────────────────────────────────────────────────────────┐
    │ 阶段3: 创建数据库记录（status = uploaded）                          │
    └──────────────────────┬───────────────────────────────────────────┘
                           │
                           ▼
    ┌──────────────────────────────────────────────────────────────────┐
    │ 阶段4: 文档解析（status → parsing）                                │
    │  - ProjectDocumentLoader 统一解析不同格式                          │
    │  - 产出: full_text + pages/sections 结构化数据                     │
    └──────────────────────┬───────────────────────────────────────────┘
                           │
                           ▼
    ┌──────────────────────────────────────────────────────────────────┐
    │ 阶段5: 分层分块（status → chunking）                               │
    │  - build_hierarchical_chunks() 生成 parent + leaf 两层            │
    │  - parent: 大上下文块，供 small-to-big 展开                       │
    │  - leaf:   小召回块，供向量检索                                    │
    └──────────────────────┬───────────────────────────────────────────┘
                           │
                           ▼
    ┌──────────────────────────────────────────────────────────────────┐
    │ 阶段6: 向量化（Embedding）                                         │
    │  - 只对 leaf chunk 的 retrieval_content 做 embedding               │
    │  - retrieval_content 已注入父级主题前缀，检索效果更好               │
    └──────────────────────┬───────────────────────────────────────────┘
                           │
                           ▼
    ┌──────────────────────────────────────────────────────────────────┐
    │ 阶段7: 入库                                                        │
    │  - 先插入 parent chunk（db.flush 获取真实 ID）                     │
    │  - 再插入 leaf chunk（parent_chunk_id 关联到 parent）              │
    │  - 更新 document.chunk_count 和 status = ready                    │
    └──────────────────────┬───────────────────────────────────────────┘
                           │
                           ▼
    ┌──────────────────────────────────────────────────────────────────┐
    │ 阶段8: 重建 FAISS 索引                                             │
    │  - sync_user_faiss_index() 将该用户所有 leaf chunk 写入索引        │
    │  - 索引失败不影响上传成功（幂等操作，下次检索时会回退到暴力检索）    │
    └──────────────────────┬───────────────────────────────────────────┘
                           │
                           ▼
    ┌──────────────────────────────────────────────────────────────────┐
    │ 阶段9: 返回结果                                                    │
    │  - 成功: status=ready, 含 chunk_count                             │
    │  - 失败: status=failed, 含 error_message                          │
    └──────────────────────────────────────────────────────────────────┘

    ────────────────────────────────────────────────────────────────────
    示例场景：
    ────────────────────────────────────────────────────────────────────

    【场景1：上传一个 PDF 文件】
    请求:
        POST /api/knowledge/upload
        Content-Type: multipart/form-data
        file: "年度报告.pdf" (二进制内容)

    响应（成功）:
        {
            "data": {
                "id": 42,
                "name": "年度报告.pdf",
                "file_type": "pdf",
                "status": "ready",
                "chunk_count": 35,
                "error_message": ""
            }
        }

    数据库变化:
        knowledge_documents 表新增 1 条记录（status=ready）
        knowledge_chunks 表新增 35 条记录（1 parent + 34 leaf）
        磁盘新增: uploads/a1b2c3d4.pdf, faiss/user_1.faiss, faiss/user_1.json

    【场景2：上传不支持的文件类型】
    请求:
        POST /api/knowledge/upload
        file: "image.png"

    响应（失败）:
        HTTP 400
        {"detail": "Invalid file type"}

    【场景3：文件解析失败】
    请求:
        POST /api/knowledge/upload
        file: "corrupted.pdf"  (内容损坏的 PDF)

    响应（失败）:
        {
            "data": {
                "id": 43,
                "name": "corrupted.pdf",
                "status": "failed",
                "chunk_count": 0,
                "error_message": "Loader did not produce any document"
            }
        }
        # 注意：返回 HTTP 200，但 status=failed，前端通过 status 字段判断成功与否

    ────────────────────────────────────────────────────────────────────
    设计决策说明：
    ────────────────────────────────────────────────────────────────────
    1. 为什么先插入 parent，flush 后再插入 leaf？
       leaf 需要 parent_chunk_id 外键，在 parent 真正入库前拿不到这个 ID。
       flush() 将 SQL 发送到数据库但不提交事务，此时就能拿到 parent.id，
       而万一后续步骤失败，整个事务回滚（rollback），不会产生孤立数据。

    2. 为什么只对 leaf 做 embedding，parent 不做？
       parent 是"大上下文块"，在 small-to-big 检索策略中只用于展开上下文，
       不参与向量检索。把 parent 也做 embedding 会浪费 GPU/API 调用成本，
       且检索结果会冗余。

    3. 为什么 FAISS 索引重建失败不影响上传？
       sync_user_faiss_index 内部 try-catch 了异常，不会向外抛出。
       即使 FAISS 索引没建成功，检索时也可以回退到暴力全量计算（brute-force）。
       这是"优雅降级"的设计。

    4. 为什么失败时也返回 200 而不是 4xx/5xx？
       失败时 db 事务已回滚，但 document 记录被更新为 status=failed 并保留。
       用户可以在列表中看到这个失败记录，便于排查问题。
       返回 200 + status=failed 让前端逻辑更统一（统一处理 data.status 字段）。
    """
    # ========== 阶段1: 文件校验 ==========
    if not file.filename:
        raise HTTPException(status_code=400, detail="Filename is required")

    # 提取文件扩展名，检查是否在白名单中
    file_type = get_file_type(file.filename)
    if file_type not in ALLOWED_FILE_TYPES:
        raise HTTPException(status_code=400, detail="Invalid file type")

    # ========== 阶段2: 文件落盘 ==========
    upload_dir = ensure_upload_dir()
    # 生成唯一文件名: {32位uuid}.{原始扩展名}，避免文件名冲突
    # 例: "a1b2c3d4e5f6a7b8c9d0e1f2a3b4c5d6.pdf"
    stored_name = f"{uuid.uuid4().hex}.{file_type}"
    stored_path = upload_dir / stored_name

    # 读取文件内容并写入磁盘
    content = await file.read()
    stored_path.write_bytes(content)

    # ========== 阶段3: 创建数据库记录（status = uploaded） ==========
    document = KnowledgeDocuments(
        user_id=user.id,
        name=file.filename,              # 保留用户上传时的原始文件名
        file_path=str(stored_path),      # 磁盘上的实际存储路径
        file_type=file_type,
        status=DOCUMENT_STATUS_UPLOADED,  # 初始状态: 已上传，待解析
    )
    db.add(document)
    db.commit()
    db.refresh(document)  # 刷新获取自动生成的 id

    try:
        # ========== 阶段4: 文档解析（status → parsing） ==========
        document.status = DOCUMENT_STATUS_PARSING
        db.commit()

        # ProjectDocumentLoader 内部会根据 file_type 选择对应的解析器:
        #   pdf → PyPDFLoader
        #   docx → Docx2txtLoader
        #   xlsx/xls → Excel 解析器
        #   md/txt → 文本读取
        # 解析结果统一封装为 LangChain Document 对象
        loader = ProjectDocumentLoader(
            str(stored_path),
            file_type=file_type,
            metadata={
                "document_id": document.id,
                "document_name": file.filename,
            },
        )
        # lazy_load(): 惰性加载，逐页/逐段读取，避免大文件撑爆内存
        loaded_documents = list(loader.lazy_load())
        if not loaded_documents:
            raise RuntimeError("Loader did not produce any document")

        # 取第一个（也是唯一一个）解析结果
        source_document = loaded_documents[0]

        # 提取结构化解析数据:
        #   parsed_document: 包含 pages/sections 等结构化信息（PDF/Excel 等才有）
        #   page_content:   纯文本全文（兜底）
        parsed = source_document.metadata.get("parsed_document") or {
            "full_text": source_document.page_content,
            "pages": [],        # 按页的内容列表（PDF/PPTX）
            "sections": [],     # 按章节/工作表的内容列表（Excel/Word/Markdown）
            "metadata": {},     # 源文件元信息（作者、创建时间等）
        }
        full_text = source_document.page_content or ""

        # 保存全文到数据库（用于后续全文检索或展示）
        document.content_text = full_text
        document.error_message = ""

        # ========== 阶段5: 分层分块（status → chunking） ==========
        document.status = DOCUMENT_STATUS_CHUNKING
        db.commit()

        # build_hierarchical_chunks 产出 parent + leaf 两层 chunk:
        #   输出是一个扁平列表，结构如下:
        #   [
        #     {"chunk_role": "parent", "local_parent_key": "parent_0", ...},  # 父块0
        #     {"chunk_role": "leaf",   "local_parent_key": "parent_0", ...},  # 父块0的第1个子块
        #     {"chunk_role": "leaf",   "local_parent_key": "parent_0", ...},  # 父块0的第2个子块
        #     {"chunk_role": "parent", "local_parent_key": "parent_1", ...},  # 父块1
        #     {"chunk_role": "leaf",   "local_parent_key": "parent_1", ...},  # 父块1的第1个子块
        #     ...
        #   ]
        chunk_items = build_hierarchical_chunks(
            parsed,
            file_type=file_type,
            chunk_size=settings.RAG_CHUNK_SIZE,      # 默认 500 字符
            overlap=settings.RAG_CHUNK_OVERLAP,       # 默认 100 字符
        )

        if not chunk_items:
            raise RuntimeError("No chunk items produced")

        # 按角色分组: parent 和 leaf 分别处理
        parent_items = [item for item in chunk_items if item["chunk_role"] == KNOWLEDGE_CHUNK_ROLE_PARENT]
        leaf_items = [item for item in chunk_items if item["chunk_role"] == KNOWLEDGE_CHUNK_ROLE_LEAF]

        # ========== 阶段6: 向量化（只对 leaf chunk 做 embedding） ==========
        embeddings_service = ProjectEmbeddings()
        leaf_embeddings: list[list[float]] = []
        if leaf_items:
            # 对 leaf chunk 的 retrieval_content 做 embedding
            # retrieval_content 已包含 "[父级主题] xxx" 和 "[内容类型] 正文/表格" 前缀
            # 例: "[父级主题] 第二章 方法\n[内容类型] 正文\n本研究采用..."
            leaf_embeddings = await embeddings_service.aembed_documents(
                [item["retrieval_content"] for item in leaf_items]
            )

        # 向量数量必须和 leaf chunk 数量一致，否则说明 embedding 服务异常
        if len(leaf_embeddings) != len(leaf_items):
            raise RuntimeError("Embedding result count does not match leaf chunk count")

        # ========== 阶段7: 入库（先 parent，后 leaf） ==========

        # 7.1 先插入 parent chunk
        #     使用 db.flush() 而非 commit()，这样 parent.id 立即可用
        #     但万一后续失败，整个事务回滚，不会留下孤儿数据
        local_parent_id_map: dict[str, int] = {}  # local_parent_key → 数据库 id 的映射
        for item in parent_items:
            row = KnowledgeChunks(
                document_id=document.id,
                user_id=user.id,
                chunk_index=int(item["chunk_index"]),       # 全局序号，用于排序
                chunk_role=item["chunk_role"],              # "parent"
                parent_chunk_id=None,                        # parent 没有上级
                parent_title=item["parent_title"],           # 如 "第一章 引言"
                block_type=item["block_type"],               # "text" 或 "table"
                child_index=int(item["child_index"]),        # parent 固定为 0
                table_row_from=item["table_row_from"],       # 表格行号（仅 table 有值）
                table_row_to=item["table_row_to"],
                content=item["content"],                     # 父块的完整文本
                retrieval_content="",                        # parent 不参与检索，留空
                start_offset=int(item["start_offset"]),      # 在原文中的字符偏移
                end_offset=int(item["end_offset"]),
                source_page=item["source_page"],             # 来源页码（PDF 类才有）
                source_section=item["source_section"] or "", # 来源章节
                embedding_json="",                           # parent 不做 embedding
            )
            db.add(row)
            db.flush()  # 发送 SQL 但不提交，获取 row.id
            # 建立映射: "parent_0" → 1001, "parent_1" → 1002, ...
            local_parent_id_map[item["local_parent_key"]] = row.id

        # 7.2 再插入 leaf chunk，关联 parent_chunk_id
        for item, embedding in zip(leaf_items, leaf_embeddings):
            parent_chunk_id = local_parent_id_map.get(item["local_parent_key"])

            row = KnowledgeChunks(
                document_id=document.id,
                user_id=user.id,
                chunk_index=int(item["chunk_index"]),
                chunk_role=item["chunk_role"],              # "leaf"
                parent_chunk_id=parent_chunk_id,             # 指向父块的数据库 ID
                parent_title=item["parent_title"],
                block_type=item["block_type"],
                child_index=int(item["child_index"]),        # 该 leaf 在父块中的序号（从1开始）
                table_row_from=item["table_row_from"],
                table_row_to=item["table_row_to"],
                content=item["content"],                     # 叶子块的原始文本
                retrieval_content=item["retrieval_content"], # 增强检索文本（含父级主题前缀）
                start_offset=int(item["start_offset"]),
                end_offset=int(item["end_offset"]),
                source_page=item["source_page"],
                source_section=item["source_section"] or "",
                embedding_json=json.dumps(embedding, ensure_ascii=False),  # 向量存为 JSON 字符串
            )
            db.add(row)

        # 更新文档状态: 记录 chunk 总数，标记为 ready
        document.chunk_count = len(chunk_items)
        document.status = DOCUMENT_STATUS_READY
        db.commit()       # 事务提交，所有 parent + leaf 一次性入库
        db.refresh(document)

        # ========== 阶段8: 重建 FAISS 索引 ==========
        # 将该用户所有 leaf chunk 的向量写入 FAISS 索引文件
        # 失败不影响上传（sync_user_faiss_index 内部已 try-catch）
        sync_user_faiss_index(db, user_id=user.id)

    except Exception as exc:
        # ========== 异常处理: 回滚 + 标记失败 ==========
        db.rollback()  # 回滚所有未提交的 chunk 数据

        # 重新查询 document（因为 rollback 后之前的 document 对象可能已失效）
        failed_doc = (
            db.query(KnowledgeDocuments)
            .filter(KnowledgeDocuments.id == document.id, KnowledgeDocuments.user_id == user.id)
            .first()
        )
        if failed_doc:
            # 标记为失败，保留错误信息供用户排查
            failed_doc.status = DOCUMENT_STATUS_FAILED
            failed_doc.error_message = str(exc)
            db.commit()
            db.refresh(failed_doc)
            document = failed_doc

    # ========== 阶段9: 返回结果 ==========
    # 无论成功还是失败，都返回 document 对象
    # 前端通过 status 字段判断: "ready"=成功, "failed"=失败
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
    sync_user_faiss_index(db, user_id=user.id)
    return {"data": payload}