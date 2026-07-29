from datetime import datetime, timezone

from sqlalchemy import DateTime, Float, ForeignKey, Integer, String, Text
from sqlalchemy.dialects.mysql import LONGTEXT
from sqlalchemy.orm import Mapped, mapped_column

from core.db.base import Base

LongText = Text().with_variant(LONGTEXT(), 'mysql')
DEFAULT_SESSION_TITLE = '新对话'
MESSAGE_MODE_CHAT = "chat"
MESSAGE_MODE_RAG = "rag"
MESSAGE_SOURCE_CHAT_STREAM = "chat_stream"
MESSAGE_SOURCE_RAG_ASK = "rag_ask"
RUN_STATUS_RUNNING = "running"
RUN_STATUS_COMPLETED = "completed"
RUN_STATUS_FAILED = "failed"

STEP_STATUS_RUNNING = "running"
STEP_STATUS_COMPLETED = "completed"
STEP_STATUS_FAILED = "failed"


DOCUMENT_STATUS_UPLOADED = "uploaded"
DOCUMENT_STATUS_PARSING = "parsing"
DOCUMENT_STATUS_CHUNKING = "chunking"
DOCUMENT_STATUS_READY = "ready"
DOCUMENT_STATUS_FAILED = "failed"


RAG_RUN_STATUS_RUNNING = "running"
RAG_RUN_STATUS_COMPLETED = "completed"
RAG_RUN_STATUS_FAILED = "failed"

RAG_STEP_STATUS_RUNNING = "running"
RAG_STEP_STATUS_COMPLETED = "completed"
RAG_STEP_STATUS_FAILED = "failed"



KNOWLEDGE_CHUNK_ROLE_PARENT = "parent"
KNOWLEDGE_CHUNK_ROLE_LEAF = "leaf"
KNOWLEDGE_BLOCK_TYPE_TEXT = "text"
KNOWLEDGE_BLOCK_TYPE_TABLE = "table"



def now() -> datetime:
    return datetime.now(timezone.utc)


class User(Base):
    __tablename__ = 'users'

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    email: Mapped[str] = mapped_column(String(255), unique=True, index=True, nullable=False)
    name: Mapped[str] = mapped_column(String(100), nullable=False)
    password_hash: Mapped[str] = mapped_column(String(255), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now, nullable=False)


class Agent(Base):
    __tablename__ = 'agents'

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    name: Mapped[str] = mapped_column(String(160), nullable=False)
    system_prompt: Mapped[str] = mapped_column(Text, default='', nullable=False)
    welcome_message: Mapped[str] = mapped_column(Text, default='', nullable=False)
    model: Mapped[str] = mapped_column(String(120), nullable=False)
    temperature: Mapped[float] = mapped_column(Float, default=0.4, nullable=False)
    created_by: Mapped[int] = mapped_column(ForeignKey('users.id', ondelete='CASCADE'), index=True, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now, onupdate=now, nullable=False)


class ChatSession(Base):
    __tablename__ = 'sessions'

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    title: Mapped[str] = mapped_column(String(200), default=DEFAULT_SESSION_TITLE, nullable=False)
    user_id: Mapped[int] = mapped_column(ForeignKey('users.id', ondelete='CASCADE'), index=True, nullable=False)
    agent_id: Mapped[int] = mapped_column(ForeignKey('agents.id', ondelete='CASCADE'), index=True, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now, onupdate=now, nullable=False)


class Message(Base):
    __tablename__ = 'messages'

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    session_id: Mapped[int] = mapped_column(ForeignKey('sessions.id', ondelete='CASCADE'), index=True, nullable=False)
    role: Mapped[str] = mapped_column(String(20), nullable=False)
    content: Mapped[str] = mapped_column(Text, nullable=False)
    mode: Mapped[str] = mapped_column(String(20), default=MESSAGE_MODE_CHAT, nullable=False)
    source: Mapped[str] = mapped_column(String(50), default=MESSAGE_SOURCE_CHAT_STREAM, nullable=False)
    strict_mode: Mapped[int | None] = mapped_column(Integer, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now, nullable=False)


class Runs(Base):
    __tablename__ = 'runs'
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    session_id: Mapped[int] = mapped_column(ForeignKey('sessions.id', ondelete='CASCADE'), index=True, nullable=False)
    agent_id: Mapped[int] = mapped_column(ForeignKey('agents.id', ondelete='CASCADE'), index=True, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now, onupdate=now, nullable=False)
    status: Mapped[str] = mapped_column(String(20), nullable=False)
    input_text: Mapped[str] = mapped_column(Text, nullable=False)
    output_text: Mapped[str] = mapped_column(Text, default='', nullable=False)
    error_message: Mapped[str] = mapped_column(Text, default='', nullable=False)
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    finished_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=True)
    user_id: Mapped[int] = mapped_column(ForeignKey('users.id', ondelete='CASCADE'), index=True, nullable=False)


class RunSteps(Base):
    __tablename__ = 'run_steps'
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    run_id: Mapped[int] = mapped_column(ForeignKey('runs.id', ondelete='CASCADE'), index=True, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now, onupdate=now, nullable=False)
    status: Mapped[str] = mapped_column(String(20), nullable=False)
    step_type: Mapped[str] = mapped_column(String(20), nullable=False)
    step_name: Mapped[str] = mapped_column(String(20), nullable=False)
    input_payload: Mapped[str] = mapped_column(Text, nullable=False)
    output_payload: Mapped[str] = mapped_column(Text, default='', nullable=False)
    error_message: Mapped[str] = mapped_column(Text, default='', nullable=False)
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    finished_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=True)


