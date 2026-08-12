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


# ==========================================================================
# 文档导入状态机（缺口6改造：5状态 → 12细分状态）
# ==========================================================================
# 为什么要从 5 个大状态拆成 12 个细分状态？
#   改造前只有 uploaded / parsing / chunking / ready / failed 这 5 个
#   一旦 status=failed，只能猜到底是"PDF坏了"还是"Embedding API挂了"——
#   而且失败后是整篇回滚，下次得从 0 开始。
#
# 12 状态的正常流转（8步）：
#   uploaded → parsing → parsed → chunking → chunked
#            → embedding → indexing → ready
#
# 非正常分支（4 个失败状态）：
#   parsing     失败  → parse_failed   ← PDF损坏/解析器不兼容，重传也大概率失败
#   chunking    失败  → chunk_failed   ← 分块参数越界等逻辑异常，比较少见
#   embedding   失败  → embed_failed   ← API Key 过期/限流，换个时间重试大概率成功
#   其他兜底           → failed         ← 老代码/未知错误兼容
#
# 前端显示示例（进度条百分比对应见 API 层 _enrich_doc_with_progress）：
#   status=parsing        → "正在解析文档..."       5%
#   status=embedding      → "正在向量化 42/100 ..." 55%
#   status=parse_failed   → "❌ 解析失败：PDF损坏"   红叉
#   status=embed_failed   → "⚠️ 向量化失败：API限流"  给"重试"按钮
# ==========================================================================

# ---- 正常流转阶段 ----
DOCUMENT_STATUS_UPLOADED = "uploaded"      # 文件落盘 + DB INSERT 完成，还没开始解析（用户点上传后的第1秒状态）
DOCUMENT_STATUS_PARSING = "parsing"        # PyPDF/Excel/Docx 正在读文件 → 抽全文 + 章节结构
DOCUMENT_STATUS_PARSED = "parsed"          # 解析完成，全文 content_text 已写入 DB（过渡状态，马上进 chunking）
DOCUMENT_STATUS_CHUNKING = "chunking"      # build_hierarchical_chunks() 在做 parent+leaf 两层切分
DOCUMENT_STATUS_CHUNKED = "chunked"        # 分块完成，所有 chunk 行已写入 DB，total_chunks/processed_chunks 字段可用
DOCUMENT_STATUS_EMBEDDING = "embedding"    # 正在调 Embedding API（最耗时的一步，可按 processed_chunks/total_chunks 显示精确进度条）
DOCUMENT_STATUS_INDEXING = "indexing"      # rebuild_user_faiss_index() 把新向量写进 FAISS 文件
DOCUMENT_STATUS_READY = "ready"            # 全部完成 ✅ 文档可被检索到

# ---- 失败分支（4 个细分状态，不再笼统写 failed）----
DOCUMENT_STATUS_PARSE_FAILED = "parse_failed"    # 例：PDF 加密/损坏 → 前端给"重新上传文件"按钮
DOCUMENT_STATUS_CHUNK_FAILED = "chunk_failed"    # 例：分块器 BUG → 前端给"使用系统兜底分块重试"
DOCUMENT_STATUS_EMBED_FAILED = "embed_failed"    # 例：API 限流 429/Key过期 → 前端给"重试向量化"按钮（80%能恢复）
DOCUMENT_STATUS_FAILED = "failed"                # 兼容性兜底：老版本/未知错误一律落这儿

