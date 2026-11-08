"""Application errors and a consistent public error envelope."""
from fastapi.responses import JSONResponse


class APIError(Exception):
    def __init__(self, status_code, code, message):
        super().__init__(message)
        self.status_code = status_code
        self.code = code
        self.message = message


def error_response(request, status_code, code, message, details=None):
    return JSONResponse(status_code=status_code, content={
        "error": {"code": code, "message": message, "details": details},
        "request_id": getattr(request.state, "request_id", None),
    })
