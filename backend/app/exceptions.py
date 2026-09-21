"""Custom application exceptions."""


class SqlResultTooLargeError(Exception):
    """Raised when a SQL query returns more rows than the allowed limit."""

    def __init__(self, row_count: int, limit: int = 100) -> None:
        self.row_count = row_count
        self.limit = limit
        super().__init__(
            f"SQL result is too large: got {row_count} rows, limit is {limit}"
        )
