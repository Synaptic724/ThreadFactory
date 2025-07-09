class OperationCanceledError(Exception):
    """Exception raised when a cooperative operation is canceled."""

    def __init__(self, message="The operation was canceled."):
        self.message = message
        super().__init__(self.message)
