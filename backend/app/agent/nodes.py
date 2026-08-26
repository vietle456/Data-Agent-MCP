import json
from langchain_core.messages import SystemMessage, HumanMessage, AIMessage

from app.agent.state import AgentState
from app.core.logging_config import get_logger
from app.prompt.prompt import (
    PLANNER_SYSTEM_PROMPT,
    CODE_GEN_SYSTEM_PROMPT,
    ERROR_CORRECTION_SYSTEM_PROMPT,
    FINAL_ANSWER_SYSTEM_PROMPT,
)
from app.core.security_ast import validate_code

logger = get_logger(__name__)

# ── Nodes ─────────────────────────────────────────────────────────────────────


class PlannerNode:
    """Analyzes question + schema to produce a structured JSON analytical plan."""

    def __init__(self, llm, mcp_tools: list | None = None) -> None:
        self.llm = llm
        # Resolve inspect_db_schema once at construction to avoid per-call lookup
        self._schema_tool = next(
            (
                t
                for t in (mcp_tools or [])
                if getattr(t, "name", None) == "inspect_db_schema"
            ),
            None,
        )

    async def __call__(self, state: AgentState) -> dict:
        question = state["messages"][-1].content
        logger.debug("[PlannerNode] START | question=%r", question)

        # Pre-fetch schema directly — no LLM round-trip needed for this
        if self._schema_tool:
            logger.debug("[PlannerNode] Fetching DB schema via MCP tool")
            schema_context = await self._schema_tool.ainvoke({})
            logger.debug(
                "[PlannerNode] Schema fetched (%d chars)", len(schema_context)
            )
        else:
            logger.warning("[PlannerNode] No schema tool found — proceeding without schema")
            schema_context = ""

        # ainvoke may return a list of content items (LangChain MCP adapter behaviour)
        # — coerce to a plain string before any further processing.
        if not isinstance(schema_context, str):
            schema_context = "\n".join(
                item.text if hasattr(item, "text") else str(item)
                for item in schema_context
            )
            logger.debug(
                "[PlannerNode] schema_context coerced from list to str (%d chars)",
                len(schema_context),
            )

        # Detect empty schema — an empty JSON object '{}' or whitespace means no tables exist
        _schema_stripped = schema_context.strip()
        schema_is_empty = not _schema_stripped or _schema_stripped in ("{}", "[]")
        if schema_is_empty and schema_context:
            logger.warning(
                "[PlannerNode] Schema returned but contains no tables (%r) — "
                "injecting NO_SCHEMA_AVAILABLE notice into prompt",
                _schema_stripped,
            )

        if schema_is_empty:
            schema_section = (
                "\n\nDatabase schema: NO_SCHEMA_AVAILABLE\n"
                "The database returned no tables or an empty schema. "
                "Any question that requires querying data CANNOT be answered."
            )
        else:
            schema_section = f"\n\nDatabase schema:\n{schema_context}"

        question_with_schema = (
            f"User question: {state['messages'][-1].content}{schema_section}"
        )

        messages = [
            SystemMessage(content=PLANNER_SYSTEM_PROMPT),
            HumanMessage(content=question_with_schema),
        ]

        logger.debug("[PlannerNode] Calling LLM to generate execution plan")
        plan_response = await self.llm.ainvoke(messages)
        content = plan_response.content.strip()
        if content.startswith("```"):
            lines = content.splitlines()
            if lines and lines[0].startswith("```"):
                lines = lines[1:]
            if lines and lines[-1].startswith("```"):
                lines = lines[:-1]
            content = "\n".join(lines).strip()

        plan_data = json.loads(content)
        plan = plan_data["plan"]
        num_steps = len(plan.get("steps", []))
        intent = plan.get("intent", "unknown")

        logger.debug(
            "[PlannerNode] Plan generated | intent=%r, steps=%d",
            intent,
            num_steps,
        )
        for i, step in enumerate(plan.get("steps", [])):
            logger.debug(
                "[PlannerNode]   Step %d: [%s] %s",
                i + 1,
                step.get("type", "?"),
                step.get("description", ""),
            )

        return {
            "schema_context": schema_context,
            "messages": [plan_response],
            "plan": plan,
            "current_step_index": 0,
            "retry_count": 0,
        }


