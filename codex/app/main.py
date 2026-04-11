"""CODEX/WARBRAIN Conversation API -- FastAPI application."""

from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api.router import v1_router
from app.config import settings
from app.interfaces.retriever import MockCodexRetriever
from app.models.database import init_db
from app.services.evaluation import EvaluationPipeline
from app.services.rule_engine import CodexRuleEngine


@asynccontextmanager
async def lifespan(app: FastAPI):
    await init_db()

    retriever = MockCodexRetriever()
    rule_engine = CodexRuleEngine()

    app.state.evaluation_pipeline = EvaluationPipeline(
        retriever=retriever,
        rule_engine=rule_engine,
    )

    yield


app = FastAPI(
    title="CODEX/WARBRAIN Conversation API",
    description="Machine-to-machine doctrinal evaluation API implementing CODEX Decision-Time Evaluation",
    version="0.2.0",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(v1_router)


if __name__ == "__main__":
    import uvicorn
    uvicorn.run("app.main:app", host=settings.host, port=settings.port, reload=True)
