from typing import Annotated, TypedDict

from app.models.artifact_schema import DatasetArtifact
from app.models.execution_output import PythonExecutionResult, SQLExecutionResult
from app.models.plan import Plan
from langchain_core.messages import BaseMessage
from langgraph.graph.message import add_messages


class AgentState(TypedDict):
    messages: Annotated[list[BaseMessage], add_messages]
    plan: Plan
    current_step_index: int
    schema_context: str
    generated_code: str
    retry_count: int
    ast_violation: bool
    datasets: dict[str, DatasetArtifact]
    sql_execution_output: SQLExecutionResult | None
    python_execution_output: PythonExecutionResult | None
    execution_error: str | None
    summary: str | None
    final_answer: str
