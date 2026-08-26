import sys
from pathlib import Path
from mcp import StdioServerParameters

# Root of the backend package (the directory that contains the 'app' package)
_BACKEND_DIR = Path(__file__).resolve().parent.parent.parent

# MCP server parameters
# sys.executable ensures the subprocess uses the same venv Python as the parent,
# so all dependencies (fastmcp, duckdb, etc.) are available.
# '-m app.mcp.mcp_server' (module mode) also ensures 'app.*' imports resolve
# correctly against the backend directory on sys.path.
MCP_SERVER_PARAMS = StdioServerParameters(
    command=sys.executable,
    args=["-m", "app.mcp.mcp_server"],
    cwd=str(_BACKEND_DIR),
)

# Local storage path
DB_PATH = _BACKEND_DIR / "storage" / "database.duckdb"
