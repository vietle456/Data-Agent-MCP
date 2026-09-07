from typing import TypedDict, Annotated
from langchain_core.messages import BaseMessage
from langgraph.graph.message import add_messages

from app.models.execution_output import ExecutionOutput
from app.models.plan import Plan


class AgentState(TypedDict):
    messages: Annotated[list[BaseMessage], add_messages]
    plan: Plan
    current_step_index: int
    schema_context: str
    generated_code: str
    retry_count: int
    execution_output: ExecutionOutput
    ast_violation: bool
    final_answer: str
