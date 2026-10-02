"""El Resumen aplica el ámbito entero: ``/resumen/hoy``, ``/resumen/timeline``,
``/trends`` y ``solo_abiertas`` en ``/overview``.

FastAPI descarta sin decir nada los query params que una ruta no declara. Las
tres primeras solo declaraban fecha, CCAA y tecnología, y el cliente les manda
la barra de filtros entera: con un chip de estado o una búsqueda, «Mercado
abierto» y las publicaciones contaban otro universo que la tira de contexto de
al lado, y la pantalla tenía que avisarlo panel por panel. Por eso estos tests
van por HTTP y no contra el servicio: lo que fallaba era la declaración de la
ruta.

También fija las dos reglas que vinieron con ello en ``/resumen/hoy``:
``vencen_48h`` cuenta solo abiertas, e ``importe_p75`` es el umbral del ámbito
con el que se contó ``calientes`` —antes, con filtros, llegaba ``None``.
"""

from __future__ import annotations

from collections.abc import Iterator
from datetime import UTC, datetime, timedelta

import pytest

from db.database import connect

_HOY = "/api/v1/analytics/resumen/hoy"
_TIMELINE = "/api/v1/analytics/resumen/timeline"
_TRENDS = "/api/v1/analytics/trends"
_OVERVIEW = "/api/v1/analytics/overview"


def _iso(**delta: float) -> str:
    return (datetime.now(UTC) + timedelta(**delta)).isoformat()


def _licitacion(
    id_externo: str,
    *,
    titulo: str,
    estado: str,
    importe: float,
    ccaa: str = "Madrid",
    limite_en_horas: float = 24,
) -> None:
    with connect() as c:
        c.execute(
            "INSERT INTO licitaciones (id_externo, titulo, estado, fecha_publicacion, "
            "fecha_limite, fecha_extraccion, importe, ccaa, tecnologia) "
            "VALUES (%s, %s, %s, %s, %s, %s, %s, %s, 'SAP')",
            (
                id_externo,
                titulo,
                estado,
                _iso(hours=-6),
                _iso(hours=limite_en_horas),
                _iso(hours=-6),
                importe,
                ccaa,
            ),
        )


@pytest.fixture()
def corpus(client) -> Iterator[None]:
    """Tres expedientes que vencen en 24 h y dos que no; todos de hoy.

    La caché de respuestas de analítica es de proceso y no conoce el schema de
    cada test: se vacía antes y después para que una respuesta de otro test con
    los mismos parámetros no se cuele.
    """
    from shared.cache import get_cache

    get_cache("analytics").clear()
    _licitacion("AMB-SAP", titulo="Mantenimiento SAP", estado="PUB", importe=100_000)
    _licitacion("AMB-ORACLE", titulo="Licencias Oracle", estado="EV", importe=300_000)
    _licitacion("AMB-ANULADA", titulo="Soporte anulado", estado="ANUL", importe=50_000)
    _licitacion(
        "AMB-LEJOS-1", titulo="Consultoría", estado="PUB", importe=200_000, limite_en_horas=24 * 30
    )
    _licitacion(
        "AMB-LEJOS-2",
        titulo="Formación",
        estado="PUB",
        importe=400_000,
        ccaa="Cataluña",
        limite_en_horas=24 * 30,
    )
    yield
    get_cache("analytics").clear()


def test_hoy_vencen_48h_solo_cuenta_abiertas(client, auth, corpus):
    cuerpo = client.get(_HOY, headers=auth).json()
    # AMB-SAP y AMB-ORACLE; la anulada tiene el plazo en la ventana y no cuenta.
    assert cuerpo["vencen_48h"] == 2


@pytest.mark.parametrize(
    ("query", "esperado"),
    [
        ("estado=PUB", 1),
        ("q=Oracle", 1),
        ("importe_min=200000", 1),
        ("importe_max=200000", 1),
        ("solo_abiertas=true", 2),
    ],
)
def test_hoy_aplica_el_resto_del_ambito(client, auth, corpus, query, esperado):
    cuerpo = client.get(f"{_HOY}?{query}", headers=auth).json()
    assert cuerpo["vencen_48h"] == esperado


def test_hoy_publica_el_p75_del_ambito(client, auth, corpus):
    """Con un filtro el P75 sale igual, y es el del subconjunto.

    Madrid: 50k, 100k, 200k, 300k → ``percentile_cont(0.75)`` = 225k. El global
    (con los 400k de Cataluña) sería 300k: si la ruta publicara ese, el enlace
    de la tarjeta cortaría por un umbral que no produjo su cifra.
    """
    cuerpo = client.get(f"{_HOY}?ccaa=Madrid", headers=auth).json()
    assert cuerpo["importe_p75"] == pytest.approx(225_000)
    # El umbral que publica es el que contó: abiertas, en plazo y ≥ 225k → Oracle.
    assert cuerpo["calientes"] == 1


def test_timeline_aplica_el_resto_del_ambito(client, auth, corpus):
    todas = client.get(_TIMELINE, headers=auth).json()
    assert todas["total"] == 5

    por_estado = client.get(f"{_TIMELINE}?estado=EV", headers=auth).json()
    assert [fila["id_externo"] for fila in por_estado["items"]] == ["AMB-ORACLE"]

    abiertas = client.get(f"{_TIMELINE}?solo_abiertas=true", headers=auth).json()
    assert "AMB-ANULADA" not in {fila["id_externo"] for fila in abiertas["items"]}
    assert abiertas["total"] == 4


def test_trends_aplica_el_resto_del_ambito(client, auth, corpus):
    def publicadas(query: str = "") -> int:
        cuerpo = client.get(f"{_TRENDS}?group_by=day{query}", headers=auth).json()
        return sum(punto["count"] for punto in cuerpo["series"])

    assert publicadas() == 5
    assert publicadas("&q=Oracle") == 1
    assert publicadas("&solo_abiertas=true") == 4


def test_overview_aplica_solo_abiertas(client, auth, corpus):
    todas = client.get(_OVERVIEW, headers=auth).json()
    abiertas = client.get(f"{_OVERVIEW}?solo_abiertas=true", headers=auth).json()
    assert todas["total_licitaciones"] == 5
    assert abiertas["total_licitaciones"] == 4
