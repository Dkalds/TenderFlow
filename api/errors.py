"""Manejo de errores RFC 7807 y deprecación de rutas.

Registrar los manejadores con ``register_exception_handlers(app)`` en la
creación de la app; marcar una ruta deprecada con ``deprecate_route``.
"""

from __future__ import annotations

from datetime import UTC, date, datetime, timedelta
from email.utils import format_datetime
from typing import Any

from fastapi import FastAPI, HTTPException, Request, Response
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
        # `**extra_headers` acepta cualquier nombre, así que pasar un campo del
        # modelo —`instance=...`— no era un error: se convertía en un header
        # HTTP y el campo se quedaba en `None`, fuera del body. Además metía la
        # URL cruda (con los bytes que mandó el cliente) en un header, que es
        # donde reventaba el transporte. Se detecta aquí en vez de confiar en
        # que nadie repita la confusión.
        colisiones = sorted(set(extra_headers) & set(type(self).model_fields))
        if colisiones:
            raise TypeError(
                f"{colisiones} son campos de ProblemDetail, no headers: pasalos al "
                "constructor. `.response()` sólo acepta headers HTTP extra."
            )
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


def problem_422(errors: list[dict[str, Any]], instance: str | None = None) -> ProblemDetail:
    return ProblemDetail(
        type="https://licitaciones-sap/errors/validation-error",
        title="Unprocessable Entity",
        status=422,
        detail="La solicitud contiene datos inválidos.",
        instance=instance,
        errors=errors,
    )


def problem_429(limit: int, window: int) -> ProblemDetail:
    return ProblemDetail(
        type="https://licitaciones-sap/errors/rate-limit-exceeded",
        title="Too Many Requests",
        status=429,
        detail=f"Límite de {limit} requests por {window}s excedido.",
    )


def problem_500(
    detail: str = "Error interno del servidor.", instance: str | None = None
) -> ProblemDetail:
    return ProblemDetail(
        type="https://licitaciones-sap/errors/internal-server-error",
        title="Internal Server Error",
        status=500,
        detail=detail,
        instance=instance,
    )


def problem_503(detail: str = "Servicio temporalmente no disponible.") -> ProblemDetail:
    return ProblemDetail(
        type="https://licitaciones-sap/errors/service-unavailable",
        title="Service Unavailable",
        status=503,
        detail=detail,
    )


# ── Deprecación de rutas (C8.1) ──────────────────────────────────────────────

#: Ventana mínima entre anunciar la deprecación y apagar la ruta.
#:
#: Noventa días es lo que tarda un consumidor externo en enterarse, planificar y
#: desplegar. La ventana es del **contrato**, no del calendario de quien
#: deprecia: acortarla convierte el aviso en un incidente ajeno.
DEPRECATION_WINDOW_DAYS = 90


def sunset_anunciado(sunset: date, *, anunciado: date | None = None) -> date:
    """Valida y devuelve una fecha de apagado. Se llama **al declararla**.

    Se ejecuta en tiempo de import del módulo que define la constante, así que
    un plazo demasiado corto rompe el arranque —donde se ve— y no una request
    de un usuario.

    Args:
        sunset: Día a partir del cual la ruta puede dejar de existir.
        anunciado: Día en que se anunció la deprecación. Por defecto, hoy. Se
            pasa explícito para que una fecha declarada hace meses siga siendo
            válida cuando la ventana ya se consumió: lo que la política exige es
            que hubiera 90 días **desde el anuncio**, no que sigan quedando.

    Raises:
        ValueError: Si entre el anuncio y el apagado no cabe la ventana.
    """
    origen = anunciado or datetime.now(UTC).date()
    if sunset - origen < timedelta(days=DEPRECATION_WINDOW_DAYS):
        raise ValueError(
            f"sunset={sunset.isoformat()} deja menos de {DEPRECATION_WINDOW_DAYS} días "
            f"desde {origen.isoformat()}. La ventana de deprecación es del contrato, "
            f"no del calendario de quien deprecia."
        )
    return sunset


