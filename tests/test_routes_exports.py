"""Tests del motor de exportación de ``api/routes/exports.py``.

**Reescrito el 2026-09-03.** Este fichero cubría la máquina de jobs asíncronos
(``POST /exports`` → 202, sondeo con ``GET /exports/{id}``, ``DELETE``) y su
almacén ``_store``: un ``dict`` de proceso con los bytes del PDF dentro. Esa
superficie se retiró —el 202 aceptaba un trabajo que, con más de una instancia
o tras cualquier reinicio, el sondeo no volvía a encontrar— y la exportación a
PDF pasó a ``GET /exports/download?format=pdf``, síncrona.

Los tests viejos no se han tirado a la basura: cada garantía que seguía viva se
reescribió sobre el camino síncrono, que es donde hoy corre el mismo trabajo.

- ``test_gc_store_removes_expired`` → :func:`TestDescargaPdfSincrona.
  test_la_exportacion_no_deja_el_pdf_en_memoria_del_proceso`. El GC existía
  para que los PDFs terminados no crecieran sin límite; sin almacén no hay TTL
  que respetar, pero la memoria sigue teniendo que liberarse.
- ``test_run_export_success`` → ``test_la_descarga_devuelve_el_pdf_construido_
  con_las_filas`` y ``test_los_filtros_de_la_peticion_llegan_a_la_consulta``.
- ``test_run_export_error`` → ``test_un_fallo_de_la_consulta_no_devuelve_un_
  pdf_a_medias``. El worker capturaba la excepción y la dejaba en
  ``status="error"`` esperando un sondeo; ahora el fallo viaja al cliente.
- ``TestExportsEndpoints`` (404/403/202 por dueño del job) → lo cubre
  ``tests/test_unit_export_idor.py``, ya reescrito sobre el diseño de hoy:
  el aislamiento entre usuarios (issue #50) sigue siendo obligatorio.

Se añade además la garantía que **introduce** el cambio y que el diseño viejo
tenía regalada: el worker asíncrono maquetaba el PDF en un ``BackgroundTask``,
fuera del event loop por construcción. Al volverse síncrono ese trabajo puede
acabar sobre el loop y parar la API entera (auditoría 2026-08-07, ver
``tests/test_async_handlers_no_blocking_io.py``); aquí se comprueba ejecutando
el handler, no leyendo su AST.

Los tests llaman a la corrutina del handler directamente en vez de pasar por
``TestClient``: lo que se prueba es el motor —consulta, maquetación, respuesta—
y así no hace falta Postgres. El enrutado se cubre en ``tests/test_exports.py``
y la autenticación en ``tests/test_unit_export_idor.py``.
"""

from __future__ import annotations

import asyncio
import threading
from collections.abc import Iterable
from typing import Any
from unittest.mock import patch

import pytest

import api.routes.exports as exports_mod

# El handler declara sus parámetros con `Query(...)` como valor por defecto:
# llamándolo a mano esos defaults son objetos `Query`, no `None` (solo FastAPI
# los resuelve). Se pasan todos explícitos para que lo que llegue a la consulta
# sea exactamente lo que dice el test.
_SIN_FILTROS: dict[str, Any] = {
    "q": None,
    "estado": None,
    "ccaa": None,
    "tecnologia": None,
    "fecha_desde": None,
    "fecha_hasta": None,
    "limit": 10000,
}


def _descargar(formato: str = "pdf", **filtros: Any) -> tuple[Any, bytes]:
    """Ejecuta ``download_export`` y devuelve ``(respuesta, cuerpo)``.

    El cuerpo se agota desde ``body_iterator`` porque la respuesta es un
    ``StreamingResponse``: el fichero va en la propia respuesta, que es
    justamente lo que sustituyó al 202 + sondeo.
    """
    parametros = {**_SIN_FILTROS, **filtros, "format": formato}

    async def _correr() -> tuple[Any, bytes]:
        respuesta = await exports_mod.download_export(**parametros, _user={"user_id": 1})
        cuerpo = b"".join([trozo async for trozo in respuesta.body_iterator])
        return respuesta, cuerpo

    return asyncio.run(_correr())


