"""T5 — la bandeja «Próximas» del Radar: universo, orden y fecha prevista.

Lo que estos tests protegen es exactamente el criterio de aceptación del plan:
la bandeja lista **sólo `PRE | CPM` abiertos**, con **la fecha prevista cuando
existe** y **«sin fecha» cuando no**. Las tres partes se pueden romper en
silencio:

- el universo, añadiendo un código a mano en la ruta en vez de leerlo del
  catálogo (y desincronizándolo de `v91`);
- el orden, si alguien quita el `NULLS LAST` y la bandeja abre con un bloque de
  huecos delante de lo único que tiene fecha;
- la fecha, que es la que más fácil se fabrica: un `or ""`, un fallback a
  `fecha_limite` o una estimación desde la duración convertirían un «no lo sé»
  en una afirmación (ADR-014).

**No necesitan Postgres**: el SQL se captura en la frontera sin ejecutarlo, y la
ruta se llama directamente con el repositorio parcheado.
"""

from __future__ import annotations

import asyncio
import re
from typing import Any
from unittest.mock import MagicMock, patch

import pytest

from db.repositories.licitaciones import LicitacionRepository
from services.classification import ESTADOS_PRE_LICITACION
from shared.estados import ESTADOS_CERRADOS

# ── El universo ───────────────────────────────────────────────────────────


def test_el_universo_es_exactamente_anuncio_previo_y_consulta_preliminar() -> None:
    """Los dos códigos de `v91`, ni uno más.

    Si algún día se añade un tercero, este test obliga a decidirlo aquí en vez
    de descubrirlo cuando la bandeja empiece a listar expedientes con pliego.
    """
    assert set(ESTADOS_PRE_LICITACION) == {"PRE", "CPM"}


def test_ninguno_de_los_dos_es_un_estado_terminal() -> None:
    """«Abierto» y «previo» no pueden solaparse.

    El endpoint aplica los dos filtros a la vez: si uno de estos códigos
    entrara en `ESTADOS_CERRADOS`, la bandeja quedaría permanentemente vacía y
    parecería un fallo de datos, no una contradicción de criterios.
    """
    assert not set(ESTADOS_PRE_LICITACION) & set(ESTADOS_CERRADOS)


# ── El SQL ────────────────────────────────────────────────────────────────


def _capturar(**kwargs: Any) -> tuple[list[str], list[list[Any]]]:
    """Corre `proximas` con la conexión parcheada; devuelve los SQL emitidos."""
    sqls: list[str] = []
    params: list[list[Any]] = []

    def _execute(sql: str, valores: Any = None) -> MagicMock:
        sqls.append(" ".join(sql.split()))
        params.append(list(valores) if valores is not None else [])
        cursor = MagicMock()
        cursor.fetchone.return_value = (0, 0)
        return cursor

    ctx = MagicMock()
    ctx.__enter__.return_value.execute.side_effect = _execute

    with (
        patch("db.repositories.licitaciones.connect_read", return_value=ctx),
        patch("db.repositories.licitaciones.rows_to_dicts", return_value=[]),
    ):
        LicitacionRepository().proximas(estados=ESTADOS_PRE_LICITACION, **kwargs)

    return sqls, params


def test_el_where_pide_los_dos_estados_y_excluye_los_terminales() -> None:
    sqls, params = _capturar()

    for sql, valores in zip(sqls, params, strict=True):
        assert "licitaciones.estado IN" in sql
        # Los dos códigos van como parámetros, no interpolados.
        assert valores[:2] == ["PRE", "CPM"]
        # Y el juicio de «abierta» viaja con ellos: `coalesce(...) NOT IN (...)`
        # con los cinco terminales de `shared.estados`.
        assert "NOT IN" in sql
        for terminal in ESTADOS_CERRADOS:
            assert terminal in valores


def test_la_consulta_de_datos_trae_fecha_inicio() -> None:
    """Es la única razón por la que esta bandeja no sale del listado normal.

    `_SUMMARY_COLS` no lleva `fecha_inicio`, así que `GET /licitaciones` no
    puede responder «para cuándo está prevista» por mucho que se le filtre por
    estado. Si alguien reescribiera `proximas` sobre `list_paginated`, la
    columna desaparecería y la bandeja quedaría con «sin fecha» en todas las
    filas sin que nada fallara.
    """
    sqls, _ = _capturar()
    datos = sqls[-1]

    assert "licitaciones.fecha_inicio" in datos
    assert "SELECT licitaciones.id_externo" in datos


def test_los_denominadores_los_cuenta_el_servidor() -> None:
    """`total` y `con_fecha_prevista` salen del SQL, no de las filas servidas.

    Contar los `fecha_prevista` de la página para decir «X de Y» es el
    anti-patrón exacto de ADR-014: un porcentaje sobre un denominador que no es
    el del universo.
    """
    sqls, _ = _capturar()
    conteos = sqls[0]

    assert "count(*)" in conteos
    # `count(col)` no cuenta NULL: ésa es la definición de «trae fecha».
    assert "count(licitaciones.fecha_inicio)" in conteos


