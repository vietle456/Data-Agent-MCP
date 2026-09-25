from typing import Annotated, TypedDict

from langchain_core.messages import BaseMessage
from langgraph.graph.message import add_messages

from app.schemas.artifact_schema import DatasetArtifact
from app.schemas.execution_output import PythonExecutionResult, SQLExecutionResult
from app.schemas.plan import Plan


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
    final_answer: str
