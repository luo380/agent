import re
from collections.abc import Sequence

from openai import AsyncOpenAI

from core.service.embedding import embed_text
from core.service.llm import get_llm_client, get_default_model, get_default_temperature
from core.service.retrieval import RetrievedChunk, search_similar_chunks_by_embedding, rerank_chunks


# 构建上下文
# 用户问题："怎么安装你们的产品？"
#         │
#         ▼ 检索相关文档
#    [chunk1, chunk2, chunk3, ...]  ← 从数据库查出来
#         │
#         ▼ build_context() ← 就是这段代码！
#    ┌─────────────────────────┐
#    │ [1] 来源=产品说明书...   │  ← 给每条内容加上来源标签
#    │ 内容文本...             │
#    │                         │
#    │ [2] 来源=常见问题...     │
#    │ 内容文本...             │
#    └─────────────────────────┘
#         │
#         ▼ 拼进 Prompt（提示词）
#    "请根据以下资料回答用户问题：\n\n"
#    + 上面拼接好的上下文
#    + "\n\n用户问题：怎么安装你们的产品？"
#         │
#         ▼ 发给大模型（LLM）
#    大模型看到资料 → 生成准确回答
# Sequence[] 接受列表、元组、或其他序列类型
def build_context(chunks: Sequence[RetrievedChunk]) -> str:
    # 防御性编程：如果检索结果为空，直接返回空字符串
    # 避免后面的循环报错，也让调用方不用判空
    if not chunks:
        return ""

    # 用一个列表暂存每一行文本，最后再用换行符拼接
    # 这样做比每次用 += 拼接字符串高效得多（字符串是不可变对象）
    blocks: list[str] = []

    # enumerate(chunks, start=1)
    #   - enumerate: 同时拿到"序号"和"元素"
    #   - start=1:  编号从 1 开始（而不是默认的 0），给人看更友好
    # 遍历每个检索到的文本块，依次拼装
    for index, chunk in enumerate(chunks, start=1):
        # ─── 构造"来源标签"（header） ───
        # 给每个文本块加一个信息头，告诉大模型：
        #   这段话来自哪个文档？是文档的第几块？第几页？哪个章节？
        # 用 f-string 格式化，字段之间用分号分隔，清晰易读
        #
        # 特殊处理：
        #   - source_page 可能是 None（非分页文档，如 .md 文件），
        #     此时用 "-" 占位，而不是显示 "None"
        #   - source_section 可能是空字符串，同理用 "-" 占位
        header = (
            f"[{index}] "  # 序号，用方括号括起来，如 [1]、[2]
            f"document={chunk.document_name}; "  # 文档名称
            f"chunk={chunk.chunk_index}; "  # 文本块在文档内的序号
            f"page={chunk.source_page if chunk.source_page is not None else '-'}; "  # 页码
            f"section={chunk.source_section or '-'}"  # 章节
        )

        # 依次添加到 blocks：标签头 → 内容 → 空行（分隔）
        blocks.append(header)                 # 第 1 行：来源信息
        # strip() 去除内容首尾的空白字符（空格、换行、制表符等），
        # 避免内容开头或结尾出现多余的空行，让输出更整洁
        blocks.append(chunk.content.strip())  # 第 2 行：实际内容
        blocks.append("")                     # 第 3 行：空行（作为块之间的视觉分隔）

    # 最后用换行符把所有行连起来，形成完整的上下文字符串
    # 再 strip() 一次，去掉末尾多余的空行（最后一次 append("") 产生的空行）
    # 最终格式：
    #   [1] document=...
    #   内容...
    #
    #   [2] document=...
    #   内容...
    return "\n".join(blocks).strip()


