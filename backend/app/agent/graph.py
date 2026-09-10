from langchain_core.messages import HumanMessage
from langchain_openai import ChatOpenAI
from langgraph.graph import StateGraph, END
from mcp import ClientSession
from mcp.client.stdio import stdio_client
from langchain_mcp_adapters.tools import load_mcp_tools
from dotenv import load_dotenv

from app.agent.state import AgentState
from app.models.plan import Plan
from app.agent.nodes import (
    PlannerNode,
    CodeGenNode,
    CodeExecNode,
    ErrorCorrectionNode,
    DirectAnswerNode,
    FinalFormattingNode,
    ast_eval_node,
    advance_step,
    fallback_failure_node,
    plan_intent,
    ast_eval_router,
    code_exec_router,
    step_router,
)
from app.core.config import MCP_SERVER_PARAMS
from app.core.logging_config import get_logger

load_dotenv()

logger = get_logger(__name__)


async def run_graph(question: str) -> dict:
    """
    Starts the MCP server subprocess, loads its tools, then assembles and invokes
    the LangGraph state machine — all within the MCP session context so tools
    remain valid throughout execution.
    """
    logger.debug("[run_graph] Starting MCP stdio client subprocess")
    async with stdio_client(MCP_SERVER_PARAMS) as (read, write):
        async with ClientSession(read, write) as session:
            logger.debug("[run_graph] MCP session opened — initializing")
            await session.initialize()
            logger.debug("[run_graph] MCP session initialized")

            # Convert MCP tools → LangChain Tool objects
            mcp_tools = await load_mcp_tools(session)
            logger.debug(
                "[run_graph] Loaded %d MCP tools: %s",
                len(mcp_tools),
                [getattr(t, "name", str(t)) for t in mcp_tools],
            )

            llm = ChatOpenAI(model="gpt-4o", temperature=0)
            logger.debug("[run_graph] LLM initialized (model=gpt-4o)")

            graph = _build_state_graph(llm, mcp_tools)
            logger.debug("[run_graph] State graph compiled")

            initial_state: AgentState = {
                "messages": [HumanMessage(content=question)],
                "plan": Plan(intent="Code execution", steps=[]),
                "current_step_index": 0,
                "schema_context": "",
                "generated_code": "",
                "retry_count": 0,
                "ast_violation": False,
                "final_answer": "",
                "datasets": {},
                "sql_execution_output": None,
                "python_execution_output": None,
                "execution_error": None,
            }

            logger.debug("[run_graph] Invoking graph | question=%r", question)
            result = await graph.ainvoke(initial_state)

            final_answer = result.get("final_answer", "")
            logger.debug(
                "[run_graph] Graph execution complete | final_answer_len=%d",
                len(final_answer),
            )
            return result


def _build_state_graph(llm, mcp_tools):
    logger.debug("[_build_state_graph] Building state graph")
    graph = StateGraph(AgentState)

    # ── Nodes ─────────────────────────────────────────────────────────────────
    graph.add_node("planner", PlannerNode(llm, mcp_tools))
    graph.add_node("code_gen", CodeGenNode(llm))
    graph.add_node("ast_eval", ast_eval_node)
    graph.add_node("code_exec", CodeExecNode(mcp_tools))
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

    # ast_eval → safe: proceed to execution
    #           → retry: violation found, retries remaining — send to error_correction
    #           → give_up: violation found, budget exhausted — terminate
    graph.add_conditional_edges(
        "ast_eval",
        ast_eval_router,
        {
            "safe": "code_exec",
            "retry": "error_correction",
            "give_up": "fallback_failure",
        },
    )

    # code_exec → retry / give up / advance
    graph.add_conditional_edges(
        "code_exec",
        code_exec_router,
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

    compiled = graph.compile()
    logger.debug("[_build_state_graph] Graph compiled with %d nodes", 9)
    return compiled
