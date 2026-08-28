"""El campo ``estado`` nunca vuelve a contener texto crudo de la PSCP.

Regresión de un fallo que costó el 93% del corpus: el fallback del conector
(``fase.strip().upper()[:20]``) filtraba la fase catalana cruda al campo
``estado``. Eso llenaba el selector de ``/meta/filters`` de valores como
``"PUBLICACIÓ AGREGADA "`` y, como ``abierta_sql`` enumera el cierre y no la
apertura, hacía que 645.664 contratos menores ya adjudicados contaran como
oportunidades vivas.

Las fases de este fichero son el vocabulario real del dataset ybgg-dgi6 medido
contra la API viva el 2026-08-27; ver la tabla de evidencia en
``scraper/connectors/pscp.py``.
"""

from __future__ import annotations

import pytest

from scraper.connectors.pscp import (
    _FASE_ESTADO,
    _fases_sin_mapeo_vistas,
    fase_to_estado,
)
from shared.estados import (
    ESTADOS_CANONICOS,
    ESTADOS_CERRADOS,
    filtrar_estados_canonicos,
    normalizar_estado,
)

# Las diez fases que el dataset publica hoy, con el conteo medido, y el estado
# que el producto debe darles.
FASES_OBSERVADAS = [
    ("Publicació agregada de contractes", "AGREG"),
    ("Formalització", "RES"),
    ("Adjudicació", "ADJ"),
    ("Execució", "EJEC"),
    ("Anul·lació", "ANUL"),
    ("Anunci de licitació", "PUB"),
    ("Expedient en avaluació", "EV"),
    ("Anunci previ", "PRE"),
    ("Alerta futura", "PRE"),
    ("Consulta preliminar del mercat", "PRE"),
]

# Lo que `GET /api/v1/meta/filters` devolvía en producción antes del arreglo:
# texto crudo en mayúsculas truncado a 20 caracteres, espacios finales incluidos.
ESTADOS_SUCIOS_EN_BD = [
    "ALERTA FUTURA",
    "CONSULTA PRELIMINAR ",
    "EXECUCIÓ",
    "EXPEDIENT EN AVALUAC",
    "PUBLICACIÓ AGREGADA ",
]


@pytest.mark.parametrize(("fase", "esperado"), FASES_OBSERVADAS)
def test_fases_observadas_mapean_al_estado_decidido(fase, esperado):
    assert fase_to_estado(fase) == esperado


@pytest.mark.parametrize(("fase", "_esperado"), FASES_OBSERVADAS)
def test_ninguna_fase_observada_produce_texto_crudo(fase, _esperado):
    assert fase_to_estado(fase) in ESTADOS_CANONICOS


class _LogEspia:
    """Captura las llamadas a ``log.warning`` sin depender del backend real."""

    def __init__(self):
        self.warnings: list[tuple[str, dict[str, object]]] = []

    def warning(self, evento, **kwargs):
        self.warnings.append((evento, kwargs))


def test_fase_desconocida_no_revienta_y_no_filtra_texto_crudo():
    _fases_sin_mapeo_vistas.clear()
    assert fase_to_estado("Fase Inventada Que No Existe") is None


def test_fase_desconocida_queda_logueada_una_sola_vez(monkeypatch):
    """El log es la única pista de que falta un mapeo, pero no puede ser spam.

    La fase masiva son 1,7M de filas: si la fuente la renombra, un log por fila
    ahogaría la corrida antes de que nadie leyera el aviso.
    """
    espia = _LogEspia()
    monkeypatch.setattr("scraper.connectors.pscp.log", espia)
    _fases_sin_mapeo_vistas.clear()

    assert fase_to_estado("Fase Rarísima") is None
    assert fase_to_estado("Fase Rarísima") is None

    assert len(espia.warnings) == 1
    evento, kwargs = espia.warnings[0]
    assert evento == "pscp_fase_sin_mapeo"
    assert kwargs["fase"] == "Fase Rarísima"


def test_fase_vacia_o_nula_devuelve_none():
    assert fase_to_estado(None) is None
    assert fase_to_estado("") is None
    assert fase_to_estado("   ") is None


@pytest.mark.parametrize("sucio", ESTADOS_SUCIOS_EN_BD)
def test_los_estados_sucios_de_produccion_siguen_siendo_mapeables(sucio):
    """El script de reparación relee el valor almacenado con la tabla del conector.

    Por eso las agujas de ``_FASE_ESTADO`` están recortadas para sobrevivir al
    truncado a 20 caracteres: si alguien "arregla" ``avaluac`` poniendo
    ``avaluaci``, ``"EXPEDIENT EN AVALUAC"`` deja de mapear y las filas
    históricas se quedan sucias para siempre.
    """
    assert fase_to_estado(sucio) in ESTADOS_CANONICOS


def test_publicacio_agregada_no_cuenta_como_oportunidad_viva():
    """El 93% del corpus. Si esto se rompe, "Total activas" vuelve a mentir."""
    assert fase_to_estado("Publicació agregada de contractes") in ESTADOS_CERRADOS


def test_execucio_es_estado_cerrado():
    assert fase_to_estado("Execució") in ESTADOS_CERRADOS


@pytest.mark.parametrize("fase", ["Anunci de licitació", "Expedient en avaluació"])
def test_las_convocatorias_con_plazo_siguen_abiertas(fase):
    assert fase_to_estado(fase) not in ESTADOS_CERRADOS


# ── vocabulario canónico ────────────────────────────────────────────────


def test_todo_estado_cerrado_es_canonico():
    assert set(ESTADOS_CERRADOS) <= ESTADOS_CANONICOS


def test_la_tabla_del_conector_solo_emite_codigos_canonicos():
    assert {estado for _, estado in _FASE_ESTADO} <= ESTADOS_CANONICOS


def test_normalizar_estado_limpia_pero_no_adivina():
    assert normalizar_estado(" pub ") == "PUB"
    assert normalizar_estado("PUBLICACIÓ AGREGADA ") is None
    assert normalizar_estado(None) is None
    assert normalizar_estado("") is None


def test_filtrar_estados_canonicos_descarta_la_basura_historica():
    """Reproduce la respuesta real de /meta/filters antes del arreglo."""
    observado = [
        "ADJ",
        "ALERTA FUTURA",
        "ANUL",
        "CONSULTA PRELIMINAR ",
        "EV",
        "EVA",
        "EXECUCIÓ",
        "EXPEDIENT EN AVALUAC",
        "PRE",
        "PUB",
        "PUBLICACIÓ AGREGADA ",
        "RES",
    ]
    assert filtrar_estados_canonicos(observado) == ["ADJ", "ANUL", "EV", "PRE", "PUB", "RES"]


def test_filtrar_estados_canonicos_deduplica_y_tolera_nulos():
    assert filtrar_estados_canonicos(["PUB", " pub", None, "PUB "]) == ["PUB"]


def test_filtrar_estados_canonicos_admite_los_codigos_nuevos():
    """Tras la reparación el selector debe poder ofrecer AGREG y EJEC."""
    assert filtrar_estados_canonicos(["AGREG", "EJEC"]) == ["AGREG", "EJEC"]