class KnowledgeDocuments(Base):
    __tablename__ = "knowledge_documents"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    user_id: Mapped[int] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"),
        index=True,
        nullable=False,
    )
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    file_path: Mapped[str] = mapped_column(String(500), nullable=False)
    file_type: Mapped[str] = mapped_column(String(20), nullable=False)
    status: Mapped[str] = mapped_column(String(20), default=DOCUMENT_STATUS_UPLOADED, nullable=False)
    content_text: Mapped[str] = mapped_column(LongText, default="", nullable=False)
    error_message: Mapped[str] = mapped_column(Text, default="", nullable=False)
    chunk_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now, onupdate=now, nullable=False)


class KnowledgeChunks(Base):
    __tablename__ = "knowledge_chunks"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    document_id: Mapped[int] = mapped_column(
        ForeignKey("knowledge_documents.id", ondelete="CASCADE"),
        index=True,
        nullable=False,
    )
    user_id: Mapped[int] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"),
        index=True,
        nullable=False,
    )

    # 全局顺序编号。
    # 这里不是“只给 leaf 编号”，而是 parent / leaf 都在同一条时间线上排序，
    # 这样文档详情页按 chunk_index 展示时，结构会更容易看懂。
    chunk_index: Mapped[int] = mapped_column(Integer, nullable=False)

    # parent / leaf
    # parent: 大块上下文，供 small-to-big expand 后给 LLM
    # leaf:   小块召回单元，供 embedding / BM25 / FAISS 检索
    chunk_role: Mapped[str] = mapped_column(String(20), default=KNOWLEDGE_CHUNK_ROLE_LEAF, nullable=False)

    # 如果当前是 leaf chunk，这里指向它所属的 parent chunk
    # 如果当前是 parent chunk，则为 None
    parent_chunk_id: Mapped[int | None] = mapped_column(
        ForeignKey("knowledge_chunks.id", ondelete="CASCADE"),
        index=True,
        nullable=True,
    )

    # 父级标题/主题，主要用于：
    # 1. 检索时把 parent 主题注入 retrieval_content
    # 2. 调试时更容易看出这块属于哪个大主题
    parent_title: Mapped[str] = mapped_column(String(255), default="", nullable=False)

    # text / table
    # 不同 block_type 后续可以走不同 chunking 和 retrieval 策略
    block_type: Mapped[str] = mapped_column(String(30), default=KNOWLEDGE_BLOCK_TYPE_TEXT, nullable=False)

    # child 在 parent 内的顺序编号
    child_index: Mapped[int] = mapped_column(Integer, default=0, nullable=False)

    # 如果是表格块，可记录该 leaf 覆盖的是哪几行
    table_row_from: Mapped[int | None] = mapped_column(Integer, nullable=True)
    table_row_to: Mapped[int | None] = mapped_column(Integer, nullable=True)

    # 给模型看的原始内容。
    # parent chunk: 一般是完整大段正文或完整表格
    # leaf chunk:   一般是子块正文或表格子块
    content: Mapped[str] = mapped_column(LongText, nullable=False)

    start_offset: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    end_offset: Mapped[int] = mapped_column(Integer, default=0, nullable=False)

    source_page: Mapped[int | None] = mapped_column(Integer, nullable=True)
    source_section: Mapped[str] = mapped_column(String(255), default="", nullable=False)

    # 真正给 embedding / BM25 用的检索文本。
    # 它通常比 content 多一点“检索增强信息”，例如父标题、内容类型提示等。
    # 这样能提高 child chunk 的召回准确率。
    retrieval_content: Mapped[str] = mapped_column(LongText, default="", nullable=False)

    # 只有 leaf chunk 才会有 embedding_json
    # parent chunk 一般不做 embedding，避免向量空间被大块噪音污染
    embedding_json: Mapped[str] = mapped_column(LongText, default="", nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now, onupdate=now, nullable=False)

class RagRuns(Base):
    __tablename__ = "rag_runs"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)

    # 谁发起的这次 RAG 提问
    user_id: Mapped[int] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"),
        index=True,
        nullable=False,
    )

    # 原始问题
    question: Mapped[str] = mapped_column(Text, nullable=False)

    # 最终回答
    answer: Mapped[str] = mapped_column(LongText, default="", nullable=False)

    # 整体状态：running / completed / failed
    status: Mapped[str] = mapped_column(String(20), nullable=False)

    # 可选：这次只搜哪些文档
    document_scope_json: Mapped[str] = mapped_column(Text, default="", nullable=False)

    # strict_mode=True 表示只允许根据知识库回答
    strict_mode: Mapped[int] = mapped_column(Integer, default=1, nullable=False)

    # top_k 检索条数，方便后面排查效果
    top_k: Mapped[int] = mapped_column(Integer, default=5, nullable=False)

    # 整次失败原因
    error_message: Mapped[str] = mapped_column(Text, default="", nullable=False)

    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    finished_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now, onupdate=now, nullable=False)


class RagRunSteps(Base):
    __tablename__ = "rag_run_steps"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)

    # 属于哪次 rag run
    rag_run_id: Mapped[int] = mapped_column(
        ForeignKey("rag_runs.id", ondelete="CASCADE"),
        index=True,
        nullable=False,
    )

    status: Mapped[str] = mapped_column(String(20), nullable=False)

    # 比如 embed_query / vector_search / rerank_chunks
    step_type: Mapped[str] = mapped_column(String(50), nullable=False)

    # 给前端或日志看的展示名
    step_name: Mapped[str] = mapped_column(String(100), nullable=False)

    # 输入输出都存 JSON 字符串，方便调试
    input_payload: Mapped[str] = mapped_column(LongText, default="", nullable=False)
    output_payload: Mapped[str] = mapped_column(LongText, default="", nullable=False)

    error_message: Mapped[str] = mapped_column(Text, default="", nullable=False)

    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    finished_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now, onupdate=now, nullable=False)