class CodeGenNode:
    """Generates SQL or Python code for the current plan step only."""

    def __init__(self, llm) -> None:
        self.llm = llm  # plain LLM — no tool binding needed for code generation

    async def __call__(self, state: AgentState) -> dict:
        steps = state["plan"]["steps"]
        index = state["current_step_index"]
        current_step = steps[index]

        logger.debug(
            "[CodeGenNode] START | step=%d/%d type=%r desc=%r",
            index + 1,
            len(steps),
            current_step.get("type"),
            current_step.get("description"),
        )

        # Surface previous execution output so the LLM can reference prior results
        prev_output = (
            state["execution_output"].get("stdout", "")
            if state["execution_output"]
            else ""
        )
        if prev_output:
            logger.debug(
                "[CodeGenNode] Previous step stdout (%d chars): %s",
                len(prev_output),
                prev_output[:200] + ("..." if len(prev_output) > 200 else ""),
            )

        context_message = HumanMessage(
            content=f"""
Schema:
{state['schema_context']}

Full plan ({len(steps)} steps):
{json.dumps(steps, indent=2)}

Current step to implement (step {index + 1} of {len(steps)}):
  Type: {current_step['type']}
  Description: {current_step['description']}

Previous step output (if any):
{prev_output or "None"}
"""
        )

        messages = [
            SystemMessage(content=CODE_GEN_SYSTEM_PROMPT),
            context_message,
        ]

        logger.debug("[CodeGenNode] Calling LLM to generate code")
        response = await self.llm.ainvoke(messages)
        generated = response.content.strip()

        logger.debug(
            "[CodeGenNode] Code generated (%d chars):\n%s",
            len(generated),
            generated,
        )

        return {"generated_code": generated, "messages": [response]}


class SandboxExecNode:
    """Runs generated code in the Docker sandbox via the MCP execute tool."""

    def __init__(self, mcp_tools) -> None:
        self.mcp_tools = mcp_tools

    async def __call__(self, state: AgentState) -> dict:
        code = state["generated_code"]
        step_num = state["current_step_index"] + 1

        logger.debug("[SandboxExecNode] START | step=%d", step_num)
        logger.debug(
            "[SandboxExecNode] Submitting code to sandbox:\n%s", code
        )

        exec_tool = next(
            (
                t
                for t in self.mcp_tools
                if getattr(t, "name", None) == "execute_python_analysis"
            ),
            None,
        )

        if exec_tool is None:
            raise RuntimeError("MCP tool 'execute_python_analysis' not found")

        logger.debug("[SandboxExecNode] Invoking MCP tool 'execute_python_analysis'")
        # Call the MCP tool — goes through the MCP protocol to the server process
        # which runs the code in Docker
        raw_result = await exec_tool.ainvoke({"code": code})

        # raw_result is a JSON string (MCP tools return strings)
        result = json.loads(raw_result)

        exit_code = result.get("exit_code", -1)
        stdout = result.get("stdout", "")
        stderr = result.get("stderr", "")
        artifacts = result.get("artifacts", [])

        logger.debug(
            "[SandboxExecNode] Execution complete | exit_code=%d, stdout_len=%d, stderr_len=%d, artifacts=%s",
            exit_code,
            len(stdout),
            len(stderr),
            artifacts,
        )
        if stdout:
            logger.debug(
                "[SandboxExecNode] stdout:\n%s",
                stdout[:500] + ("..." if len(stdout) > 500 else ""),
            )
        if stderr:
            logger.debug("[SandboxExecNode] stderr:\n%s", stderr)

        # Add execution output to messages so the next code_gen step can reference it
        output_message = HumanMessage(
            content=f"Step {step_num} execution output:\n{stdout}"
        )

        return {
            "execution_output": result,
            "messages": [output_message],
        }


class ErrorCorrectionNode:
    """Uses the LLM to fix failing code; stores the corrected code directly in state."""

    def __init__(self, llm) -> None:
        self.llm = llm  # plain LLM — no tool binding needed

    async def __call__(self, state: AgentState) -> dict:
        steps = state["plan"]["steps"]
        current_step = steps[state["current_step_index"]]
        stderr = state["execution_output"].get("stderr", "Unknown error")
        retry_count = state["retry_count"] + 1

        logger.debug(
            "[ErrorCorrectionNode] START | step=%d, attempt=%d/3",
            state["current_step_index"] + 1,
            retry_count,
        )
        logger.debug("[ErrorCorrectionNode] Error to fix:\n%s", stderr)

        messages = [
            SystemMessage(content=ERROR_CORRECTION_SYSTEM_PROMPT),
            HumanMessage(
                content=f"""
Original question:
{state['messages'][0].content}

Schema:
{state['schema_context']}

Step being corrected:
  Type: {current_step['type']}
  Description: {current_step['description']}

Code that was executed:
{state['generated_code']}

Error (attempt {retry_count} of 3):
{stderr}
"""
            ),
        ]

        logger.debug("[ErrorCorrectionNode] Calling LLM for corrected code")
        response = await self.llm.ainvoke(messages)
        corrected = response.content.strip()

        logger.debug(
            "[ErrorCorrectionNode] Corrected code (%d chars):\n%s",
            len(corrected),
            corrected,
        )

        return {
            "retry_count": retry_count,
            "generated_code": corrected,
            "messages": [response],
        }


class DirectAnswerNode:
    """Handles 'Direct answer' intent — synthesizes a response without any code execution."""

    def __init__(self, llm) -> None:
        self.llm = llm

    async def __call__(self, state: AgentState) -> dict:
        # For direct answers the plan has a single ANSWER step with the synthesis description
        answer_step = state["plan"]["steps"][0]

        logger.debug(
            "[DirectAnswerNode] START | guidance=%r",
            answer_step.get("description", "")[:120],
        )

        messages = [
            SystemMessage(content=FINAL_ANSWER_SYSTEM_PROMPT),
            HumanMessage(
                content=f"""
User question:
{state['messages'][0].content}

Guidance:
{answer_step['description']}
"""
            ),
        ]

        logger.debug("[DirectAnswerNode] Calling LLM for direct answer")
        response = await self.llm.ainvoke(messages)

        logger.debug(
            "[DirectAnswerNode] Answer generated (%d chars)", len(response.content)
        )

        return {
            "final_answer": response.content,
            "messages": [AIMessage(content=response.content)],
        }


