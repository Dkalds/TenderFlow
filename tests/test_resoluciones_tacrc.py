"""Tests de resoluciones TACRC (Fase 5.3, RFC 20260611-1)."""

from __future__ import annotations

import pytest

from scraper.connectors.tacrc import _fecha_iso, _sentido, parse_index, run
from services.resoluciones import (
    Resolucion,
    link_unlinked,
    resoluciones,
    upsert_resoluciones,
)


@pytest.fixture()
def db(tmp_db):
    db_mod, _ = tmp_db
    return db_mod


_INDEX_HTML = """
<html><body><table>
  <tr>
    <td><a href="/docs/res_0123_2026.pdf">Resolución nº 123/2026</a></td>
    <td>Recurso nº 99/2026 — Expediente: EXP-2026-42 — 15/03/2026 —
        Estimado. Anula la adjudicación y retrotrae actuaciones.</td>
  </tr>
  <tr>
    <td><a href="/docs/res_0124_2026.pdf">Resolución nº 124/2026</a></td>
    <td>Recurso nº 101/2026 — 2026-03-16 — Desestimado.</td>
  </tr>
  <tr>
    <td><a href="/otra-cosa">Nota informativa sin número</a></td>
    <td>Texto irrelevante</td>
  </tr>
</table></body></html>
"""


# ---------------------------------------------------------------------------
# Parser del índice HTML
# ---------------------------------------------------------------------------


def test_parse_index_extrae_metadatos():
    items = parse_index(_INDEX_HTML, base_url="https://tribunal.example/index.html")

    assert len(items) == 2
    por_numero = {r.numero_resolucion: r for r in items}
    res = por_numero["123/2026"]
    assert res.numero_recurso == "99/2026"
    assert res.fecha == "2026-03-15"
    assert res.expediente == "EXP-2026-42"
    assert res.sentido == "estimado"
    assert res.url_pdf == "https://tribunal.example/docs/res_0123_2026.pdf"
    assert por_numero["124/2026"].sentido == "desestimado"
    assert por_numero["124/2026"].fecha == "2026-03-16"


def test_parse_index_patron_pdf_real_hacienda():
    # Formato real de los PDFs del TACRC en hacienda.gob.es:
    # "Recurso NNNN-AAAA (Res NNNN) DD-MM-AAAA.pdf" (verificado 2026-06)
    html = """
    <html><body><ul>
      <li><a href="https://www.hacienda.gob.es/TACRC/Resoluciones/A%C3%B1o%202025/Recurso%201443-2025%20(Res%201782)%2004-12-2025.pdf">
        Recurso 1443-2025 (Res 1782) 04-12-2025</a></li>
    </ul></body></html>
    """
    items = parse_index(html)

    assert len(items) == 1
    res = items[0]
    assert res.numero_resolucion == "1782/2025"
    assert res.numero_recurso == "1443/2025"
    assert res.fecha == "2025-12-04"
    assert res.url_pdf.endswith(".pdf")


def test_parse_index_vacio_o_sin_enlaces():
    assert parse_index("") == []
    assert parse_index("<html><body><p>nada</p></body></html>") == []


def test_sentido_y_fecha_helpers():
    assert _sentido("El tribunal acuerda DESESTIMAR el recurso") == "desestimado"
    assert _sentido("Estimar parcialmente") == "estimado"
    assert _sentido("Inadmisión por extemporáneo") == "inadmitido"
    assert _sentido("texto neutro") is None
    assert _fecha_iso("a 5/3/2026") == "2026-03-05"
    assert _fecha_iso("sin fecha") is None


# ---------------------------------------------------------------------------
# Persistencia + vinculación + evento recurso
# ---------------------------------------------------------------------------


def _resolucion_estimada(**overrides):
    base = dict(
        numero_resolucion="123/2026",
        numero_recurso="99/2026",
        fecha="2026-03-15",
        expediente="EXP-2026-42",
        organo="Departament de Salut",
        sentido="estimado",
        url_pdf="https://tribunal.example/res123.pdf",
    )
    base.update(overrides)
    return Resolucion(**base)


def test_upsert_resoluciones_es_idempotente(db):
    assert upsert_resoluciones([_resolucion_estimada()]) == (1, 0)
    assert upsert_resoluciones([_resolucion_estimada()]) == (0, 1)
    from db.database import connect

    with connect() as c:
        assert c.execute("SELECT COUNT(*) FROM resoluciones_recurso").fetchone()[0] == 1


