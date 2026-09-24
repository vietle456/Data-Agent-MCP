from pydantic import BaseModel


class ExecutionOutput(BaseModel):
    success: bool


class SQLExecutionResult(ExecutionOutput):
    id: str
    row_count: int | None
    columns: list[dict]
    rows: list[dict]
    error: str | None
    summary: str | None


class PythonExecutionResult(ExecutionOutput):
    stdout: str
    stderr: str | None
    artifacts: list[str]
    analysis_result: dict | list | None
