from typing import TypedDict, Annotated, Any
from langchain_core.messages import BaseMessage
from langgraph.graph.message import add_messages


class AgentState(TypedDict):
    messages: Annotated[list[BaseMessage], add_messages]
    plan: dict[str, Any]          # {"intent": str, "steps": list[{"type": str, "description": str}]}
    current_step_index: int
    schema_context: str
    generated_code: str
    retry_count: int
    execution_output: dict[str, Any]
    ast_violation: bool
    final_answer: str
