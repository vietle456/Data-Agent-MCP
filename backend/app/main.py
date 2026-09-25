from contextlib import asynccontextmanager

import uvicorn
from fastapi import FastAPI

from app.agent.graph import run_graph
from app.api.v1.authentication import router as auth_router
from app.api.v1.chat import router as chat_router
from app.core.database import create_tables
from app.schemas.request import QuestionRequest


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Ensure all DB tables exist before the first request is served."""
    await create_tables()
    yield


app = FastAPI(lifespan=lifespan, title="Data Agent MCP", version="1.0.0")

# Register routers
app.include_router(auth_router, prefix="/api/v1")
app.include_router(chat_router, prefix="/api/v1")


@asynccontextmanager
async def lifespan(app: FastAPI):
    await create_tables()
    yield


@app.post("/ask")
async def ask(request: QuestionRequest):
    result = await run_graph(request.question)
    return {"answer": result["final_answer"]}


if __name__ == "__main__":
    uvicorn.run(app, host="localhost", port=8000)
