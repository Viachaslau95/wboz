class RuntimeValidationError(Exception):
    """Raised when runtime validation fails."""


class DetailedValidationError(Exception):
    """Raised when validation details should be shown to users."""

    def __init__(self, message: str, details: str | None = None) -> None:
        self.details = details
        super().__init__(message if not details else f"{message}: {details}")