def test_link_estimado_genera_evento_recurso(db):
    from db.database import connect

    with connect() as c:
        c.execute(
            "INSERT INTO licitaciones (id_externo, titulo, organo_contratacion, fuente, "
            " fecha_extraccion) VALUES (%s, %s, %s, 'placsp', CURRENT_TIMESTAMP)",
            ("EXP-2026-42", "Contrato recurrido", "DEPARTAMENT DE SALUT"),
        )
    upsert_resoluciones([_resolucion_estimada()])

    stats = link_unlinked()

    assert stats == {"vinculadas": 1, "eventos": 1}
    rows = resoluciones(licitacion_id="EXP-2026-42")
    assert len(rows) == 1 and rows[0]["numero_resolucion"] == "123/2026"
    with connect() as c:
        evento = c.execute(
            "SELECT tipo, fecha, detalle FROM contrato_eventos WHERE licitacion_id = %s",
            ("EXP-2026-42",),
        ).fetchone()
    assert evento[0] == "recurso"
    assert evento[1] == "2026-03-15"
    assert "123/2026" in evento[2]

    # Re-vincular no duplica el evento
    assert link_unlinked() == {"vinculadas": 0, "eventos": 0}


def test_link_sin_match_conserva_resolucion(db):
    upsert_resoluciones([_resolucion_estimada(expediente="NO-EXISTE")])
    stats = link_unlinked()
    assert stats["vinculadas"] == 0
    rows = resoluciones()
    assert len(rows) == 1 and rows[0]["licitacion_id"] is None  # feed de jurisprudencia


def test_link_desestimado_no_genera_evento(db):
    from db.database import connect

    with connect() as c:
        c.execute(
            "INSERT INTO licitaciones (id_externo, titulo, organo_contratacion, fuente, "
            " fecha_extraccion) VALUES (%s, %s, %s, 'placsp', CURRENT_TIMESTAMP)",
            ("EXP-7", "Contrato", "Organo Z"),
        )
    upsert_resoluciones(
        [
            _resolucion_estimada(
                numero_resolucion="200/2026",
                expediente="EXP-7",
                organo="Organo Z",
                sentido="desestimado",
            )
        ]
    )

    stats = link_unlinked()

    assert stats == {"vinculadas": 1, "eventos": 0}


def test_run_ingesta_completa_con_cursor(db, monkeypatch):
    from db.database import get_cursor

    monkeypatch.setattr(
        "scraper.connectors.tacrc.fetch_index", lambda url=None, session=None: _INDEX_HTML
    )

    stats = run()

    assert stats["fetched"] == 2
    assert stats["nuevas"] == 2
    assert stats["errores"] == 0
    assert get_cursor("tacrc")["last_seen_updated"] == "2026-03-16"

    # Segunda pasada: idempotente, sin nuevas
    stats2 = run()
    assert stats2["nuevas"] == 0


def test_run_fetch_roto_va_a_dlq_sin_avanzar_cursor(db, monkeypatch):
    from db.database import connect, get_cursor

    def _boom(url=None, session=None):
        raise RuntimeError("índice caído")

    monkeypatch.setattr("scraper.connectors.tacrc.fetch_index", _boom)

    stats = run()

    assert stats["errores"] == 1
    assert get_cursor("tacrc") is None
    with connect() as c:
        dlq = c.execute(
            "SELECT fuente, scope FROM failed_extractions WHERE fuente = 'tacrc'"
        ).fetchall()
    assert ("tacrc", "fetch") in dlq


# ---------------------------------------------------------------------------
# API
# ---------------------------------------------------------------------------


def test_api_resoluciones_filtra_por_sentido(client, auth):
    upsert_resoluciones(
        [
            _resolucion_estimada(),
            _resolucion_estimada(numero_resolucion="124/2026", sentido="desestimado"),
        ]
    )

    resp = client.get("/api/v1/resoluciones", params={"sentido": "estimado"}, headers=auth)

    assert resp.status_code == 200
    items = resp.json()["items"]
    assert len(items) == 1 and items[0]["numero_resolucion"] == "123/2026"

    assert (
        client.get(
            "/api/v1/resoluciones", params={"sentido": "inventado"}, headers=auth
        ).status_code
        == 422
    )
