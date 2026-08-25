from pathlib import Path
from mcp import StdioServerParameters

# MCP server parameters
MCP_SERVER_PARAMS = StdioServerParameters(
    command="python", args=["app/mcp/mcp_server.py"]
)

WORKSPACE_PATH = Path(__file__).resolve()

# Local storage path
DB_PATH = WORKSPACE_PATH / "storage" / "database.duckdb"
SCHEMA_CACHE_PATH = WORKSPACE_PATH / "storage" / "cache"