def deprecate_route(
    response: Response,
    *,
    sunset: date,
    successor: str | None = None,
    rfc: str | None = None,
) -> None:
    """Marca la respuesta como perteneciente a una ruta deprecada.

    Escribe tres cabeceras estándar, y la que faltaba era la segunda:

    - ``Deprecation: true`` (RFC 8594) — la ruta está deprecada.
    - ``Sunset: <fecha HTTP>`` (RFC 8594) — **cuándo deja de responder**. Hasta
      2026-09 la única ruta deprecada emitía ``Deprecation`` sin ``Sunset``, que
      le dice al cliente que se prepare sin decirle para cuándo.
    - ``Link`` — la sucesora (``rel="successor-version"``) y, si la hay, la RFC
      que documenta la retirada (``rel="deprecation"``).

    La ventana de 90 días **no** se comprueba aquí: se comprueba al declarar la
    fecha, con ``sunset_anunciado()``. La diferencia importa. Validar en cada
    request convertiría una fecha que se acerca en un 500 en producción: el día
    que faltasen 89 días, la ruta deprecada dejaría de responder de golpe — que
    es exactamente el apagón sin aviso que esta política existe para evitar.

    Args:
        response: La ``Response`` de FastAPI de la operación.
        sunset: Día a partir del cual la ruta puede dejar de existir.
        successor: Ruta que la sustituye, si existe.
        rfc: URL o ruta de la RFC de retirada.
    """
    response.headers["Deprecation"] = "true"
    # RFC 8594 exige formato de fecha HTTP (IMF-fixdate), no ISO-8601.
    response.headers["Sunset"] = format_datetime(
        datetime.combine(sunset, datetime.min.time(), tzinfo=UTC), usegmt=True
    )

    enlaces: list[str] = []
    if successor:
        enlaces.append(f'<{successor}>; rel="successor-version"')
    if rfc:
        enlaces.append(f'<{rfc}>; rel="deprecation"')
    if enlaces:
        response.headers["Link"] = ", ".join(enlaces)


# ── Exception handlers ───────────────────────────────────────────────────────


def _instance(request: Request) -> str:
    """URL de la petición, garantizada ASCII imprimible.

    ASGI entrega el path decodificado como latin-1, así que ``str(request.url)``
    puede arrastrar los bytes crudos que mandó el cliente e incluso surrogates.
    Eso rompe a quien luego los codifique: el transporte al serializar headers,
    o el encoder JSON al escribir el body. El ``instance`` de RFC 7807 sirve
    para identificar la petición, no para devolverla byte a byte, así que se
    escapa lo que no sea ASCII en vez de propagarlo.
    """
    return str(request.url).encode("ascii", "backslashreplace").decode("ascii")


def register_exception_handlers(app: FastAPI) -> None:
    """Registra manejadores globales de excepciones con respuestas RFC 7807."""

    @app.exception_handler(HTTPException)
    async def http_exception_handler(request: Request, exc: HTTPException) -> JSONResponse:
        status_code = exc.status_code
        constructors = {
            400: lambda: problem_400(str(exc.detail), _instance(request)),
            401: lambda: problem_401(str(exc.detail)),
            403: lambda: problem_403(str(exc.detail)),
            404: lambda: problem_404(str(exc.detail)),
            409: lambda: problem_409(str(exc.detail)),
            # Preserva el detail del route handler (e.g. presupuesto LLM agotado).
            # El rate-limit middleware no pasa por aquí: construye su JSONResponse
            # propia con límite/ventana reales.
            429: lambda: ProblemDetail(
                type="https://licitaciones-sap/errors/too-many-requests",
                title="Too Many Requests",
                status=429,
                detail=str(exc.detail),
            ),
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
                instance=_instance(request),
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
        return problem_422(errors, _instance(request)).response()

    @app.exception_handler(ValueError)
    async def value_error_handler(request: Request, exc: ValueError) -> JSONResponse:
        """Convierte un ``ValueError`` no capturado en 400 **sin** su mensaje.

        Antes se reflejaba ``str(exc)`` verbatim. Los ``ValueError`` de
        ``shared.ssrf`` distinguen "DNS resolution failed", "no global" y "no
        incluido en la allowlist", así que dar de alta webhooks se convertía en
        un escáner de red interna con respuestas de oráculo. El mensaje real
        solo va al log estructurado, igual que en ``generic_exception_handler``.

        Quien necesite que el usuario lea un motivo concreto debe lanzar
        ``HTTPException(status_code=400, detail=...)`` explícitamente: así el
        detalle se publica por decisión deliberada y no por descarte.
        """
        from observability.logging import get_logger

        log = get_logger(__name__)
        log.warning(
            "value_error_masked",
            path=str(request.url.path),
            exc_type=type(exc).__name__,
            error=str(exc),
        )
        return problem_400(
            "La solicitud contiene un valor inválido.", _instance(request)
        ).response()

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
        return problem_500(instance=_instance(request)).response()
