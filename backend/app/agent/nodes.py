import asyncio
import json
from langchain_core.messages import SystemMessage, HumanMessage, AIMessage

from app.agent.state import AgentState
from app.models.plan import Plan
from app.models.execution_output import ExecutionOutput
from app.core.logging_config import get_logger
from app.prompt.prompt import (
    PLANNER_SYSTEM_PROMPT,
    CODE_GEN_SYSTEM_PROMPT,
    ERROR_CORRECTION_SYSTEM_PROMPT,
    FINAL_ANSWER_SYSTEM_PROMPT,
)
from app.core.security_ast import validate_python, validate_sql

logger = get_logger(__name__)

# ── Constants ────────────────────────────────────────────────────────────────

MAX_RETRIES = 3  # maximum code-correction attempts per step
MCP_TOOL_TIMEOUT = 60  # seconds before an MCP tool call is considered hung


class _Route:
    """Route name constants used by all router functions."""

    DIRECT = "direct"
    EXECUTE = "execute"
    SAFE = "safe"
    RETRY = "retry"
    GIVE_UP = "give_up"
    SUCCESS = "success"
    DONE = "done"
    NEXT_STEP = "next_step"


# ── Nodes ─────────────────────────────────────────────────────────────────────


class PlannerNode:
    """Analyzes question + schema to produce a structured JSON analytical plan."""

    def __init__(self, llm, mcp_tools: list | None = None) -> None:
        self.llm = llm
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

        if self._schema_tool:
            logger.debug("[PlannerNode] Fetching DB schema via MCP tool")
            schema_context = await self._schema_tool.ainvoke({})
            logger.debug("[PlannerNode] Schema fetched (%d chars)", len(schema_context))
        else:
            logger.warning(
                "[PlannerNode] No schema tool found — proceeding without schema"
            )
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

        try:
            plan_data = json.loads(content)
            plan = Plan.model_validate(plan_data["plan"])
        except (json.JSONDecodeError, KeyError, ValueError) as exc:
            logger.error(
                "[PlannerNode] Failed to parse plan response: %s\nRaw content: %r",
                exc,
                content,
            )
            raise RuntimeError(
                f"Planner LLM returned an invalid JSON plan: {exc}"
            ) from exc

        logger.debug(
            "[PlannerNode] Plan generated | intent=%r, steps=%d",
            plan.intent,
            len(plan.steps),
        )
        for i, step in enumerate(plan.steps):
            logger.debug(
                "[PlannerNode]   Step %d: [%s] %s",
                i + 1,
                step.type,
                step.description,
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
        self.llm = llm

    async def __call__(self, state: AgentState) -> dict:
        steps = state["plan"].steps
        index = state["current_step_index"]
        current_step = steps[index]

        logger.debug(
            "[CodeGenNode] START | step=%d/%d type=%r desc=%r",
            index + 1,
            len(steps),
            current_step.type,
            current_step.description,
        )

        # Surface previous execution output so the LLM can reference prior results
        exec_out = state["execution_output"]
        prev_output = (
            {"data": exec_out.data, "stdout": exec_out.stdout}
            if (exec_out.data or exec_out.stdout)
            else None
        )

        steps_json = json.dumps([s.model_dump() for s in steps], indent=2)
        context_message = HumanMessage(content=f"""
Schema:
{state['schema_context']}

Full plan ({len(steps)} steps):
{steps_json}

Current step to implement (step {index + 1} of {len(steps)}):
  Type: {current_step.type}
  Description: {current_step.description}

Previous step output (if any):
{prev_output or "No previous step output"}
""")

        messages = [
            SystemMessage(content=CODE_GEN_SYSTEM_PROMPT),
            context_message,
        ]

        logger.debug("[CodeGenNode] Calling LLM to generate code")
        response = await self.llm.ainvoke(messages)
        generated = response.content.strip()

        # Strip markdown fences that the LLM may emit despite prompt instructions
        if generated.startswith("```"):
            lines = generated.splitlines()
            # Drop the opening fence line (e.g. ```sql / ```python / ```)
            lines = lines[1:]
            # Drop the closing fence line if present
            if lines and lines[-1].strip() == "```":
                lines = lines[:-1]
            generated = "\n".join(lines).strip()

        logger.debug(
            "[CodeGenNode] Code generated (%d chars):\n%s",
            len(generated),
            generated,
        )

        return {"generated_code": generated, "messages": [response]}


class CodeExecNode:
    """Executes a plan step via MCP tools — SQL queries via execute_sql_query,
    Python scripts via execute_python_analysis (Docker sandbox)."""

    def __init__(self, mcp_tools) -> None:
        self.mcp_tools = mcp_tools

    def _get_tool(self, name: str):
        tool = next(
            (t for t in self.mcp_tools if getattr(t, "name", None) == name),
            None,
        )
        if tool is None:
            raise RuntimeError(f"MCP tool '{name}' not found")
        return tool

    async def __call__(self, state: AgentState) -> dict:
        step_index = state["current_step_index"]
        step_num = step_index + 1
        current_step = state["plan"].steps[step_index]
        code = state["generated_code"]
        step_type = current_step.type  # "SQL_QUERY" | "PYTHON"

        logger.debug("[CodeExecNode] START | step=%d | type=%s", step_num, step_type)
        logger.debug("[CodeExecNode] Submitting to executor:\n%s", code)

        if step_type == "SQL_QUERY":
            sql_tool = self._get_tool("execute_sql_query")
            logger.debug("[CodeExecNode] Invoking MCP tool 'execute_sql_query'")
            raw_result = await asyncio.wait_for(
                sql_tool.ainvoke({"query": code}),
                timeout=MCP_TOOL_TIMEOUT,
            )

            # Coerce to str — MCP adapter should return a string, but guard
            # against future adapter changes that may return a list or dict.
            if not isinstance(raw_result, str):
                raw_result = json.dumps(raw_result)
            sql_result = json.loads(json.loads(raw_result)[0]["text"])

            success = sql_result.get("success", True)
            error_msg = sql_result.get("error", "") if not success else ""
            rows = sql_result.get("data", [])

            logger.debug(
                "[CodeExecNode] SQL execution complete | success=%s, rows=%s",
                success,
                len(rows) if success else "N/A",
            )
            if error_msg:
                logger.debug("[CodeExecNode] SQL error:\n%s", error_msg)

            execution_output = ExecutionOutput(
                success=success,
                error=error_msg if error_msg else None,
                artifacts=[],
                data=sql_result.get("data"),
                stdout=(
                    json.dumps(sql_result.get("data", sql_result), indent=2)
                    if success
                    else None
                ),
            )

        else:  # PYTHON
            python_tool = self._get_tool("execute_python_analysis")
            logger.debug("[CodeExecNode] Invoking MCP tool 'execute_python_analysis'")
            # Call the MCP tool — goes through the MCP protocol to the server process
            # which runs the code in Docker
            raw_result = await asyncio.wait_for(
                python_tool.ainvoke({"code_str": code}),
                timeout=MCP_TOOL_TIMEOUT,
            )
            # logger.debug("[CodeExecNode] Python raw result: %s", raw_result)

            # Coerce to str — guard against adapter changes.
            if not isinstance(raw_result, str):
                raw_result = json.dumps(raw_result)
            result = json.loads(json.loads(raw_result)[0]["text"])
            logger.debug("[CodeExecNode] Python json loads result: %s", result)

            exit_code = result.get("exit_code", -1)
            stdout = result.get("stdout", "") or ""
            stderr = result.get("stderr", "") or ""
            artifacts = result.get("artifacts", [])

            logger.debug(
                "[CodeExecNode] Python execution complete | exit_code=%d, stdout_len=%d, stderr_len=%d, artifacts=%s",
                exit_code,
                len(stdout),
                len(stderr),
                artifacts,
            )
            if stdout:
                logger.debug(
                    "[CodeExecNode] stdout:\n%s",
                    stdout[:500] + ("..." if len(stdout) > 500 else ""),
                )
            if stderr:
                logger.debug("[CodeExecNode] stderr:\n%s", stderr)

            # Build ExecutionOutput inside the branch — avoids re-reading from
            # `result` after the branch and eliminates the risk of key mismatches.
            execution_output = ExecutionOutput(
                success=exit_code == 0,
                error=stderr if stderr else None,
                artifacts=artifacts,
                data=result.get("data"),
                stdout=stdout,
            )

        # Add execution output to messages so the next code_gen step can reference it
        output_message = HumanMessage(
            content=f"Step {step_num} execution output:\n{execution_output.stdout or ''}"
        )

        return {
            "execution_output": execution_output,
            "messages": [output_message],
        }


class ErrorCorrectionNode:
    """Uses the LLM to fix failing code; stores the corrected code directly in state."""

    def __init__(self, llm) -> None:
        self.llm = llm

    async def __call__(self, state: AgentState) -> dict:
        steps = state["plan"].steps
        current_step = steps[state["current_step_index"]]
        error = state["execution_output"].error
        retry_count = state["retry_count"] + 1

        logger.debug(
            "[ErrorCorrectionNode] START | step=%d, attempt=%d/3",
            state["current_step_index"] + 1,
            retry_count,
        )
        logger.debug("[ErrorCorrectionNode] Error to fix:\n%s", error)

        messages = [
            SystemMessage(content=ERROR_CORRECTION_SYSTEM_PROMPT),
            HumanMessage(content=f"""
Original question:
{state['messages'][0].content}

Schema:
```
{state['schema_context']}
```

Step being corrected:
  Type: {current_step.type}
  Description: {current_step.description}

Code that was executed:
```
{state['generated_code']}
```

Error (attempt {retry_count} of 3):
```
{error}
```
"""),
        ]

        logger.debug("[ErrorCorrectionNode] Calling LLM for corrected code")
        response = await self.llm.ainvoke(messages)
        corrected = response.content.strip()

        # Strip markdown fences that the LLM may emit despite prompt instructions
        if corrected.startswith("```"):
            lines = corrected.splitlines()
            lines = lines[1:]
            if lines and lines[-1].strip() == "```":
                lines = lines[:-1]
            corrected = "\n".join(lines).strip()

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
        # Find the ANSWER step — for direct answers the planner should emit one,
        # but fall back to the first step if the plan is unexpectedly malformed.
        answer_step = next(
            (s for s in state["plan"].steps if s.type == "ANSWER"),
            state["plan"].steps[0],
        )

        logger.debug(
            "[DirectAnswerNode] START | guidance=%r",
            answer_step.description[:120],
        )

        messages = [
            SystemMessage(content=FINAL_ANSWER_SYSTEM_PROMPT),
            HumanMessage(content=f"""
User question:
{state['messages'][0].content}

Guidance:
{answer_step.description}
"""),
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
        exec_out = state["execution_output"]
        # Serialise structured data to a JSON string — prevents None from
        # rendering literally as the string 'None' inside the LLM prompt.
        data_str = (
            json.dumps(exec_out.data, indent=2) if exec_out.data is not None else ""
        )
        exec_str = exec_out.stdout or ""

        artifact_note = ""
        if exec_out.artifacts:
            artifact_note = "\n\nGenerated artifacts (charts/files):\n" + "\n".join(
                exec_out.artifacts
            )

        messages = [
            SystemMessage(content=FINAL_ANSWER_SYSTEM_PROMPT),
            HumanMessage(content=f"""
User question:
{state['messages'][0].content}

Execution outputs:
{data_str}{exec_str}{artifact_note}
"""),
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
    current_step_index = state["current_step_index"]
    code_type = state["plan"].steps[current_step_index].type

    logger.debug("[ast_eval_node] Validating generated code with AST security checker")
    try:
        if code_type == "SQL_QUERY":
            validate_sql(state["generated_code"])
        elif code_type == "PYTHON":
            validate_python(state["generated_code"])
        else:
            raise ValueError(f"Unknown code type: {code_type!r}")
        logger.debug("[ast_eval_node] Code passed AST validation — safe to execute")
        return {"ast_violation": False}
    except SyntaxError as e:
        # ast.parse() raises SyntaxError on malformed code (e.g. leftover markdown fences).
        # Treat this as a correctable violation so the graph routes to error_correction.
        logger.warning("[ast_eval_node] SyntaxError during AST parse: %s", e)
        return {
            "ast_violation": True,
            "execution_output": ExecutionOutput(
                success=False,
                error=f"SyntaxError in generated code: {str(e)}",
                data=None,
                stdout=None,
                artifacts=[],
            ),
        }
    except ValueError as e:
        logger.warning("[ast_eval_node] AST VIOLATION detected: %s", e)
        return {
            "ast_violation": True,
            "execution_output": ExecutionOutput(
                success=False,
                error=f"AST Security Violation: {str(e)}",
                data=None,
                stdout=None,
                artifacts=[],
            ),
        }


def advance_step(state: AgentState) -> dict:
    """Increments the step index and resets the retry counter after a successful execution."""
    new_index = state["current_step_index"] + 1
    total_steps = len(state["plan"].steps)
    logger.debug(
        "[advance_step] Step %d/%d complete — moving to step index %d",
        state["current_step_index"] + 1,
        total_steps,
        new_index,
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
        "final_answer": f"I was unable to complete this analysis after {MAX_RETRIES} attempts. Please rephrase your question.",
        "messages": [AIMessage(content="Analysis failed after maximum retries.")],
    }


# ── Router functions ──────────────────────────────────────────────────────────


def plan_intent(state: AgentState) -> str:
    """After planning: route to direct answer or start the code execution loop."""
    intent = state["plan"].intent
    route = _Route.DIRECT if intent == "Direct answer" else _Route.EXECUTE
    logger.debug("[plan_intent] intent=%r → route=%r", intent, route)
    return route


def ast_eval_router(state: AgentState) -> str:
    """After AST eval: route to code execution, error correction, or give up.

    Returns:
        "safe"     - code passed validation, proceed to code_exec
        "retry"    - violation found but retries remain, send to error_correction
        "give_up"  - violation found and retry budget exhausted, send to fallback
    """
    if not state.get("ast_violation", False):
        logger.debug("[ast_eval_router] ast_violation=False → safe")
        return _Route.SAFE

    retry_count = state["retry_count"]
    route = _Route.RETRY if retry_count < MAX_RETRIES else _Route.GIVE_UP
    logger.debug(
        "[ast_eval_router] ast_violation=True, retry_count=%d → %r",
        retry_count,
        route,
    )
    return route


def code_exec_router(state: AgentState) -> str:
    """After code execution: advance on success, retry on failure, or give up."""
    success = state["execution_output"].success
    retry_count = state["retry_count"]

    if success:
        route = _Route.SUCCESS
    elif retry_count < MAX_RETRIES:
        route = _Route.RETRY
    else:
        route = _Route.GIVE_UP

    logger.debug(
        "[code_exec_router] retry_count=%d → route=%r",
        retry_count,
        route,
    )
    return route


def step_router(state: AgentState) -> str:
    """After advancing the step index: loop back to code_gen or finish."""
    steps = state["plan"].steps
    index = state["current_step_index"]

    if index >= len(steps):
        logger.debug("[step_router] All steps complete → done")
        return _Route.DONE

    # ANSWER steps are synthesized by final_formatting, not executed as code
    if steps[index].type == "ANSWER":
        logger.debug("[step_router] Next step is ANSWER type → done (final_formatting)")
        return _Route.DONE

    logger.debug(
        "[step_router] Continuing to step %d/%d → next_step",
        index + 1,
        len(steps),
    )
    return _Route.NEXT_STEP
