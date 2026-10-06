"""Application error carrying an HTTP status and a stable, machine-readable code.

Services raise ``AppError``; the API layer turns it into the standard envelope
``{code, message, request_id}``. Messages are written for the end user (FR-24).
"""


class AppError(Exception):
    def __init__(self, status: int, code: str, message: str) -> None:
        super().__init__(message)
        self.status = status
        self.code = code
        self.message = message


def not_found(code: str, message: str) -> AppError:
    return AppError(404, code, message)


def conflict(code: str, message: str) -> AppError:
    return AppError(409, code, message)


def unprocessable(code: str, message: str) -> AppError:
    return AppError(422, code, message)


DOCUMENT_NOT_FOUND = "This document does not exist. It may have been deleted."
CONVERSATION_NOT_FOUND = "This conversation does not exist."