def build_citations(chunks: Sequence[RetrievedChunk]) -> list[dict]:
    # 返回给前端展示的引用信息
    citations: list[dict] = []
    for chunk in chunks:
        citations.append(
            {
                "document_id": chunk.document_id,
                "document_name": chunk.document_name,
                "chunk_id": chunk.chunk_id,
                "chunk_index": chunk.chunk_index,
                "source_page": chunk.source_page,
                "source_section": chunk.source_section,
                "score": chunk.final_score or chunk.vector_score,
                "content": chunk.content[:300],
            }
        )
    return citations
# 用来检测答案里是否已经出现了 [1] / [2] 这种引用标记
CITATION_MARK_RE = re.compile(r"\[(\d+)\]")


def _chunk_value(chunk: RetrievedChunk | dict, key: str, default=None):
    if isinstance(chunk, dict):
        return chunk.get(key, default)
    return getattr(chunk, key, default)


def ensure_answer_has_citations(answer_text: str, chunks: Sequence[RetrievedChunk]) -> str:
    """
    给最终回答补一道“引用兜底”。

    为什么需要这一步：
    - 我们虽然在 prompt 里要求模型输出 [1][2] 引用
    - 但大模型并不总是 100% 听话
    - 所以这里再做一次后处理，保证“有命中的知识库内容时，最终答案里一定看得到来源”

    处理规则：
    1. 没有检索结果：原样返回
    2. 已经带 [1] / [2]：原样返回，不重复追加
    3. 没带引用：在答案后面自动补一个“参考来源”块
    """
    if not chunks:
        return (answer_text or "").strip()

    clean_answer = (answer_text or "").strip()
    if not clean_answer:
        clean_answer = "我根据知识库整理了相关信息。"

    # 如果模型已经按要求写了 [1][2]，就不要重复追加
    if CITATION_MARK_RE.search(clean_answer):
        return clean_answer

    reference_lines: list[str] = []
    for index, chunk in enumerate(chunks, start=1):
        document_name = _chunk_value(chunk, "document_name", "unknown document")
        source_page = _chunk_value(chunk, "source_page")
        source_section = _chunk_value(chunk, "source_section", "")
        page_text = f"；第 {source_page} 页" if source_page is not None else ""
        section_text = f"；章节/区域：{source_section}" if source_section else ""
        reference_lines.append(f"[{index}] {document_name}{page_text}{section_text}")

    reference_block = "\n".join(reference_lines)

    return f"{clean_answer}\n\n参考来源：\n{reference_block}"
def build_rag_messages(question: str, context: str, strict_mode: bool) -> list[dict]:
    # 注意：这里包含中文 prompt，文件必须保持 UTF-8 编码；修改时不要使用会破坏中文或换行的批量替换方式。
    # strict_mode=True 时，要求模型只根据上下文回答
    # 严格模式
    if strict_mode:
        system_prompt = (
            "你是一个知识库问答助手。"
            "必须优先依据提供的知识库上下文回答。"
            "如果上下文不足以支持答案，就直接说明知识库中没有足够信息，不要编造。"
        )
    else:
        system_prompt = (
            "你是一个知识库优先的问答助手。"
            "请优先依据提供的知识库上下文回答。"
            "如果知识库没有命中相关内容，可以基于常识做谨慎补充，但要明确说明这部分不是来自知识库。"
        )

    has_context = bool((context or "").strip())
    if has_context:
        answer_instruction = (
            "请先基于知识库给出简洁回答，并在确实引用到知识库内容时使用 [1]、[2] 这类来源编号。"
        )
        context_block = context
    else:
        answer_instruction = (
            "当前没有检索到相关知识库内容。"
            "不要使用 [1]、[2] 这类引用标记。"
            "如果 strict_mode 已关闭，你可以给出谨慎的补充回答，但必须明确说明这部分不是来自知识库。"
        )
        context_block = "未检索到相关知识库内容。"

    user_prompt = (
        f"用户问题：\n{question}\n\n"
        f"知识库上下文：\n{context_block}\n\n"
                                                                                                                                                                                                                                                                                  f"回答要求：{answer_instruction}"
    )

    return [
        {"role": "system", "content": system_prompt},
        {"role": "user", "content": user_prompt},
    ]



