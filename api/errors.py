"""Manejo de errores RFC 7807 (Problem Details for HTTP APIs).

Registrar con ``register_exception_handlers(app)`` en la creación de la app.
"""

from __future__ import annotations

from typing import Any

from fastapi import FastAPI, HTTPException, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from pydantic import BaseModel


class ProblemDetail(BaseModel):
    """RFC 7807 Problem Details.

    https://datatracker.ietf.org/doc/html/rfc7807
    """

    type: str = "about:blank"
    title: str
    status: int
    detail: str | None = None
    instance: str | None = None
    # Campos de extensión opcionales
    errors: list[dict[str, Any]] | None = None

    def response(self, **extra_headers: str) -> JSONResponse:
        headers = {"Content-Type": "application/problem+json"}
        headers.update(extra_headers)
        return JSONResponse(
            status_code=self.status,
            content=self.model_dump(exclude_none=True),
            headers=headers,
        )


# ── Constructores de errores estándar ────────────────────────────────────────


def problem_400(detail: str, instance: str | None = None) -> ProblemDetail:
    return ProblemDetail(
        type="https://licitaciones-sap/errors/bad-request",
        title="Bad Request",
        status=400,
        detail=detail,
        instance=instance,
    )


def problem_401(detail: str = "API key ausente o inválida.") -> ProblemDetail:
    return ProblemDetail(
        type="https://licitaciones-sap/errors/unauthorized",
        title="Unauthorized",
        status=401,
        detail=detail,
    )


def problem_403(detail: str = "Acceso denegado. Scope insuficiente.") -> ProblemDetail:
    return ProblemDetail(
        type="https://licitaciones-sap/errors/forbidden",
        title="Forbidden",
        status=403,
        detail=detail,
    )


def problem_404(detail: str = "Recurso no encontrado.") -> ProblemDetail:
    return ProblemDetail(
        type="https://licitaciones-sap/errors/not-found",
        title="Not Found",
        status=404,
        detail=detail,
    )


def problem_409(detail: str) -> ProblemDetail:
    return ProblemDetail(
        type="https://licitaciones-sap/errors/conflict",
        title="Conflict",
        status=409,
        detail=detail,
    )


def problem_422(errors: list[dict[str, Any]]) -> ProblemDetail:
    return ProblemDetail(
        type="https://licitaciones-sap/errors/validation-error",
        title="Unprocessable Entity",
        status=422,
        detail="La solicitud contiene datos inválidos.",
        errors=errors,
    )


def problem_429(limit: int, window: int) -> ProblemDetail:
    return ProblemDetail(
        type="https://licitaciones-sap/errors/rate-limit-exceeded",
        title="Too Many Requests",
        status=429,
        detail=f"Límite de {limit} requests por {window}s excedido.",
    )


def problem_500(detail: str = "Error interno del servidor.") -> ProblemDetail:
    return ProblemDetail(
        type="https://licitaciones-sap/errors/internal-server-error",
        title="Internal Server Error",
        status=500,
        detail=detail,
    )


def problem_503(detail: str = "Servicio temporalmente no disponible.") -> ProblemDetail:
    return ProblemDetail(
        type="https://licitaciones-sap/errors/service-unavailable",
        title="Service Unavailable",
        status=503,
        detail=detail,
    )


# ── Exception handlers ───────────────────────────────────────────────────────


def register_exception_handlers(app: FastAPI) -> None:
    """Registra manejadores globales de excepciones con respuestas RFC 7807."""

    @app.exception_handler(HTTPException)
    async def http_exception_handler(request: Request, exc: HTTPException) -> JSONResponse:
        status_code = exc.status_code
        constructors = {
            400: lambda: problem_400(str(exc.detail), str(request.url)),
            401: lambda: problem_401(str(exc.detail)),
            403: lambda: problem_403(str(exc.detail)),
            404: lambda: problem_404(str(exc.detail)),
            409: lambda: problem_409(str(exc.detail)),
            429: lambda: problem_429(120, 60),
            500: lambda: problem_500(str(exc.detail)),
            503: lambda: problem_503(str(exc.detail)),
        }
        builder = constructors.get(status_code)
        if builder:
            problem = builder()
        else:
            problem = ProblemDetail(
                title=f"HTTP {status_code}",
                status=status_code,
                detail=str(exc.detail),
                instance=str(request.url),
            )
        extra: dict[str, str] = {}
        if status_code == 401:
            extra["WWW-Authenticate"] = "ApiKey"
        if exc.headers:
            extra.update(exc.headers)
        return problem.response(**extra)

    @app.exception_handler(RequestValidationError)
    async def validation_exception_handler(
        request: Request, exc: RequestValidationError
    ) -> JSONResponse:
        errors = [
            {
                "loc": list(e.get("loc", [])),
                "msg": e.get("msg", ""),
                "type": e.get("type", ""),
            }
            for e in exc.errors()
        ]
        return problem_422(errors).response(instance=str(request.url))

    @app.exception_handler(ValueError)
    async def value_error_handler(request: Request, exc: ValueError) -> JSONResponse:
        return problem_400(str(exc), str(request.url)).response()

    @app.exception_handler(Exception)
    async def generic_exception_handler(request: Request, exc: Exception) -> JSONResponse:
        from observability.logging import get_logger

        log = get_logger(__name__)
        log.error(
            "unhandled_exception",
            path=str(request.url.path),
            exc_type=type(exc).__name__,
            error=str(exc),
        )
        return problem_500().response(instance=str(request.url))