def _valores(contenedor: Any) -> Iterable[Any]:
    """Valores de un contenedor mutable, sea mapping o secuencia."""
    return contenedor.values() if isinstance(contenedor, dict) else contenedor


def _contenedores_de_modulo() -> dict[str, int]:
    """Tamaño de las estructuras mutables de nivel de módulo, por nombre.

    Mismo criterio que ``_estado_mutable_de_modulo`` en
    ``tests/test_unit_export_idor.py``: las constantes en MAYÚSCULAS son
    configuración declarada, no estado acumulado entre peticiones.
    """
    return {
        nombre: len(valor)
        for nombre, valor in vars(exports_mod).items()
        if isinstance(valor, (dict, list, set))
        and not nombre.startswith("__")
        and not nombre.isupper()
    }


class TestBuildPdf:
    """``_build_pdf``: el maquetador, único superviviente literal del F5."""

    def test_build_pdf_empty_rows(self):
        from api.routes.exports import _build_pdf

        result = _build_pdf([], "Test Title")
        assert isinstance(result, bytes)
        assert len(result) > 0
        assert result[:5] == b"%PDF-"

    def test_build_pdf_with_rows(self):
        from api.routes.exports import _build_pdf

        rows = [
            {"col_a": "value1", "col_b": "value2"},
            {"col_a": "value3", "col_b": "value4"},
        ]
        result = _build_pdf(rows, "Test Export")
        assert result[:5] == b"%PDF-"


