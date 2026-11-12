"""Uniform API errors: every failure returns {"error": {"code", "message"}}."""
from __future__ import annotations

import logging

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse

log = logging.getLogger("talentsignal.api")


class AppError(Exception):
    def __init__(self, status: int, code: str, message: str):
        super().__init__(message)
        self.status = status
        self.code = code
        self.message = message


def install_error_handlers(app: FastAPI) -> None:
    @app.exception_handler(AppError)
    async def _app_error(_: Request, exc: AppError):
        return JSONResponse({"error": {"code": exc.code, "message": exc.message}}, status_code=exc.status)

    @app.exception_handler(RequestValidationError)
    async def _validation(_: Request, exc: RequestValidationError):
        details = [
            {"field": ".".join(str(p) for p in e.get("loc", [])[1:]), "message": e.get("msg", "")}
            for e in exc.errors()
        ]
        msg = "; ".join(f"{d['field']}: {d['message']}" for d in details[:5]) or "Invalid request."
        return JSONResponse({"error": {"code": "validation_error", "message": msg, "details": details}},
                            status_code=422)

    @app.exception_handler(Exception)
    async def _unexpected(request: Request, exc: Exception):
        log.exception("Unhandled error on %s %s", request.method, request.url.path)
        return JSONResponse({"error": {"code": "internal_error",
                                       "message": "An unexpected error occurred. It has been logged."}},
                            status_code=500)
