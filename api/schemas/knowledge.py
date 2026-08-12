from datetime import datetime

from pydantic import BaseModel, ConfigDict


class KnowledgeDocumentResponse(BaseModel):
    """
    文档列表 / 文档详情通用响应。
    缺口6新增 8 个工程化字段（底部 8 行）：
      ● 去重相关：file_md5 / is_duplicate_hit / duplicate_of_document_id
      ● 进度相关：file_size_bytes / total_chunks / processed_chunks / failed_chunks
      ● 计算字段：import_progress_percent（由后端 _enrich_doc_with_progress 计算）
    """
    model_config = ConfigDict(from_attributes=True)

    id: int
    user_id: int
    name: str
    file_path: str
    file_type: str
    # status 取值 12 种：uploaded/parsing/parsed/parse_failed/chunking/chunked/
    #                   chunk_failed/embedding/embed_failed/indexing/ready/failed
    status: str
    content_text: str
    error_message: str
    chunk_count: int  # 兼容旧字段，总 chunk 数推荐用新字段 total_chunks
    created_at: datetime
    updated_at: datetime

    # ---- 缺口6新增：MD5 去重 + 文件大小 ----
    file_md5: str = ""                # 内容 MD5（32 位小写十六进制）
    file_size_bytes: int = 0          # 原始文件字节数（= content_text 字节数的 2~20 倍）

    # ---- 缺口6新增：进度条三剑客 ----
    total_chunks: int = 0             # 总 chunk 数（chunked 阶段结束后确定）
    processed_chunks: int = 0         # 已完成 embedding 且写入 FAISS 的 chunk 数
    failed_chunks: int = 0            # 3 次降级重试仍失败的 chunk 数（>0 时前端给「重试失败chunk」）

    # ---- 缺口6新增：前端直接展示用的衍生字段（后端计算好直接返回）----
    import_progress_percent: float | None = None  # 0~100 浮点数，None 表示"未知（老文档没跑过新流水线）"
    is_duplicate_hit: bool = False                 # True=这次上传命中了同MD5旧文档，没真跑解析/embedding
    duplicate_of_document_id: int | None = None    # 命中的那条旧文档 id（方便前端跳转到已存在的页面）


class KnowledgeDocumentImportTaskResponse(BaseModel):
    """
    【异步上传立即返回】轻量响应体（特意排除了 content_text 这种几 MB 的大字段）

    典型场景（上传接口 POST /upload）：
        用户拖拽「2024年报.pdf」8.4 MB → 以前等 45 秒 HTTP 才返回，现在：
            1. 后端先算 MD5 + INSERT document
            2. 把耗时的 4 个阶段丢进 BackgroundTasks.add_task
            3. HTTP 立刻（<300ms）返回本 schema

        返回示例：
        {
          "data": {
            "id": 42,
            "name": "2024年报.pdf",
            "status": "uploaded",
            "file_size_bytes": 8421337,
            "import_progress_percent": 5.0,
            "total_chunks": 0,
            "is_duplicate_hit": false
          }
        }

    前端拿到后每 1 秒 GET /api/knowledge/42/status（也是返回这个 schema），
    直到 status ∈ {ready, parse_failed, chunk_failed, embed_failed, failed} 停止轮询。
    """
    model_config = ConfigDict(from_attributes=True)

    id: int
    user_id: int
    name: str
    file_type: str
    status: str
    error_message: str = ""
    chunk_count: int = 0
    created_at: datetime
    updated_at: datetime

    # 进度条相关字段（和 KnowledgeDocumentResponse 保持对齐）
    file_size_bytes: int = 0
    total_chunks: int = 0
    processed_chunks: int = 0
    failed_chunks: int = 0
    import_progress_percent: float | None = None

    # MD5 去重命中标志
    is_duplicate_hit: bool = False
    duplicate_of_document_id: int | None = None


class KnowledgeChunkResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    document_id: int
    user_id: int
    chunk_index: int
    chunk_role: str
    parent_chunk_id: int | None
    parent_title: str
    block_type: str
    child_index: int
    table_row_from: int | None
    table_row_to: int | None
    content: str
    retrieval_content: str
    start_offset: int
    end_offset: int
    source_page: int | None
    source_section: str
    created_at: datetime


class KnowledgeDocumentDetailResponse(KnowledgeDocumentResponse):
    chunks: list[KnowledgeChunkResponse]