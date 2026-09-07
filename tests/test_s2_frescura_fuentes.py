"""Frescura por fuente de ingesta (S2.3).

Hoy un conector puede llevar semanas muerto y el job sale verde: seis de los
siete corren con ``continue-on-error: true`` y el healthcheck solo miraba el
último ``extraction_run`` global, que el carril PLACSP mantiene fresco aunque
las demás fuentes estén paradas.

Sin BD: se inyecta el repositorio de salud.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Any
from unittest.mock import patch

from scheduler.healthcheck import comprobar_frescura_fuentes
from scraper.connectors import REGISTERED_SOURCES, REGISTERED_SOURCES_BY_ID

AHORA = datetime(2026, 9, 3, 12, 0, tzinfo=UTC)


class _RepoFalso:
    """Repositorio de salud inyectable: solo necesita ``list_health``."""

    def __init__(self, filas: list[dict[str, Any]]) -> None:
        self._filas = filas

    def list_health(self) -> list[dict[str, Any]]:
        return self._filas


def _fila(
    source: str, *, horas: float | None, status: str = "success", fetched: int = 1
) -> dict[str, Any]:
    ultimo = None if horas is None else (AHORA - timedelta(hours=horas)).isoformat()
    # `fetched=1` por defecto: un run sano trae avisos. El cero es el caso raro
    # —y el que este módulo aprendió a mirar en C4.3—, así que se pide a mano.
    return {
        "source": source,
        "status": status,
        "last_success_at": ultimo,
        "fetched": fetched,
    }


def _todas_frescas() -> list[dict[str, Any]]:
    return [_fila(s.source_id, horas=1) for s in REGISTERED_SOURCES]


# ---------------------------------------------------------------------------
# El inventario
# ---------------------------------------------------------------------------


def test_el_inventario_cubre_las_fuentes_vivas() -> None:
    assert set(REGISTERED_SOURCES_BY_ID) == {
        "placsp",
        "ted",
        "galicia_rss",
        "euskadi",
        "pscp",
        "tacrc",
        "placsp_watched_company_awards",
    }


def test_placsp_tiene_el_umbral_del_carril_diario() -> None:
    """36 h = nueve ciclos de 4 h, el mismo número que ``--freshness-hours``."""
    assert REGISTERED_SOURCES_BY_ID["placsp"].max_lag_hours == 36


def test_las_fuentes_de_descubrimiento_tienen_umbral_semanal() -> None:
    for source_id in ("ted", "galicia_rss", "tacrc"):
        assert REGISTERED_SOURCES_BY_ID[source_id].max_lag_hours == 168


def test_euskadi_dejo_de_ser_una_fuente_de_descubrimiento() -> None:
    """Pasó de un RSS de ventana corta a un buscador oficial paginado (C4.3).

    El umbral semanal era coherente con «lo que se pierda hoy no vuelve»; con
    cursor por fecha sobre ~698.000 resultados, lo que se pierde se recupera en
    el siguiente run, y dos días sin completar sí son señal.
    """
    assert REGISTERED_SOURCES_BY_ID["euskadi"].max_lag_hours == 72


def test_toda_fuente_declara_por_que_tiene_ese_umbral() -> None:
    """Un umbral sin motivo escrito se relaja hasta que deja de alertar."""
    for fuente in REGISTERED_SOURCES:
        assert fuente.motivo.strip()
        assert fuente.max_lag_hours > 0
        assert fuente.modulo.startswith("scraper.connectors.")


def test_las_fuentes_gateadas_por_variable_de_entorno_son_opcionales() -> None:
    assert REGISTERED_SOURCES_BY_ID["pscp"].opcional
    assert REGISTERED_SOURCES_BY_ID["tacrc"].opcional
    assert not REGISTERED_SOURCES_BY_ID["placsp"].opcional


# ---------------------------------------------------------------------------
# El chequeo
# ---------------------------------------------------------------------------


def test_todas_frescas_no_reporta_nada() -> None:
    resultado = comprobar_frescura_fuentes(_RepoFalso(_todas_frescas()), ahora=AHORA)

    assert resultado["atrasadas"] == []
    assert resultado["sin_registro"] == []
    assert resultado["apagadas"] == []
    assert resultado["fuentes"]["placsp"]["estado"] == "fresca"


def test_una_fuente_pasada_de_su_umbral_sale_atrasada() -> None:
    filas = _todas_frescas()
    filas[0] = _fila("placsp", horas=40)  # umbral 36

    resultado = comprobar_frescura_fuentes(_RepoFalso(filas), ahora=AHORA)

    assert resultado["atrasadas"] == ["placsp"]
    assert resultado["fuentes"]["placsp"]["lag_hours"] == 40.0


def test_cada_fuente_se_mide_contra_su_propio_umbral() -> None:
    """40 h atrasan a PLACSP y no a Galicia: el punto del inventario."""
    filas = [
        _fila("placsp", horas=40),
        _fila("galicia_rss", horas=40),
        *[
            _fila(s.source_id, horas=1)
            for s in REGISTERED_SOURCES
            if s.source_id not in ("placsp", "galicia_rss")
        ],
    ]

    resultado = comprobar_frescura_fuentes(_RepoFalso(filas), ahora=AHORA)

    assert resultado["atrasadas"] == ["placsp"]
    assert resultado["fuentes"]["galicia_rss"]["estado"] == "fresca"


def test_apagada_no_es_lo_mismo_que_muerta() -> None:
    """``disabled`` lo escribe el propio conector cuando le falta su variable.

    Es lo que S2.5 añade a PSCP y TACRC, y es la distinción que el
    ``continue-on-error: true`` del workflow borraba.
    """
    filas = _todas_frescas()
    filas = [f for f in filas if f["source"] != "pscp"]
    filas.append(_fila("pscp", horas=None, status="disabled"))

    resultado = comprobar_frescura_fuentes(_RepoFalso(filas), ahora=AHORA)

    assert resultado["apagadas"] == ["pscp"]
    assert resultado["atrasadas"] == []
    assert resultado["fuentes"]["pscp"]["estado"] == "apagada"


def test_una_fuente_apagada_que_vuelve_a_correr_vuelve_a_medirse() -> None:
    filas = _todas_frescas()
    filas = [f for f in filas if f["source"] != "pscp"]
    filas.append(_fila("pscp", horas=100, status="success"))  # umbral 72

    resultado = comprobar_frescura_fuentes(_RepoFalso(filas), ahora=AHORA)

    assert resultado["apagadas"] == []
    assert resultado["atrasadas"] == ["pscp"]


def test_una_fuente_obligatoria_sin_registro_alerta() -> None:
    filas = [f for f in _todas_frescas() if f["source"] != "placsp"]

    resultado = comprobar_frescura_fuentes(_RepoFalso(filas), ahora=AHORA)

    assert resultado["sin_registro"] == ["placsp"]
    assert resultado["fuentes"]["placsp"]["estado"] == "sin_registro"


def test_una_fuente_opcional_sin_registro_no_alerta() -> None:
    """Repetir cada seis horas que algo nunca se configuró es el ruido que
    acaba con el check desactivado."""
    filas = [f for f in _todas_frescas() if f["source"] != "tacrc"]

    resultado = comprobar_frescura_fuentes(_RepoFalso(filas), ahora=AHORA)

    assert resultado["sin_registro"] == []
    assert resultado["fuentes"]["tacrc"]["estado"] == "sin_registro"


def test_una_fila_sin_ningun_run_exitoso_cuenta_como_atrasada() -> None:
    """Hay registro (la fuente corrió) pero nunca terminó bien."""
    filas = [f for f in _todas_frescas() if f["source"] != "ted"]
    filas.append(_fila("ted", horas=None, status="failed"))

    resultado = comprobar_frescura_fuentes(_RepoFalso(filas), ahora=AHORA)

    assert resultado["atrasadas"] == ["ted"]
    assert resultado["fuentes"]["ted"]["lag_hours"] is None


def test_una_fuente_obligatoria_que_no_descarga_nada_esta_rota() -> None:
    """Cero avisos con ``success`` no es silencio: es un conector que no entiende su fuente.

    Es lo que le pasó a Euskadi durante toda su vida útil (C4.3): 50 avisos en
    el feed, 0 emitidos por el conector, ``success`` cada día, y ni una fila en
    `licitaciones`. El chequeo de frescura lo veía fresco.
    """
    filas = [f for f in _todas_frescas() if f["source"] != "euskadi"]
    filas.append(_fila("euskadi", horas=1, fetched=0))

    resultado = comprobar_frescura_fuentes(repo=_RepoFalso(filas), ahora=AHORA)

    assert resultado["esteriles"] == ["euskadi"]
    assert resultado["fuentes"]["euskadi"]["estado"] == "esteril"
    assert not resultado["atrasadas"], "estéril y atrasada son diagnósticos distintos"


def test_una_fuente_opcional_sin_avisos_no_es_esteril() -> None:
    """Para una fuente opcional, cero avisos es un estado declarado.

    `placsp_watched_company_awards` sin NIFs vigilados no descarga nada, y eso
    es correcto: alertar sería pedirle al mantenedor que arregle una decisión.
    """
    filas = [f for f in _todas_frescas() if f["source"] != "placsp_watched_company_awards"]
    filas.append(_fila("placsp_watched_company_awards", horas=1, fetched=0))

    resultado = comprobar_frescura_fuentes(repo=_RepoFalso(filas), ahora=AHORA)

    assert resultado["esteriles"] == []


def test_atrasada_gana_a_esteril() -> None:
    """Si además lleva días sin correr, lo que hay que arreglar es que no corre."""
    filas = [f for f in _todas_frescas() if f["source"] != "galicia_rss"]
    filas.append(_fila("galicia_rss", horas=1000, fetched=0))

    resultado = comprobar_frescura_fuentes(repo=_RepoFalso(filas), ahora=AHORA)

    assert resultado["atrasadas"] == ["galicia_rss"]
    assert resultado["esteriles"] == []


def test_una_fecha_ilegible_no_se_cuenta_como_fresca() -> None:
    filas = [f for f in _todas_frescas() if f["source"] != "ted"]
    filas.append({"source": "ted", "status": "success", "last_success_at": "ayer"})

    resultado = comprobar_frescura_fuentes(_RepoFalso(filas), ahora=AHORA)

    assert resultado["atrasadas"] == ["ted"]


def test_las_fuentes_bulk_efimeras_se_ignoran() -> None:
    """``bulk_YYYYMM`` es una fuente por mes reprocesado: no tiene SLA."""
    filas = [*_todas_frescas(), _fila("bulk_202401", horas=9000)]

    resultado = comprobar_frescura_fuentes(_RepoFalso(filas), ahora=AHORA)

    assert resultado["atrasadas"] == []
    assert "bulk_202401" not in resultado["fuentes"]


# ---------------------------------------------------------------------------
# Integración con el informe del healthcheck
# ---------------------------------------------------------------------------


def test_el_informe_incluye_la_frescura_y_avisa() -> None:
    from scheduler.healthcheck import _incorporar_frescura_fuentes

    checks: list[dict[str, object]] = []
    warnings: list[str] = []
    info: dict[str, object] = {}

    with (
        patch(
            "scheduler.healthcheck.comprobar_frescura_fuentes",
            return_value={
                "atrasadas": ["placsp"],
                "apagadas": ["pscp"],
                "sin_registro": ["ted"],
                "fuentes": {},
            },
        ),
        patch("scheduler.healthcheck.notify") as notificar,
    ):
        _incorporar_frescura_fuentes(checks, warnings, info)

    assert "fuente_atrasada:placsp" in warnings
    assert "fuente_sin_registro:ted" in warnings
    assert {"name": "fuentes_frescas", "ok": False} in checks
    assert info["fuentes_frescura"]["apagadas"] == ["pscp"]  # type: ignore[index]
    notificar.assert_called_once()


def test_no_poder_medir_la_frescura_no_tumba_el_informe() -> None:
    """Mismo criterio que el resto de checks secundarios del healthcheck."""
    from scheduler.healthcheck import _incorporar_frescura_fuentes

    checks: list[dict[str, object]] = []
    warnings: list[str] = []
    info: dict[str, object] = {}

    with patch(
        "scheduler.healthcheck.comprobar_frescura_fuentes",
        side_effect=RuntimeError("sin BD"),
    ):
        _incorporar_frescura_fuentes(checks, warnings, info)

    assert warnings == ["fuentes_frescura_no_medida"]
    assert checks == [{"name": "fuentes_frescas", "ok": True}]
    assert "fuentes_frescura_error" in info


# ---------------------------------------------------------------------------
# La cuarta tabla de salud (C4.6)
# ---------------------------------------------------------------------------


def test_nadie_escribe_en_la_tabla_retirada() -> None:
    """``extracciones`` se retiró en v119: es una vista, y escribirla falla.

    El guardarraíl es de código y no de base de datos a propósito. En Postgres
    un ``INSERT`` sobre una vista simple ya falla solo, pero ese error llegaría
    en producción, a las 4 de la mañana, dentro del camino caliente de la
    ingesta. Aquí llega en el PR que lo reintroduce.

    Se busca la escritura, no la mención: el docstring de la revisión y esta
    misma prueba nombran la tabla, y tienen que poder hacerlo.
    """
    import re
    from pathlib import Path

    raiz = Path(__file__).resolve().parents[1]
    escritura = re.compile(r"(INSERT\s+INTO|UPDATE|DELETE\s+FROM)\s+extracciones\b", re.IGNORECASE)
    culpables = []
    for ruta in raiz.rglob("*.py"):
        partes = set(ruta.parts)
        if partes & {".venv", "node_modules", "graphify-out", "__pycache__", "versions"}:
            continue
        if escritura.search(ruta.read_text(encoding="utf-8", errors="replace")):
            culpables.append(str(ruta.relative_to(raiz)))

    assert not culpables, (
        "Escriben en `extracciones`, retirada en v119 (C4.6). Lo que se quería "
        "registrar ya está en `extraction_runs` (por run) o en "
        f"`source_ingestion_health` (por fuente): {culpables}"
    )
