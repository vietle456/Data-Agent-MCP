import json
from typing import Optional
from pathlib import Path
import duckdb

from app.core.config import SCHEMA_CACHE_PATH


class DuckDBEngine:
    """Service wrapper for DuckDB analytical database operations."""

    def __init__(self, db_path: Optional[str | Path] = None):
        # In-memory database or disk-persisted .duckdb file
        self.db_path = db_path or ":memory:"
        self.conn = duckdb.connect(database=self.db_path)

    def load_dataset(self, file_path: Path, table_name: str) -> bool:
        """Dynamically ingests CSV or Parquet into DuckDB table."""
        suffix = file_path.suffix.lower()
        if suffix == ".csv":
            query = (
                f"CREATE TABLE '{table_name}' AS SELECT * FROM read_csv('{file_path}');"
            )
        elif suffix == ".parquet":
            query = f"CREATE TABLE '{table_name}' AS SELECT * FROM read_parquet('{file_path}');"
        else:
            raise ValueError(f"Unsupported file format: {suffix}")

        self.conn.execute(query)
        self._save_schema_cache(table_name)
        return True

    def list_tables(self) -> list[str]:
        tables = self.conn.execute("SHOW TABLES").fetchall()
        return [table[0] for table in tables]

    def describe_table(self, table_name: str) -> list[dict]:
        rows = self.conn.execute(f"DESCRIBE {table_name}").fetchall()

        return [
            {
                "name": row[0],
                "type": row[1],
            }
            for row in rows
        ]

    def sample_table(
        self,
        table_name: str,
        limit: int = 3,
    ) -> list[dict]:
        columns = self.describe_table(table_name)

        rows = self.conn.execute(f"SELECT * FROM {table_name} LIMIT {limit}").fetchall()

        column_names = [column["name"] for column in columns]

        return [dict(zip(column_names, row)) for row in rows]

    def execute_read_query(self, query: str) -> str:
        """Executes read-only SQL query with a safety LIMIT clause."""
        # Safety: force LIMIT 500 if not present
        if "LIMIT" not in query.upper():
            query = f"SELECT * FROM ({query}) AS subq LIMIT 500"

        try:
            result = self.conn.execute(query).df()  # returns pandas DataFrame

            return json.dumps(
                {
                    "success": True,
                    "row_count": len(result),
                    "columns": list(result.columns),
                    "data": result.head(10).to_dict(orient="records"),  # first 10 rows
                    "summary": result.describe().to_dict(),
                }
            )
        except Exception as e:  # pylint: disable=broad-except
            return json.dumps({"success": False, "error": str(e)})

    def close(self):
        """Close database connection"""
        self.conn.close()

    def _save_schema_cache(self, table_name: str) -> None:
        """
        Writes a JSON schema cache file for the given table to storage/cache/.
        The file is named <table_name>.json and contains the table name and
        its column names with their DuckDB types.
        """
        columns = self.describe_table(table_name)
        schema = {
            "table": table_name,
            "columns": columns,  # [{"name": ..., "type": ...}, ...]
        }

        SCHEMA_CACHE_PATH.mkdir(parents=True, exist_ok=True)
        cache_file = SCHEMA_CACHE_PATH / f"{table_name}.json"
        cache_file.write_text(json.dumps(schema, indent=2), encoding="utf-8")