class FinalFormattingNode:
    """Synthesizes all execution outputs into a professional final answer via LLM."""

    def __init__(self, llm) -> None:
        self.llm = llm

    async def __call__(self, state: AgentState) -> dict:
        execution_summary = state["execution_output"].get("stdout", "")
        artifacts = state["execution_output"].get("artifacts", [])

        logger.debug(
            "[FinalFormattingNode] START | stdout_len=%d, artifacts=%s",
            len(execution_summary),
            artifacts,
        )

        artifact_note = ""
        if artifacts:
            artifact_note = "\n\nGenerated artifacts (charts/files):\n" + "\n".join(
                artifacts
            )

        messages = [
            SystemMessage(content=FINAL_ANSWER_SYSTEM_PROMPT),
            HumanMessage(
                content=f"""
User question:
{state['messages'][0].content}

Execution outputs:
{execution_summary}{artifact_note}
"""
            ),
        ]

        logger.debug("[FinalFormattingNode] Calling LLM to synthesize final answer")
        response = await self.llm.ainvoke(messages)

        logger.debug(
            "[FinalFormattingNode] Final answer generated (%d chars)",
            len(response.content),
        )

        return {
            "final_answer": response.content,
            "messages": [AIMessage(content=response.content)],
        }


def ast_eval_node(state: AgentState) -> dict:
    """Validates generated code safety before sandbox execution."""
    logger.debug("[ast_eval_node] Validating generated code with AST security checker")
    try:
        validate_code(state["generated_code"])
        logger.debug("[ast_eval_node] Code passed AST validation — safe to execute")
        return {"ast_violation": False}
    except ValueError as e:
        logger.warning("[ast_eval_node] AST VIOLATION detected: %s", e)
        return {
            "ast_violation": True,
            "execution_output": {
                "stdout": "",
                "stderr": f"AST Security Violation: {str(e)}",
                "exit_code": 1,
                "artifacts": [],
            },
        }


def advance_step(state: AgentState) -> dict:
    """Increments the step index and resets the retry counter after a successful execution."""
    new_index = state["current_step_index"] + 1
    total_steps = len(state["plan"].get("steps", []))
    logger.debug(
        "[advance_step] Step %d complete — advancing to step %d (total=%d)",
        state["current_step_index"] + 1,
        new_index + 1,
        total_steps,
    )
    return {
        "current_step_index": new_index,
        "retry_count": 0,
    }


def fallback_failure_node(state: AgentState) -> dict:  # pylint: disable=unused-argument
    """Terminal node when all retries are exhausted."""
    logger.error(
        "[fallback_failure_node] All retries exhausted for step %d — giving up",
        state["current_step_index"] + 1,
    )
    return {
        "final_answer": "I was unable to complete this analysis after 3 attempts. Please rephrase your question.",
        "messages": [AIMessage(content="Analysis failed after maximum retries.")],
    }


# ── Router functions ──────────────────────────────────────────────────────────


def plan_intent(state: AgentState) -> str:
    """After planning: route to direct answer or start the code execution loop."""
    intent = state["plan"].get("intent", "Code execution")
    route = "direct" if intent == "Direct answer" else "execute"
    logger.debug("[plan_intent] intent=%r → route=%r", intent, route)
    return route


def ast_eval_router(state: AgentState) -> str:
    """After AST eval: bypass sandbox and send to correction if a violation was found."""
    route = "violation" if state.get("ast_violation", False) else "safe"
    logger.debug("[ast_eval_router] ast_violation=%s → route=%r", state.get("ast_violation"), route)
    return route


def should_retry(state: AgentState) -> str:
    """After sandbox execution: advance on success, retry on failure, or give up."""
    exit_code = state["execution_output"].get("exit_code", 1)
    retry_count = state["retry_count"]

    if exit_code == 0:
        route = "success"
    elif retry_count < 3:
        route = "retry"
    else:
        route = "give_up"

    logger.debug(
        "[should_retry] exit_code=%d, retry_count=%d → route=%r",
        exit_code,
        retry_count,
        route,
    )
    return route


def step_router(state: AgentState) -> str:
    """After advancing the step index: loop back to code_gen or finish."""
    steps = state["plan"]["steps"]
    index = state["current_step_index"]

    if index >= len(steps):
        logger.debug("[step_router] All steps complete → done")
        return "done"

    # ANSWER steps are synthesized by final_formatting, not executed as code
    if steps[index]["type"] == "ANSWER":
        logger.debug("[step_router] Next step is ANSWER type → done (final_formatting)")
        return "done"

    logger.debug(
        "[step_router] Continuing to step %d/%d → next_step",
        index + 1,
        len(steps),
    )
    return "next_step"
