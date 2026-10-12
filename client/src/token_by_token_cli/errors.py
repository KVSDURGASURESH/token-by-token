from __future__ import annotations


class ClientError(Exception):
    def __init__(self, code: str, message: str, exit_status: int = 3) -> None:
        self.code = code
        self.message = message
        self.exit_status = exit_status
        super().__init__(f"{code}: {message}")

