import asyncio
import json
import sys
from pathlib import Path

from sqlalchemy import or_

ROOT_DIR = Path(__file__).resolve().parent.parent
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

from core.db.models import KnowledgeChunks
from core.db.session import SessionLocal
from core.service.embedding import embed_texts


async def backfill_missing_embeddings(batch_size: int = 50) -> int:
    session = SessionLocal()
    updated = 0

    try:
        chunks = (
            session.query(KnowledgeChunks)
            .filter(
                or_(
                    KnowledgeChunks.embedding_json == "",
                    KnowledgeChunks.embedding_json.is_(None),
                )
            )
            .order_by(KnowledgeChunks.document_id.asc(), KnowledgeChunks.chunk_index.asc())
            .all()
        )

        for start in range(0, len(chunks), batch_size):
            batch = chunks[start:start + batch_size]
            embeddings = await embed_texts([chunk.content for chunk in batch])
            if len(embeddings) != len(batch):
                raise RuntimeError("Embedding result count does not match chunk count")

            for chunk, embedding in zip(batch, embeddings):
                chunk.embedding_json = json.dumps(embedding, ensure_ascii=False)
                updated += 1

            session.commit()

        return updated
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()


if __name__ == "__main__":
    count = asyncio.run(backfill_missing_embeddings())
    print(f"Backfilled embeddings for {count} chunks.")