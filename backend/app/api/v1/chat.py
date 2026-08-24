from fastapi import APIRouter

router = APIRouter(prefix="/chat")


@router.post("/generate")
def generate_answer(prompt: str):

    response = agent.invoke(
        {"messages": [HumanMessage(content=request.prompt)]},
        {"configurable": {"thread_id": thread_id}},
    )
    return LLMResponse(answer=response["messages"][-1].content)
