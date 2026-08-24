from langchain_core.messages import HumanMessage
from langchain_openai import ChatOpenAI
from langgraph.graph import StateGraph, END
from mcp import ClientSession
from mcp.client.stdio import stdio_client
from langchain_mcp_adapters.tools import load_mcp_tools
from dotenv import load_dotenv

from app.agent.state import AgentState
from app.agent.nodes import (
    PlannerNode,
    CodeGenNode,
    SandboxExecNode,
    ErrorCorrectionNode,
    DirectAnswerNode,
    FinalFormattingNode,
    ast_eval_node,
    advance_step,
    fallback_failure_node,
    plan_intent,
    ast_eval_router,
    should_retry,
    step_router,
)
from app.core.config import MCP_SERVER_PARAMS

load_dotenv()


async def run_graph(question: str) -> dict:
    """
    Starts the MCP server subprocess, loads its tools, then assembles and invokes
    the LangGraph state machine — all within the MCP session context so tools
    remain valid throughout execution.
    """
    async with stdio_client(MCP_SERVER_PARAMS) as (read, write):
        async with ClientSession(read, write) as session:
            await session.initialize()

            # Convert MCP tools → LangChain Tool objects
            mcp_tools = await load_mcp_tools(session)

            llm = ChatOpenAI(model="gpt-4o", temperature=0)

            graph = _build_state_graph(llm, mcp_tools)

            initial_state: AgentState = {
                "messages": [HumanMessage(content=question)],
                "plan": {},
                "current_step_index": 0,
                "schema_context": "",
                "generated_code": "",
                "retry_count": 0,
                "execution_output": {},
                "ast_violation": False,
                "final_answer": "",
            }

            return await graph.ainvoke(initial_state)


def _build_state_graph(llm, mcp_tools):
    graph = StateGraph(AgentState)

    # ── Nodes ─────────────────────────────────────────────────────────────────
    graph.add_node("planner", PlannerNode(llm, mcp_tools))
    graph.add_node("code_gen", CodeGenNode(llm))
    graph.add_node("ast_eval", ast_eval_node)
    graph.add_node("sandbox_exec", SandboxExecNode(mcp_tools))
    graph.add_node("advance_step", advance_step)
    graph.add_node("error_correction", ErrorCorrectionNode(llm))
    graph.add_node("direct_answer", DirectAnswerNode(llm))
    graph.add_node("final_formatting", FinalFormattingNode(llm))
    graph.add_node("fallback_failure", fallback_failure_node)

    graph.set_entry_point("planner")

    # ── Edges ──────────────────────────────────────────────────────────────────
    # planner → intent check
    graph.add_conditional_edges(
        "planner",
        plan_intent,
        {"direct": "direct_answer", "execute": "code_gen"},
    )

    # direct answer path terminates immediately
    graph.add_edge("direct_answer", END)

    # code_gen → safety gate
    graph.add_edge("code_gen", "ast_eval")

    # ast_eval → bypass sandbox on violation, run sandbox if safe
    graph.add_conditional_edges(
        "ast_eval",
        ast_eval_router,
        {"safe": "sandbox_exec", "violation": "error_correction"},
    )

    # sandbox_exec → retry / give up / advance
    graph.add_conditional_edges(
        "sandbox_exec",
        should_retry,
        {
            "success": "advance_step",
            "retry": "error_correction",
            "give_up": "fallback_failure",
        },
    )

    # error_correction generates corrected code → back to safety gate (skip code_gen re-run)
    graph.add_edge("error_correction", "ast_eval")

    # advance_step → loop back for next step or finish
    graph.add_conditional_edges(
        "advance_step",
        step_router,
        {"next_step": "code_gen", "done": "final_formatting"},
    )

    graph.add_edge("fallback_failure", END)
    graph.add_edge("final_formatting", END)

    return graph.compile()
