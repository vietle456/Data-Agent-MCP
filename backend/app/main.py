import asyncio

from app.agent.graph import run_graph


async def run_agent(question: str):
    result = await run_graph(question)
    print(result["final_answer"])


if __name__ == "__main__":
    asyncio.run(
        run_agent("Summarize the overall sales trend of each video game genre globally")
    )