# ─────────────────────────────────────────────────────────────
# 函数：answer_with_knowledge
# 作用：完整的 RAG 流水线 — 从用户问题到最终回答
# ─────────────────────────────────────────────────────────────
#
# 【什么是 RAG？】
# RAG = Retrieval-Augmented Generation（检索增强生成）
# 简单说就是：
#   1. 从你的知识库中找到相关资料
#   2. 把资料和问题一起发给大模型
#   3. 大模型看着资料来回答，不会瞎编
#
# 【完整流程】
#   用户问题 → 转向量 → 向量检索 → 精排 → 拼上下文 → 发大模型 → 返回回答+引用
#
# 【参数】
#   db:             数据库会话（SQLAlchemy）
#   user_id:        用户ID（只查该用户自己的资料）
#   question:       用户的原始问题文本
#   top_k:          最终用多少条参考资料（默认 5）
#   document_ids:   可选：限定只在某些文档中检索（None=全部文档）
#   strict_mode:    是否开启严格模式（默认 True，不瞎编）
#   client:         可选：大模型客户端（不传就自动创建一个）
# 【返回】
#   dict: 包含回答文本、参考资料列表、原始问题等
# ─────────────────────────────────────────────────────────────
# ─────────────────────────────────────────────────────────────
# answer_with_knowledge: 完整的 RAG 主函数
#
# 【RAG 是什么？】
# RAG = Retrieval-Augmented Generation（检索增强生成）
# 简单理解：先从你的知识库"搜资料"，再让 AI"看着资料"回答问题
#
# 【完整流程】
#   用户问题 → 转向量 → 向量检索 → 精排 rerank → 拼上下文 → 发大模型 → 返回结果
#
# 【参数】
#   db:             数据库会话（SQLAlchemy），用于查询知识库
#   user_id:        用户ID，只检索该用户自己的文档（越权防护）
#   question:       用户的原始问题文本
#   top_k:          最终用多少条参考资料（默认 5）
#   document_ids:   可选：限定只在某些文档中检索（None=全部文档）
#   strict_mode:    是否开启严格模式（默认 True=只能根据资料回答）
#   client:         可选：大模型客户端（方便依赖注入、测试时 mock）
# 【返回】
#   dict: 包含 answer（回答文本）、citations（引用列表）等结构化数据
# ─────────────────────────────────────────────────────────────
async def answer_with_knowledge(
    db,                                  # 数据库连接
    *,                                   # Python 语法：后面所有参数必须写参数名（防传错位置）
    user_id: int,                        # 用户ID
    question: str,                       # 用户的原始问题（例如："怎么安装产品？"）
    top_k: int = 5,                      # 最终取多少条参考资料（默认 5 条）
    document_ids: Sequence[int] | None = None,  # 可选：限定某些文档；None=检索所有文档
    strict_mode: bool = True,            # 严格模式：True=只能根据资料答；False=可发挥
    client: AsyncOpenAI | None = None,   # 可选：大模型客户端
) -> dict:

    # ─── 整条 RAG 链路：问句 embedding → 检索 → rerank → 拼上下文 → 生成回答 ───

    # 步骤 1：获取/准备大模型客户端
    # client or get_llm_client() 的含义：
    #   - 如果调用方传了 client（不是 None），就用传进来的
    #   - 如果 client 是 None，就调用 get_llm_client() 创建一个新的
    # 这叫"依赖注入"，方便测试（可以传一个假 client 进去），也方便复用已有连接
    client = client or get_llm_client()

    # 步骤 2：把用户问题转成向量（Embedding）
    # 向量检索的前提：必须把文本转成一串数字（向量）
    # 例如："怎么安装产品？" → [0.12, -0.34, 0.58, ...]
    # await 表示这是异步操作（需要等待大模型 API 返回向量结果）
    query_embedding = await embed_text(question, client=client)

    # 步骤 3：向量检索（粗检索）
    # 根据向量相似度，从数据库中找出最相关的文本块
    # top_k=max(top_k * 3, top_k)：先检索 3 倍数量（想要 5 条就先查 15 条）
    #   目的：给后面的精排（rerank）更多候选，提高最终准确性
    #   max(..., top_k) 是防御性代码，防止 top_k=0 时出问题
    vector_hits = search_similar_chunks_by_embedding(
        db,
        user_id=user_id,
        query_embedding=query_embedding,
        top_k=max(top_k * 3, top_k),
        document_ids=document_ids,
    )

    # 步骤 4：精排（Rerank）
    # 向量相似度只看"语义上像不像"
    # 关键词重合度看"字面有没有重复词"
    # rerank_chunks 把两者结合，重新排序，挑出最相关的 top_k 条
    # 精排可以显著提高检索质量，避免"语义像但关键词不搭"的错误结果
    reranked_hits = rerank_chunks(question, vector_hits, top_k=top_k)

    # 步骤 5：拼上下文（给大模型看的参考资料文本）
    # 把精排后的文本块拼成格式化文本（带 [1] [2] 编号和来源信息）
    # 格式示例：
    #   [1] 来源=产品说明书.pdf; chunk=5; page=3
    #   首先下载安装包...
    #
    #   [2] 来源=常见问题.md; chunk=12; page=-
    #   安装失败请检查网络...
    context = build_context(reranked_hits)

    # ─── 步骤 6：决定是否调用大模型生成回答 ───
    #
    # 条件判断：context or not strict_mode
    #   情况 A：context 不为空（检索到了资料）→ 调用大模型
    #   情况 B：strict_mode 是 False（宽松模式，即使没资料也允许 AI 发挥）→ 调用大模型
    #   情况 C：context 为空 + strict_mode 是 True → 不调用大模型，直接返回找不到
    #
    # 这样设计的目的：
    #   - 严格模式下，如果知识库没相关资料，直接告诉用户"找不到"，不让 AI 瞎编
    #   - 宽松模式下，即使没资料，也允许 AI 根据自身知识回答（质量可能不稳）
    if context or not strict_mode:
        # 调用大模型生成回答
        # await client.chat.completions.create() 是 OpenAI Python SDK 的标准异步调用
        # model=get_default_model(): 使用项目配置的默认模型（如 gpt-4o-mini）
        # messages=build_rag_messages(...): 组装好的 system + user 消息
        # temperature=get_default_temperature(): 温度值（0=保守确定，1=创意随机）
        completion = await client.chat.completions.create(
            model=get_default_model(),
            messages=build_rag_messages(question, context, strict_mode),
            temperature=get_default_temperature(),
        )
        # 从返回结果中提取回答文本
        # (completion.choices[0].message.content or "") 是防御性代码
        #   - 正常情况下 content 是字符串
        #   - 但如果模型返回的内容是 None，or "" 保证不会报错
        # .strip() 去除首尾空白字符
        answer_text = (completion.choices[0].message.content or "").strip()
    else:
        # 严格模式 + 没检索到相关资料 → 直接告诉用户"找不到"
        # 不调用大模型，避免 AI 瞎编
        answer_text = "I could not find relevant content in the knowledge base."

    # ─── 步骤 7：组装最终返回结果 ───
    # 把所有关键信息打包成一个 dict 返回
    # 结构化返回方便前端做各种展示和处理
    return {
        "answer": answer_text,                    # AI 生成的回答文本（核心）
        "citations": build_citations(reranked_hits),  # 参考来源列表（给前端展示"引用了哪些文档"）
        "retrieved_chunks": reranked_hits,         # 检索到的原始文本块（方便前端二次处理）
        "context": context,                        # 拼好的上下文（方便调试或日志记录）
        "query_embedding_dim": len(query_embedding),  # 向量维度（验证用，如 1536 维）
    }