# ==========================================================================
# 单 chunk 失败记录（KnowledgeChunkFailures.status 取值）
# ==========================================================================
# 为什么需要这个级别的状态？
#   一份 100 页 PDF 会切成 ~300 个 leaf chunk。Embedding API 调用 300 次，
#   很常见的情况是 297 个成功，只有第 73/184/256 个因为网络抖动失败。
#   改造前这种情况下整篇文档会被 rollback 成 failed → 下次 300 个全重跑（白白浪费 99% 的钱）
#   改造后失败的这 3 个单独写进 KnowledgeChunkFailures 表，下次点「重试失败chunk」
#   只跑这 3 个就行。
IMPORT_CHUNK_STEP_PENDING = "pending"      # 排队待重试（用户点了"重试失败chunk"，还没轮到它）
IMPORT_CHUNK_STEP_RETRYING = "retrying"    # 正在重试中（指数退避等待间隔时也保持这个）
IMPORT_CHUNK_STEP_SUCCESS = "success"      # 这次重试成功了（可以把这行 status 标成功或者直接 delete）
IMPORT_CHUNK_STEP_FAILED = "failed"       # 达到最大重试次数（3次）仍然失败 → 需要人工介入


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
    """
    知识库文档主表 —— 缺口6新增 5 个工程化字段说明：
    ┌──────────────────┬─────────────┬────────────────────────────────────────────┐
    │ 字段             │ 类型        │ 作用 + 示例                                │
    ├──────────────────┼─────────────┼────────────────────────────────────────────┤
    │ file_md5         │ VARCHAR(32) │ 文件内容 MD5，用于【秒级去重】。            │
    │                  │  INDEX      │ 例：用户把「2024年报.pdf」改名叫           │
    │                  │             │ 「2024年度最终版.pdf」再传一次 → 会命中     │
    │                  │             │ 同 MD5 → 直接返回旧文档 id，不白跑解析。    │
    ├──────────────────┼─────────────┼────────────────────────────────────────────┤
    │ file_size_bytes  │ INT         │ 文件字节数，用于：①前端显示文件大小        │
    │                  │             │ （8.4 MB）②估算进度（大文件通常 chunk 多） │
    ├──────────────────┼─────────────┼────────────────────────────────────────────┤
    │ total_chunks     │ INT         │ 总 chunk 数（分块阶段结束后确定）          │
    ├──────────────────┼─────────────┼────────────────────────────────────────────┤
    │ processed_chunks │ INT         │ 已完成 embedding 的 chunk 数，每个 batch   │
    │                  │             │ 成功就 +=len(batch)，因此进度条是平滑的。  │
    ├──────────────────┼─────────────┼────────────────────────────────────────────┤
    │ failed_chunks    │ INT         │ embedding 3次降级重试仍失败的 chunk 数。   │
    │                  │             │ >0 时 status 不会到 ready，而是到          │
    │                  │             │ embed_failed，给用户展示「重试失败chunk」。│
    └──────────────────┴─────────────┴────────────────────────────────────────────┘

    前端进度条百分比的公式（见 API 层 _enrich_doc_with_progress）：
        if status == uploaded:     progress = 5%
        if status == parsing:      progress = 10%
        if status == parsed:       progress = 30%
        if status == chunking:     progress = 40%
        if status == chunked:      progress = 50%
        if status == embedding:    progress = 50 + 45 * processed/total    ← 最精确的一段
        if status == indexing:     progress = 95%
        if status == ready:        progress = 100%
    """
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
    # status 取值：见上面 12 个 DOCUMENT_STATUS_* 常量
    status: Mapped[str] = mapped_column(String(20), default=DOCUMENT_STATUS_UPLOADED, nullable=False)
    content_text: Mapped[str] = mapped_column(LongText, default="", nullable=False)
    # 文档级错误信息（解析失败原因/超过最大重试次数的失败统计等）
    error_message: Mapped[str] = mapped_column(Text, default="", nullable=False)
    # 兼容老字段：改造前只有这个"总chunk数"。现在推荐用 total_chunks。
    chunk_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)

    # ------ 缺口6 新增 5 列 ------
    # MD5 去重核心。注意带了 UNIQUE 以外的 INDEX，因为查询是 (user_id, file_md5) 二元组命中。
    file_md5: Mapped[str] = mapped_column(String(32), default="", index=True, nullable=False)
    file_size_bytes: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    total_chunks: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    processed_chunks: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    failed_chunks: Mapped[int] = mapped_column(Integer, default=0, nullable=False)

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


