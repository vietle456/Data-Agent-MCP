from pydantic import BaseModel


class ExecutionOutput(BaseModel):
    success: bool
    error: str | None
    artifacts: list[str]  # files produced (Python only)
    data: dict | None  # structured result (SQL: {columns, rows, summary})
    stdout: str | None  # raw stdout (Python sandbox only)
