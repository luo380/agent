from openai import AsyncOpenAI
from sqlalchemy import Sequence

from core.config import settings
from core.service.llm import get_llm_client


def get_embedding_model() ->str:
    # 单独读 embedding 模型名，和聊天模型区分开
    return settings.EMBEDDING_MODEL


async def embed_text(text: str, client: AsyncOpenAI | None = None) -> list[float]:
    # 统一把空字符串处理掉，避免调用 embedding 报错
    text = (text or "").strip()
    if not text:
        return []

    client = client or get_llm_client()

    # OpenAI 兼容接口的 embeddings 调用
    response = await client.embeddings.create(
        model=get_embedding_model(),
        input=text,
    )

    # 返回向量数组，后面用于相似度计算
    return [float(value) for value in response.data[0].embedding]



async def embed_texts(
    texts: Sequence[str],
    client: AsyncOpenAI | None = None,
) -> list[list[float]]:
    # 批量 embedding，后面文档 chunk 入库时会很有用
    cleaned_texts = [(text or "").strip() for text in texts]
    if not cleaned_texts:
        return []

    client = client or get_llm_client()

    # 调用Embedding API  获取向量数组
    response = await client.embeddings.create(
        model=get_embedding_model(),
        input=cleaned_texts,
    )

    return [[float(value) for value in item.embedding] for item in response.data]