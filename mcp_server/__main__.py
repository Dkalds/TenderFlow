"""Arranque del servidor MCP: ``python -m mcp_server``.

En ``ENV=prod`` aborta si falta alguna variable obligatoria
(:func:`~mcp_server.servidor.validar_configuracion`); en desarrollo avisa y
arranca igual. Escucha en ``$PORT`` (Render lo fija; 8080 por defecto).
"""

from __future__ import annotations

import os

import uvicorn

from config import settings
from mcp_server.servidor import crear_app, validar_configuracion
from observability import configure_logging
from observability.logging import get_logger

log = get_logger("mcp_server")  # con `-m`, __name__ sería "__main__"


def main() -> None:
    configure_logging()
    faltan = validar_configuracion()
    if faltan:  # las que faltan y las mal formadas
        if settings.ENV == "prod":
            raise SystemExit("Configuración del MCP incompleta o inválida: " + ", ".join(faltan))
        log.warning("mcp_configuracion_incompleta", faltan=faltan)
    app = crear_app()
    uvicorn.run(
        app,
        host="0.0.0.0",  # noqa: S104  # nosec B104 — contenedor: escucha en todas las interfaces
        port=int(os.environ.get("PORT", "8080")),
        # Sin la configuración de logging de uvicorn: sus logs van al handler
        # estructurado que acaba de instalar `configure_logging`.
        log_config=None,
        # Sin log de acceso: la línea de `/oauth/google/callback` llevaría `code` y
        # `state` en la query string. Las tools ya dejan su propio log `mcp_tool`.
        access_log=False,
    )


if __name__ == "__main__":
    main()
