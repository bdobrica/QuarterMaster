class DomainError(Exception):
    """Only sanitized, human-actionable messages belong here."""

    def __init__(self, message: str, status: int = 422):
        self.message = message
        self.status = status
        super().__init__(message)
