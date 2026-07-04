from pathlib import Path

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles

from api.routes import auth, health, agents, session, runs, knowledge, rag, rag_langchain, rag_langchain_native
from core.db.session import init_db

BASE_DIR = Path(__file__).resolve().parent.parent
FRONTEND_DIR = BASE_DIR / "frontend"
FRONTEND_DIST_DIR = FRONTEND_DIR / "dist"

app = FastAPI(
    title="Agent Project API",
    description="Backend and UI entry for the agent project.",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "http://127.0.0.1:8000",
        "http://localhost:8000",
        "http://127.0.0.1:5173",
        "http://localhost:5173",
    ],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.on_event("startup")
def on_startup() -> None:
    init_db()


@app.get("/")
def root():
    return {
        "message": "Agent Project API is running.",
        "frontend_dev": "http://127.0.0.1:5173",
        "frontend_prod": "/ui/",
    }


app.include_router(health.router, prefix="/api/health", tags=["health"])
app.include_router(auth.router, prefix="/api/auth", tags=["auth"])
app.include_router(agents.router, prefix="/api/agents", tags=["agents"])
app.include_router(session.router, prefix="/api/sessions", tags=["sessions"])
app.include_router(runs.router, prefix="/api/runs", tags=["runs"])
app.include_router(knowledge.router, prefix="/api/knowledge", tags=["knowledge"])

app.include_router(rag.router, prefix="/api/rag", tags=["rag"])

app.include_router(rag_langchain_native.router, prefix="/api/rag-langchain", tags=["rag-langchain"])

if FRONTEND_DIST_DIR.exists():
    app.mount("/ui", StaticFiles(directory=FRONTEND_DIST_DIR, html=True), name="ui")
