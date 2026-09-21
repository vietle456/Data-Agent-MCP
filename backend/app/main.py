import uvicorn
from app.agent.graph import run_graph
from app.models.request import QuestionRequest
from fastapi import FastAPI

app = FastAPI(title="Data Agent MCP", version="1.0.0")


@app.post("/ask")
async def ask(request: QuestionRequest):
    result = await run_graph(request.question)
    return {"answer": result["final_answer"]}


if __name__ == "__main__":
    uvicorn.run(app, host="localhost", port=8000)