class KnowledgeChunkFailures(Base):
    """
    单 chunk 级失败记录（缺口6的新增表，支撑「失败不整篇回滚」特性）

    ═══════════════════════════════════════════════════════════════
    场景举例（最常见的 3 个失败 case）：
    ┌──────────────────────────────────────────────────────────────┐
    │ 文档 id=42 共 100 个 chunk，embedding 过程中：                 │
    │   chunk 1 ~ 72  →  ✅ 成功                                    │
    │   chunk 73      →  ❌ API 报 429 Rate limit exceeded         │
    │                   batch_size=16 失败 → 拆成 4 → 再拆 1，      │
    │                   指数退避 3 次还是 429 → 写进本表            │
    │   chunk 74~100  →  ✅ 成功                                    │
    │                                                              │
    │ 结果：document.status = embed_failed，                        │
    │       failed_chunks = 1，                                    │
    │       成功的 99 个 chunk **照常可被检索**（不因为 1 个白瞎 99 个）│
    │       用户点「重试失败chunk」→ 只跑 chunk 73 这 1 个。        │
    └──────────────────────────────────────────────────────────────┘

    关键字段速查：
      step_name  ∈ {parsing, chunking, embedding_api, faiss_write}   —— 哪一步挂的
      status     ∈ {pending, retrying, success, failed}              —— 见 IMPORT_CHUNK_STEP_*
      retry_count：当前已重试几次（Worker 内部限制 ≤3，避免无限循环打钱）
    """
    __tablename__ = "knowledge_chunk_failures"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    # ↓ 三棵外键树，一个 chunk 失败同时挂 3 个维度，怎么查都能命中索引
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
    # 可能为 NULL：比如 chunking 阶段在分块过程中崩了，这时候 chunk 行还没 INSERT，chunk_id 不存在
    chunk_id: Mapped[int | None] = mapped_column(
        ForeignKey("knowledge_chunks.id", ondelete="CASCADE"),
        index=True,
        nullable=True,
    )

    # 在哪一步失败。取值约定：
    #   parsing         —— 解析阶段（比如读取 PDF 某一页时 CRC 校验失败）
    #   chunking        —— 分块阶段（极少见）
    #   embedding_api   —— 调用 Embedding 模型接口（最常见：429 限流/超时/Key 无效）
    #   faiss_write     —— FAISS 索引写入（极少见：磁盘满/权限）
    step_name: Mapped[str] = mapped_column(String(30), nullable=False)
    # 本条失败记录的状态，见 IMPORT_CHUNK_STEP_*
    status: Mapped[str] = mapped_column(String(20), default=IMPORT_CHUNK_STEP_PENDING, nullable=False)
    # 已重试次数。每次重试前 +1，达到阈值后更新 status → failed 不再重试
    retry_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    # 结构化的异常类型（比如 httpx.ConnectTimeout / openai.RateLimitError），
    # 方便以后做 dashboard 统计 Top N 失败原因
    error_type: Mapped[str] = mapped_column(String(100), default="", nullable=False)
    # 人类可读的错误堆栈（取前 2000 字符，截断后保留）
    error_message: Mapped[str] = mapped_column(Text, default="", nullable=False)

    # chunk 序号引用（和 knowledge_chunks.chunk_index 对齐）
    # 就算 chunk_id 为 NULL，也能知道是第几个 chunk 出了问题（方便在前端文档预览里红色高亮）
    chunk_index_ref: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    # 失败 chunk 的前 500 字预览。
    #   → 管理员后台不用去查 knowledge_chunks 表，一眼就能看出是哪一段的 embedding 失败
    retrieval_content_preview: Mapped[str] = mapped_column(String(500), default="", nullable=False)

    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now, onupdate=now, nullable=False)
    # 最近一次重试时间（用于「指数退避」——第1次等1.5s，第2次等2.25s，第3次等3.375s）
    last_retry_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=True)


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