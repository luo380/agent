from fastapi import APIRouter, HTTPException, Depends
from sqlalchemy.orm import Session

from api.deps import get_db, get_current_user
from api.schemas.rag import RagCitationResponse, RagRetrievedChunkResponse, RagAskResponse, RagAskRequest
from core.db.models import RagRunSteps, RAG_STEP_STATUS_RUNNING, RagRuns, User
from core.service.embedding import embed_text
from core.service.llm import get_default_temperature, get_default_model, get_llm_client
from core.service.rag import build_citations, build_rag_messages, build_context
from core.service.rag_trace import fail_rag_step, fail_rag_run, complete_rag_run, create_rag_step, complete_rag_step, \
    create_rag_run
from core.service.retrieval import rerank_chunks, search_similar_chunks_by_embedding

router = APIRouter

def fail_open_rag_step(db: Session, step_id: int | None, error_message: str) -> None:
    # 如果某一步还处于 running，就补记为 failed
    if not step_id:
        return

    step = db.query(RagRunSteps).filter(RagRunSteps.id == step_id).first()
    if step and step.status == RAG_STEP_STATUS_RUNNING:
        fail_rag_step(db, step, error_message=error_message)










# -----------------------------------------------------------------------------
# POST /ask —— 知识库问答主入口
# -----------------------------------------------------------------------------
# 客户端向此端点提交问题，服务器执行完整的 RAG 流程：
#   embedding → 向量检索 → 重排序 → 上下文构建 → LLM 回答 → 引用格式化
# 每一步都会在数据库中创建 step 记录，便于审计、调试和性能分析。
@router.post("/ask")
async def ask_knowledge(
    # 请求体：由 Pydantic Schema 校验，包含 question、top_k、strict_mode、document_ids 等字段
    payload: RagAskRequest,
    # 依赖注入：获取数据库会话（自动管理事务）
    db: Session = Depends(get_db),
    # 依赖注入：获取当前登录用户（通过 Token 验证，未登录会自动返回 401）
    user: User = Depends(get_current_user),
):
    # -------------------------------------------------------------------------
    # 1. 参数校验：去除问题两端空白，若问题为空直接拒绝
    #    使用 strip() 避免用户输入全空格或换行等无意义内容
    # -------------------------------------------------------------------------
    question = payload.question.strip()
    if not question:
        # HTTP 400: 客户端参数错误
        raise HTTPException(status_code=400, detail="Question is empty")

    # -------------------------------------------------------------------------
    # 2. 创建 RAG 运行记录（rag_run）—— 可观测性设计
    #    本次问答的所有子步骤都会关联到此 run_id 上，便于追溯整体流程
    # -------------------------------------------------------------------------
    rag_run = create_rag_run(
        db,
        user_id=user.id,           # 关联用户，用于隔离知识库数据和统计
        question=question,         # 记录原始问题
        top_k=payload.top_k,       # 记录检索参数：期望返回的相关块数量
        strict_mode=payload.strict_mode,  # 记录模式：严格模式下无相关内容时不回答
        document_ids=payload.document_ids, # 记录检索范围：仅从指定文档中检索
    )

    # -------------------------------------------------------------------------
    # 3. 预先声明所有步骤的 step_id 变量，初始值为 None
    #    - 若某一步尚未创建就已失败，其值仍为 None，异常时 skip 处理
    #    - 用于异常处理块中统一将残留的 running 步骤标记为 failed
    # -------------------------------------------------------------------------
    step_embed_id = None      # 步骤1：问题 embedding
    step_search_id = None     # 步骤2：向量检索
    step_rerank_id = None     # 步骤3：重排序
    step_context_id = None    # 步骤4：构建上下文
    step_llm_id = None        # 步骤5：LLM 调用
    step_citation_id = None   # 步骤6：格式化引用信息

    # -------------------------------------------------------------------------
    # 主流程 try 块：所有业务步骤都包裹在此，出现异常时由 except 块统一处理
    # 每一个子步骤的模式均为：
    #   create_rag_step(创建 running 状态记录) → 执行业务 → complete_rag_step(标记成功)
    # -------------------------------------------------------------------------
    try:
        # 初始化 LLM 客户端（复用连接，后续 embedding 与 chat completion 共用）
        client = get_llm_client()

        # =====================================================================
        # Step 1: 将问题转换为向量（Query Embedding）
        # ---------------------------------------------------------------------
        # 作用：把用户的自然语言问题映射到高维向量空间，以便与知识库中预计算的
        #       文档块向量进行相似度比对。
        # =====================================================================
        # 先在数据库中创建该步骤记录，状态为 RUNNING
        step_embed = create_rag_step(
            db,
            rag_run_id=rag_run.id,             # 关联到本次问答 run
            step_type="embed_query",           # 步骤类型标识，便于后续按类型聚合统计
            step_name="Generate query embedding",  # 人类可读的步骤名称
            input_payload={
                "question_length": len(question),  # 记录问题长度，便于性能分析
            },
        )
        # 保存 step_id 以便异常时兜底处理
        step_embed_id = step_embed.id

        # 调用嵌入服务，将问题文本转换为向量（浮点数组）
        query_embedding = await embed_text(question, client=client)

        # 向量生成成功：更新步骤为成功状态，并记录输出维度（用于校验向量模型一致性）
        complete_rag_step(
            db,
            step_embed,
            output_payload={"embedding_dim": len(query_embedding)},
        )

        # =====================================================================
        # Step 2: 向量检索（Vector Search / 召回阶段）
        # ---------------------------------------------------------------------
        # 作用：在知识库中找出与问题向量最相似的 N 个文本块作为候选。
        # 策略：为了给后续 rerank 步骤提供更丰富的候选，此处实际检索数量放大为
        #       top_k 的 3 倍（例如用户要 top_k=5，则取 15 个候选），避免遗漏
        #       潜在相关内容。
        # =====================================================================
        step_search = create_rag_step(
            db,
            rag_run_id=rag_run.id,
            step_type="vector_search",
            step_name="Search similar chunks",
            input_payload={
                "top_k": payload.top_k,
                "document_ids": payload.document_ids,
            },
        )
        step_search_id = step_search.id

        # 按向量相似度从数据库中检索相似文本块
        # 参数说明：
        #   - user_id=user.id: 用户数据隔离，仅检索该用户可见的知识库
        #   - top_k=max(...): 放大召回数量（例如 top_k*3），为 rerank 提供候选池
        #   - document_ids or None: 若客户端传入了文档范围，则仅在范围内检索
        vector_hits = search_similar_chunks_by_embedding(
            db,
            user_id=user.id,
            query_embedding=query_embedding,
            top_k=max(payload.top_k * 3, payload.top_k),
            document_ids=payload.document_ids or None,
        )

        # 检索成功：记录最终候选数量
        complete_rag_step(
            db,
            step_search,
            output_payload={"candidate_count": len(vector_hits)},
        )

        # =====================================================================
        # Step 3: 重排序（Rerank / 精排阶段）
        # ---------------------------------------------------------------------
        # 作用：向量相似度是粗粒度的语义匹配，可能引入噪声。Rerank 模型会逐一审
        #       视「问题-候选块」对的语义相关性，给出更准确的相关性得分，并挑出
        #       真正最相关的 top_k 个文本块送给 LLM。
        # =====================================================================
        step_rerank = create_rag_step(
            db,
            rag_run_id=rag_run.id,
            step_type="rerank_chunks",
            step_name="Rerank retrieved chunks",
            input_payload={
                "candidate_count": len(vector_hits),  # 输入候选数
                "top_k": payload.top_k,               # 期望最终保留数量
            },
        )
        step_rerank_id = step_rerank.id

        # 调用 rerank 服务对候选重排序，只保留 top_k 个最相关的文本块
        reranked_hits = rerank_chunks(question, vector_hits, top_k=payload.top_k)

        # 重排序成功：记录最终入选的块数量
        complete_rag_step(
            db,
            step_rerank,
            output_payload={"selected_count": len(reranked_hits)},
        )

        # =====================================================================
        # Step 4: 构建上下文文本（Build RAG Context）
        # ---------------------------------------------------------------------
        # 作用：将重排序后的多个文本块拼接成一段结构化的上下文字符串，作为 LLM
        #       回答问题时的知识来源。通常格式为「文档标题 + 段落内容」的列表。
        # =====================================================================
        step_context = create_rag_step(
            db,
            rag_run_id=rag_run.id,
            step_type="build_context",
            step_name="Build RAG context",
            input_payload={"selected_count": len(reranked_hits)},
        )
        step_context_id = step_context.id

        # 将 reranked_hits 列表转换为可直接喂给 LLM 的字符串上下文
        context = build_context(reranked_hits)

        # 构建成功：记录上下文长度（用于监控 token 消耗和截断风险）
        complete_rag_step(
            db,
            step_context,
            output_payload={"context_length": len(context)},
        )

        # =====================================================================
        # Step 5: 调用 LLM 生成回答（Grounded Answer Generation）
        # ---------------------------------------------------------------------
        # 作用：将「原始问题 + 检索到的上下文」一起发给大语言模型，让模型基于
        #       上下文内容给出忠实的（grounded）回答，避免模型胡编乱造。
        #
        # strict_mode 策略：
        #   - True  严格模式：若无相关上下文，不调用 LLM，直接返回「未找到相关内容」
        #   - False 宽松模式：即使无上下文，也允许 LLM 结合自身知识作答
        # =====================================================================
        step_llm = create_rag_step(
            db,
            rag_run_id=rag_run.id,
            step_type="rag_llm_call",
            step_name="Generate grounded answer",
            input_payload={
                "strict_mode": payload.strict_mode,
                "context_length": len(context),
            },
        )
        step_llm_id = step_llm.id

        # 分支判断：有上下文 OR 处于宽松模式 → 调用 LLM 生成回答
        if context or not payload.strict_mode:
            # 异步调用 LLM Chat Completion 接口
            #   - model: 使用系统默认模型（可由配置切换）
            #   - messages: 包含系统提示、上下文、用户问题的完整消息列表
            #   - temperature: 默认采样温度，控制回答的创造性/一致性
            completion = await client.chat.completions.create(
                model=get_default_model(),
                messages=build_rag_messages(question, context, payload.strict_mode),
                temperature=get_default_temperature(),
            )
            # 从 LLM 响应中取出回答文本，处理空值并去除首尾空白
            answer_text = (completion.choices[0].message.content or "").strip()
        else:
            # 严格模式且无上下文：直接返回固定提示，避免模型自由发挥
            answer_text = "I could not find relevant content in the knowledge base."

        # LLM 调用成功：记录回答长度
        complete_rag_step(
            db,
            step_llm,
            output_payload={"answer_length": len(answer_text)},
        )

        # =====================================================================
        # Step 6: 组织引用信息（Format Citations）
        # ---------------------------------------------------------------------
        # 作用：把 reranked_hits 转换为客户端可展示的引用结构，包含文档 ID、
        #       文档标题、片段来源位置等信息，让用户可以追溯答案的出处。
        # =====================================================================
        step_citation = create_rag_step(
            db,
            rag_run_id=rag_run.id,
            step_type="format_citations",
            step_name="Format citations",
            input_payload={"chunk_count": len(reranked_hits)},
        )
        step_citation_id = step_citation.id

        # 将 hit 列表转换为 citation 对象列表
        citations = build_citations(reranked_hits)

        # 格式化成功：记录引用数量
        complete_rag_step(
            db,
            step_citation,
            output_payload={"citation_count": len(citations)},
        )

        # =====================================================================
        # 4. 收尾：标记整次 RAG 运行为成功状态
        # =====================================================================
        complete_rag_run(db, rag_run, answer=answer_text)

        # =====================================================================
        # 5. 组装统一格式的响应体
        # ---------------------------------------------------------------------
        # 返回字段：
        #   - question: 清洗后的用户问题
        #   - answer:   LLM 生成的回答（或严格模式下的固定提示）
        #   - run_id:   本次运行的 ID，方便客户端再次查询运行详情
        #   - strict_mode: 当前是否处于严格模式
        #   - citations: 引用来源列表（供前端展示「答案出处」）
        #   - retrieved_chunks: 重排序后的文本块详情（供调试或自定义渲染使用）
        # =====================================================================
        response = RagAskResponse(
            question=question,
            answer=answer_text,
            run_id=rag_run.id,
            strict_mode=payload.strict_mode,
            # 使用 Pydantic 的 model_validate 将字典/ORM 对象转换为响应 Schema
            citations=[RagCitationResponse.model_validate(item) for item in citations],
            retrieved_chunks=[
                RagRetrievedChunkResponse.model_validate(item) for item in reranked_hits
            ],
        )
        # 外层再包一层 {"data": ...}，与项目其他接口的统一响应格式保持一致
        return {"data": response}

    # =========================================================================
    # 异常处理块：捕获流程中任意一步抛出的错误，统一清理状态并返回 500
    # =========================================================================
    except Exception as exc:
        # 将异常对象转为字符串，作为统一的错误信息写入数据库和响应体
        error_message = str(exc)

        # 遍历所有可能创建过的 step_id，将仍处于 running 的步骤标记为 failed
        # （那些没有创建过的步骤其 step_id 为 None，fail_open_rag_step 会自动跳过）
        for step_id in [
            step_embed_id,
            step_search_id,
            step_rerank_id,
            step_context_id,
            step_llm_id,
            step_citation_id,
        ]:
            fail_open_rag_step(db, step_id, error_message)

        # 将整次 rag_run 也标记为 failed，并写入错误信息
        # 这里重新查询一次（而非直接使用变量 rag_run），确保读到的是数据库中的最新状态
        latest_run = db.query(RagRuns).filter(RagRuns.id == rag_run.id).first()
        if latest_run:
            fail_rag_run(db, latest_run, error_message=error_message)

        # 最后向客户端返回 HTTP 500 错误，错误详情附带原始异常信息
        raise HTTPException(status_code=500, detail=f"RAG ask failed: {error_message}")
# 1	Embedding	将用户问题转为向量	embed_text()
# 2	向量检索（召回）	从知识库找出最相似的 top_k × 3 个候选	search_similar_chunks_by_embedding()
# 3	Rerank（精排）	对候选重新打分排序，选出真正相关的 top_k 个	rerank_chunks()
# 4	Build Context	将文本块拼接成 LLM 可读取的上下文	build_context()
# 5	LLM 回答生成	将问题+上下文发给 LLM 生成 grounded answer	client.chat.completions.create()
# 6	Citations 格式化	整理引用来源（答案出处）	build_citations()