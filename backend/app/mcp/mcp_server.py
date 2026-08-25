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
def list_tables(ctx: Context) -> list[str]:
    """
    Returns a list of all table names available in the database.
    """
    db = ctx.lifespan_context["db"]
    return db.list_tables()


@mcp.tool()
def describe_table(ctx: Context, table_name: str) -> list[dict]:
    """
    Returns the column names and data types for a given table.
    Args:
        table_name: The exact name of the table to inspect (use list_tables to get valid names).
    """
    db = ctx.lifespan_context["db"]
    return db.describe_table(table_name)


@mcp.tool()
def sample_table(ctx: Context, table_name: str, limit: int = 3) -> list[dict]:
    """
    Returns a small sample of rows from a table to understand its structure and content.
    Args:
        table_name: The exact name of the table to sample (use list_tables to get valid names).
        limit: Number of rows to return. Defaults to 3.
    """
    db = ctx.lifespan_context["db"]
    return db.sample_table(table_name, limit)


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
