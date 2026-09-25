from fastapi import APIRouter
from pydantic import BaseModel

from app.agent.graph import run_graph
from app.schemas.request import QuestionRequest

router = APIRouter(prefix="/chat")


class LLMResponse(BaseModel):
    answer: str


@router.post("/generate", response_model=LLMResponse)
async def generate_answer(request: QuestionRequest) -> LLMResponse:
    result = await run_graph(request.question)
    answer = result.get("final_answer", "")
    return LLMResponse(answer=answer)
