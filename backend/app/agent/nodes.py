import json
from langchain_core.messages import SystemMessage, HumanMessage, AIMessage

from app.agent.state import AgentState
from app.prompt.prompt import (
    PLANNER_SYSTEM_PROMPT,
    CODE_GEN_SYSTEM_PROMPT,
    ERROR_CORRECTION_SYSTEM_PROMPT,
    FINAL_ANSWER_SYSTEM_PROMPT,
)
from app.core.security_ast import validate_code

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
        # Pre-fetch schema directly — no LLM round-trip needed for this
        schema_context = (
            await self._schema_tool.ainvoke({}) if self._schema_tool else ""
        )

        schema_section = (
            f"\n\nDatabase schema:\n{schema_context}" if schema_context else ""
        )

        question_with_schema = (
            f"User question: {state['messages'][-1].content}{schema_section}"
        )

        messages = [
            SystemMessage(content=PLANNER_SYSTEM_PROMPT),
            HumanMessage(content=question_with_schema),
        ]

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

        return {
            "schema_context": schema_context,
            "messages": [plan_response],
            "plan": plan_data["plan"],
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

        # Surface previous execution output so the LLM can reference prior results
        prev_output = (
            state["execution_output"].get("stdout", "")
            if state["execution_output"]
            else ""
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

        response = await self.llm.ainvoke(messages)

        return {"generated_code": response.content.strip(), "messages": [response]}


class SandboxExecNode:
    """Runs generated code in the Docker sandbox via the MCP execute tool."""

    def __init__(self, mcp_tools) -> None:
        self.mcp_tools = mcp_tools

    async def __call__(self, state: AgentState) -> dict:
        code = state["generated_code"]

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

        # Call the MCP tool — goes through the MCP protocol to the server process
        # which runs the code in Docker
        raw_result = await exec_tool.ainvoke({"code": code})

        # raw_result is a JSON string (MCP tools return strings)
        result = json.loads(raw_result)

        # Add execution output to messages so the next code_gen step can reference it
        stdout = result.get("stdout", "")
        output_message = HumanMessage(
            content=f"Step {state['current_step_index'] + 1} execution output:\n{stdout}"
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

        response = await self.llm.ainvoke(messages)

        return {
            "retry_count": retry_count,
            "generated_code": response.content.strip(),
            "messages": [response],
        }


class DirectAnswerNode:
    """Handles 'Direct answer' intent — synthesizes a response without any code execution."""

    def __init__(self, llm) -> None:
        self.llm = llm

    async def __call__(self, state: AgentState) -> dict:
        # For direct answers the plan has a single ANSWER step with the synthesis description
        answer_step = state["plan"]["steps"][0]

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

        response = await self.llm.ainvoke(messages)

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

        response = await self.llm.ainvoke(messages)

        return {
            "final_answer": response.content,
            "messages": [AIMessage(content=response.content)],
        }


def ast_eval_node(state: AgentState) -> dict:
    """Validates generated code safety before sandbox execution."""
    try:
        validate_code(state["generated_code"])
        return {"ast_violation": False}
    except ValueError as e:
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
    return {
        "current_step_index": state["current_step_index"] + 1,
        "retry_count": 0,
    }


def fallback_failure_node(state: AgentState) -> dict:  # pylint: disable=unused-argument
    """Terminal node when all retries are exhausted."""
    return {
        "final_answer": "I was unable to complete this analysis after 3 attempts. Please rephrase your question.",
        "messages": [AIMessage(content="Analysis failed after maximum retries.")],
    }


# ── Router functions ──────────────────────────────────────────────────────────


def plan_intent(state: AgentState) -> str:
    """After planning: route to direct answer or start the code execution loop."""
    intent = state["plan"].get("intent", "Code execution")
    return "direct" if intent == "Direct answer" else "execute"


def ast_eval_router(state: AgentState) -> str:
    """After AST eval: bypass sandbox and send to correction if a violation was found."""
    return "violation" if state.get("ast_violation", False) else "safe"


def should_retry(state: AgentState) -> str:
    """After sandbox execution: advance on success, retry on failure, or give up."""
    exit_code = state["execution_output"].get("exit_code", 1)

    if exit_code == 0:
        return "success"
    elif state["retry_count"] < 3:
        return "retry"
    else:
        return "give_up"


def step_router(state: AgentState) -> str:
    """After advancing the step index: loop back to code_gen or finish."""
    steps = state["plan"]["steps"]
    index = state["current_step_index"]

    if index >= len(steps):
        return "done"

    # ANSWER steps are synthesized by final_formatting, not executed as code
    if steps[index]["type"] == "ANSWER":
        return "done"

    return "next_step"
