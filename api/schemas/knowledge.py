from datetime import datetime

from pydantic import BaseModel, ConfigDict


class KnowledgeDocumentResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    user_id: int
    name: str
    file_path: str
    file_type: str
    status: str
    content_text: str
    error_message: str
    chunk_count: int
    created_at: datetime
    updated_at: datetime


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