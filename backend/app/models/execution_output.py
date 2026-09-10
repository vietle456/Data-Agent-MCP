from pydantic import BaseModel


class ExecutionOutput(BaseModel):
    success: bool


class SQLExecutionResult(ExecutionOutput):
    row_count: int | None
    columns: list[dict]
    preview: list[dict]
    error: str | None


class PythonExecutionResult(ExecutionOutput):
    stdout: str
    stderr: str | None
    artifacts: list[str]
