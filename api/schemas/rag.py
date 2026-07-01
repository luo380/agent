from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field


class RagAskRequest(BaseModel):
    session_id: int
    question: str = Field(min_length=1, max_length=20000)
    top_k: int = Field(default=5, ge=1, le=20)
    document_ids: list[int] = Field(default_factory=list)
    strict_mode: bool = Field(default=True)


class RagCitationResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    document_id: int
    document_name: str
    chunk_id: int
    chunk_index: int
    source_page: int | None
    source_section: str
    score: float
    content: str


class RagRetrievedChunkResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    document_id: int
    document_name: str
    chunk_id: int
    chunk_index: int
    source_page: int | None
    source_section: str
    content: str
    vector_score: float
    keyword_score: float
    final_score: float


class RagAskResponse(BaseModel):
    question: str
    answer: str
    run_id: int
    strict_mode: bool
    citations: list[RagCitationResponse]
    retrieved_chunks: list[RagRetrievedChunkResponse]