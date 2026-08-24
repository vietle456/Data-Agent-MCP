import pytest
from unittest.mock import AsyncMock, MagicMock
from langchain_core.messages import AIMessage, HumanMessage
from app.agent.nodes import PlannerNode
from app.agent.graph import _build_state_graph


@pytest.mark.asyncio
async def test_planner_node_init():
    mock_tool = MagicMock()
    mock_tool.name = "inspect_db_schema"
    mock_tool.ainvoke = AsyncMock(return_value="table orders (id int, amount float)")

    mock_llm = MagicMock()
    mock_llm.ainvoke = AsyncMock(
        return_value=AIMessage(
            content='{"plan": {"intent": "Code execution", "steps": []}}'
        )
    )

    node = PlannerNode(mock_llm, [mock_tool])
    assert node._schema_tool == mock_tool

    state = {"messages": [HumanMessage(content="test question")]}
    result = await node(state)

    assert result["schema_context"] == "table orders (id int, amount float)"
    assert result["plan"] == {"intent": "Code execution", "steps": []}
    mock_tool.ainvoke.assert_awaited_once_with({})
    mock_llm.ainvoke.assert_awaited_once()


def test_build_state_graph():
    mock_llm = MagicMock()
    mock_tools = [MagicMock(name="inspect_db_schema")]
    graph = _build_state_graph(mock_llm, mock_tools)
    assert graph is not None
