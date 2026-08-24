from fastmcp import FastMCP

from app.services.duckdb_engine import DuckDBEngine
from app.core.security_ast import validate_code
from app.services.sandbox_runner import SandboxRunner

mcp = FastMCP("Data Agent MCP Server")


@mcp.tool()
def inspect_db_schema() -> str:
    """
    Returns all table names, column names/types, and 3 sample rows.
    The agent MUST call this before writing any SQL or Python query.
    """
    with DuckDBEngine("storage/database.duckdb") as db:
        summary = db.get_schema_summary()
        return summary


@mcp.tool()
def execute_sql_query(query: str) -> str:
    """
    Executes a read-only SQL query against DuckDB.
    Results are automatically capped at 500 rows.
    Args:
        query: A valid SQL SELECT statement.
    """
    with DuckDBEngine("storage/database.duckdb") as db:
        query_result = db.execute_read_query(query)
        return query_result


@mcp.tool()
def execute_python_analysis(code_str: str) -> dict:
    """
    Validates Python code with AST safety checker, then runs it in Docker sandbox.
    Args:
        code: Raw Python script string to execute.
    """
    # AST check
    try:
        validate_code(code_str)
    except ValueError as e:
        return {
            "stdout": "",
            "stderr": f"AST Security Violation: {e}",
            "exit_code": 1,
            "artifacts": [],
        }

    # Docker sandbox execution
    result = SandboxRunner().execute(code_str)
    return result


if __name__ == "__main__":
    mcp.run()