class TestDescargaPdfSincrona:
    """El camino que sustituyó a ``POST /exports`` + sondeo."""

    def test_la_descarga_devuelve_el_pdf_construido_con_las_filas(self):
        """Sucesor de ``test_run_export_success``.

        Lo que antes acababa en ``_store[job]["pdf"]`` esperando un sondeo va
        ahora en el cuerpo de la respuesta, con su tipo y su nombre de fichero.
        """
        with (
            patch.object(exports_mod, "_build_pdf", return_value=b"%PDF-fake") as construir,
            patch("services.licitaciones.fetch_for_pdf", return_value=[{"a": 1}]) as consultar,
        ):
            respuesta, cuerpo = _descargar(ccaa="Madrid")

        assert cuerpo == b"%PDF-fake"
        assert respuesta.media_type == "application/pdf"
        assert ".pdf" in respuesta.headers["content-disposition"]
        assert consultar.call_count == 1
        # El título llevaba la CCAA cuando el filtro venía puesto; sigue igual.
        filas, titulo = construir.call_args.args
        assert filas == [{"a": 1}]
        assert "Madrid" in titulo

    def test_los_filtros_de_la_peticion_llegan_a_la_consulta(self):
        """La exportación exporta lo que se pidió, no el corpus entero.

        El worker viejo solo propagaba ``ccaa``/``estado``/``q``; el camino
        síncrono acepta además tecnología, rango de fechas y ``limit``. Si
        alguno se pierde por el camino el usuario se descarga otra cosa —y con
        ``limit`` de por medio, potencialmente 50 000 filas de más.
        """
        with (
            patch.object(exports_mod, "_build_pdf", return_value=b"%PDF-fake"),
            patch("services.licitaciones.fetch_for_pdf", return_value=[]) as consultar,
        ):
            _descargar(
                ccaa="Madrid",
                estado="PUB",
                q="SAP",
                tecnologia="S/4HANA",
                fecha_desde="2026-01-01",
                fecha_hasta="2026-06-30",
                limit=250,
            )

        assert consultar.call_args.kwargs == {
            "ccaa": "Madrid",
            "estado": "PUB",
            "q": "SAP",
            "tecnologia": "S/4HANA",
            "fecha_desde": "2026-01-01",
            "fecha_hasta": "2026-06-30",
            "limit": 250,
        }

    def test_un_fallo_de_la_consulta_no_devuelve_un_pdf_a_medias(self):
        """Sucesor de ``test_run_export_error``.

        El worker capturaba la excepción y la dejaba en ``status="error"``
        para que alguien la sondease. Sin sondeo, la única forma de que el
        fallo llegue al cliente es propagarse: si se tragase la excepción, la
        descarga sería un fichero vacío con un 200 encima.
        """
        with (
            patch.object(exports_mod, "_build_pdf", return_value=b"%PDF-fake") as construir,
            patch("services.licitaciones.fetch_for_pdf", side_effect=RuntimeError("boom")),
            pytest.raises(RuntimeError, match="boom"),
        ):
            _descargar()

        assert not construir.called, "se maquetó un PDF con una consulta que falló"

    def test_el_pdf_no_se_maqueta_sobre_el_event_loop(self):
        """La maquetación corre en el threadpool, no en el bucle de eventos.

        El diseño viejo tenía esto gratis: reportlab corría en un
        ``BackgroundTask``. Al hacer la descarga síncrona el mismo trabajo
        —hasta 50 000 filas más la maquetación— pasa a poder ejecutarse sobre
        el event loop, y ahí no se atiende ninguna otra petición del proceso
        mientras dura (incidente de la auditoría 2026-08-07).

        ``tests/test_async_handlers_no_blocking_io.py`` lo vigila leyendo el
        AST; esto lo comprueba ejecutando, comparando el hilo en el que se
        maqueta con el del bucle.
        """
        hilos: dict[str, int] = {"test": threading.get_ident()}

        def _maquetar(rows: list[dict[str, Any]], title: str) -> bytes:
            hilos["maquetado"] = threading.get_ident()
            return b"%PDF-fake"

        def _consultar(**_kwargs: Any) -> list[dict[str, Any]]:
            hilos["consulta"] = threading.get_ident()
            return []

        with (
            patch.object(exports_mod, "_build_pdf", side_effect=_maquetar),
            patch("services.licitaciones.fetch_for_pdf", side_effect=_consultar),
        ):
            _descargar()

        assert hilos["maquetado"] != hilos["test"], (
            "reportlab maquetó el PDF en el hilo del event loop: la API entera "
            "se para mientras dura la exportación"
        )
        assert hilos["consulta"] != hilos["test"], (
            "la consulta de exportación corrió en el hilo del event loop"
        )
        # Un solo salto al threadpool por petición: es el idioma de
        # api/concurrency.py (agrupar el trabajo síncrono en `_render` y
        # despacharlo con un único `await run_db`), no N saltos sueltos.
        assert hilos["consulta"] == hilos["maquetado"]

    def test_la_exportacion_no_deja_el_pdf_en_memoria_del_proceso(self):
        """Sucesor de ``test_gc_store_removes_expired``.

        El GC existía porque los PDFs terminados vivían en un ``dict`` de
        módulo y había que echarlos a los 15 minutos. Sin almacén no hay TTL
        que comprobar, pero sí la garantía que el TTL servía: la memoria de una
        exportación se libera al terminar la petición y dos descargas seguidas
        no hacen crecer nada del proceso.
        """
        marca = b"%PDF-marca-de-retencion"
        antes = _contenedores_de_modulo()

        with (
            patch.object(exports_mod, "_build_pdf", return_value=marca),
            patch("services.licitaciones.fetch_for_pdf", return_value=[{"a": 1}]),
        ):
            _descargar()
            _descargar()

        assert _contenedores_de_modulo() == antes, (
            "una descarga hizo crecer una estructura de nivel de módulo: vuelve "
            "el almacén de proceso que motivó la retirada de los jobs"
        )
        retienen = [
            nombre
            for nombre, valor in vars(exports_mod).items()
            if isinstance(valor, (dict, list, set))
            and any(elemento is marca or elemento == marca for elemento in _valores(valor))
        ]
        assert not retienen, f"el módulo retiene los bytes del PDF exportado: {retienen}"
