from fastmcp import FastMCP, Context
from fastmcp.server.lifespan import lifespan

from app.services.duckdb_engine import DuckDBEngine
from app.core.security_ast import validate_code
from app.core.config import DB_PATH
from app.services.sandbox_runner import SandboxRunner


@lifespan
async def app_lifespan(server):
    db = DuckDBEngine(DB_PATH)
    try:
        yield {"db": db}
    finally:
        db.close()


mcp = FastMCP("Data Agent MCP Server", lifespan=app_lifespan)


@mcp.tool()
def inspect_db_schema(ctx: Context) -> str:
    """
    Returns all table names, column names/types, and 3 sample rows.
    The agent MUST call this before writing any SQL or Python query.
    """
    db = ctx.lifespan_context["db"]
    return db.get_schema_summary()


@mcp.tool()
def execute_sql_query(ctx: Context, query: str) -> str:
    """
    Executes a read-only SQL query against DuckDB.
    Results are automatically capped at 500 rows.
    Args:
        query: A valid SQL SELECT statement.
    """
    db = ctx.lifespan_context["db"]
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
