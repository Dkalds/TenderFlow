"""La forma única del error de la API: RFC 9457 ``application/problem+json``.

Vivía en ``api/errors.py`` como modelo **y** como fábrica de respuestas, y por
eso nunca llegó al esquema OpenAPI: ninguna ruta lo declaraba, así que el
cliente generado (``web/src/generated/api.d.ts`` y el SDK de
``release-sdk.yml``) no tenía un tipo de error que parsear, aunque en tiempo de
ejecución todos los errores ya salían con esta forma. Aquí queda el dato; la
respuesta HTTP sigue construyéndose en ``api/errors.py``, que es la capa que
conoce Starlette. La convención entera está en ``docs/api-design.md``.

RFC 9457 sustituye a RFC 7807 sin cambiar el formato: los cuerpos que la API
emitía con la 7807 ya cumplen la 9457.
"""

from __future__ import annotations

from pydantic import BaseModel, Field


class ErrorDeValidacion(BaseModel):
    """Un campo que no pasó la validación (extensión ``errors`` del 422)."""

    loc: list[str | int] = Field(description='Ruta del campo: ``["query", "limit"]``.')
    msg: str = Field(description="Qué falla, legible por una persona.")
    type: str = Field(description="Código estable del fallo (``greater_than_equal``…).")


class ProblemDetail(BaseModel):
    """Cuerpo de **toda** respuesta de error de la API (RFC 9457).

    ``type`` es un URI opaco y estable por condición (namespace histórico
    ``licitaciones-sap``, ADR-015): un cliente decide por él, no por el texto
    de ``detail``. ``title`` es la frase HTTP en inglés del estándar y
    ``detail`` el motivo en español para la persona.
    """

    type: str = Field(
        default="about:blank",
        description="URI opaco y estable de la condición; es lo que un cliente compara.",
    )
    title: str = Field(description="Frase HTTP del código (``Not Found``…).")
    status: int = Field(description="El mismo código HTTP de la respuesta.")
    detail: str | None = Field(default=None, description="Motivo en español, para la persona.")
    instance: str | None = Field(default=None, description="URL de la petición que falló.")
    errors: list[ErrorDeValidacion] | None = Field(
        default=None, description="Solo en el 422: un elemento por campo inválido."
    )


#: Nombre corto de la convención (``docs/api-design.md``). Es **la misma clase**
#: y no una subclase: el componente OpenAPI se sigue llamando ``ProblemDetail``.
Error = ProblemDetail
