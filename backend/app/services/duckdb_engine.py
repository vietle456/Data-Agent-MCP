import json
from typing import Optional
from pathlib import Path
import duckdb


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
        return True

    def get_schema_summary(self) -> str:
        """Returns table names, columns, data types, and sample rows for LLM context."""
        tables = self.conn.execute("SHOW TABLES;").fetchall()
        schema_info = {}

        for (table_name,) in tables:
            # Get column names and types
            col_info = self.conn.execute(f"DESCRIBE {table_name};").fetchall()
            columns = [{"name": c[0], "type": c[1]} for c in col_info]

            # Fetch sample rows
            rows = self.conn.execute(f"SELECT * FROM {table_name} LIMIT 3").fetchall()
            samples = [dict(zip([c[0] for c in col_info], row)) for row in rows]

            schema_info[table_name] = {"columns": columns, "sample_rows": samples}
        return json.dumps(schema_info, indent=2)

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
        self.conn.close()