def test_las_filas_sin_fecha_prevista_van_al_final_y_no_se_esconden() -> None:
    """`NULLS LAST` explícito y ningún `WHERE fecha_inicio IS NOT NULL`.

    Filtrarlas sería la salida fácil —la bandeja se leería como un calendario
    limpio— y dejaría fuera al caso mayoritario. El criterio de aceptación pide
    listarlas y rotularlas «sin fecha».
    """
    sqls, _ = _capturar()
    datos = sqls[-1]

    assert re.search(r"ORDER BY licitaciones\.fecha_inicio ASC NULLS LAST", datos)
    assert "fecha_inicio IS NOT NULL" not in datos
    # Desempate estable: sin él, dos filas con la misma fecha pueden turnarse
    # entre páginas y una no salir nunca.
    assert datos.rstrip().find("licitaciones.id_externo ASC") > 0


def test_sin_estados_no_se_abre_la_conexion() -> None:
    """Un universo vacío no es una consulta sin `WHERE`: es cero filas."""
    with patch("db.repositories.licitaciones.connect_read") as conectar:
        items, total, con_fecha = LicitacionRepository().proximas(estados=())

    conectar.assert_not_called()
    assert (items, total, con_fecha) == ([], 0, 0)


# ── La ruta ───────────────────────────────────────────────────────────────

_CON_FECHA = {
    "id_externo": "PRE-1",
    "titulo": "Programa de actividades de Navidad",
    "organo_contratacion": "Distrito de Chamberí",
    "importe": 351641.8,
    "estado": "PRE",
    "fecha_publicacion": "2026-05-22",
    # `PlannedPeriod/StartDate` — la única fecha que la fuente publica antes
    # del pliego (`scraper/codice_parser.py:526`).
    "fecha_inicio": "2026-11-01",
    "ccaa": "MAD",
    "cpv": "92000000",
    "url": None,
    "tecnologia": None,
}

_SIN_FECHA = {**_CON_FECHA, "id_externo": "CPM-1", "estado": "CPM", "fecha_inicio": None}


def _llamar(filas: list[dict[str, Any]], total: int, con_fecha: int) -> Any:
    from api.routes import radar as radar_route

    with patch.object(
        radar_route._lic_repo,
        "proximas",
        return_value=(filas, total, con_fecha),
    ):
        return asyncio.run(radar_route.get_proximas(limit=50, offset=0, _ctx={}))


def test_la_fecha_prevista_es_fecha_inicio_cuando_existe() -> None:
    resultado = _llamar([_CON_FECHA], total=1, con_fecha=1)

    assert resultado.items[0].fecha_prevista == "2026-11-01"
    # Y se declara de dónde salió, para que una segunda procedencia futura no
    # cambie el significado del campo en silencio.
    assert resultado.fecha_prevista_origen == "planned_period_start"


def test_sin_fecha_publicada_el_campo_viaja_nulo_y_no_se_rellena() -> None:
    """`None` significa «sin fecha».

    Ni cadena vacía, ni la de publicación, ni una derivada de la duración: el
    cliente tiene que poder distinguir «para noviembre» de «no se sabe», y esa
    distinción se pierde en cuanto alguien pone un fallback aquí.
    """
    resultado = _llamar([_SIN_FECHA], total=1, con_fecha=0)

    fila = resultado.items[0]
    assert fila.fecha_prevista is None
    assert fila.fecha_publicacion == "2026-05-22"


def test_la_ruta_declara_el_universo_que_aplico() -> None:
    """El cliente no reescribe los códigos: los recibe."""
    resultado = _llamar([], total=0, con_fecha=0)

    assert resultado.estados == ["PRE", "CPM"]


def test_los_conteos_son_los_del_repositorio_y_no_los_de_la_pagina() -> None:
    """Servir 2 filas de un universo de 47 no puede convertir el total en 2."""
    resultado = _llamar([_CON_FECHA, _SIN_FECHA], total=47, con_fecha=3)

    assert (resultado.total, resultado.con_fecha_prevista) == (47, 3)
    assert len(resultado.items) == 2


@pytest.mark.parametrize("fila", [_CON_FECHA, _SIN_FECHA])
def test_la_fila_no_lleva_score_ni_banda(fila: dict[str, Any]) -> None:
    """Puntuar un expediente sin plazo exigiría inventar la dimensión que falta."""
    resultado = _llamar([fila], total=1, con_fecha=1)

    volcado = resultado.items[0].model_dump()
    assert "score" not in volcado
    assert "band" not in volcado
