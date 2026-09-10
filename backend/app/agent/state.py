from typing import TypedDict, Annotated
from langchain_core.messages import BaseMessage
from langgraph.graph.message import add_messages

from app.models.execution_output import SQLExecutionResult, PythonExecutionResult
from app.models.artifact_schema import DatasetArtifact
from app.models.plan import Plan


class AgentState(TypedDict):
    messages: Annotated[list[BaseMessage], add_messages]
    plan: Plan
    current_step_index: int
    schema_context: str
    generated_code: str
    retry_count: int
    ast_violation: bool
    datasets: dict[str, DatasetArtifact]

    # execution
    sql_execution_output: SQLExecutionResult | None
    python_execution_output: PythonExecutionResult | None
    execution_error: str | None
    final_answer: str
