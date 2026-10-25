"""Tests de resoluciones TACRC (Fase 5.3, RFC 20260611-1)."""

from __future__ import annotations

import json
from datetime import date

import pytest
import requests

from scraper.connectors import tacrc
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


# ---------------------------------------------------------------------------
# Índice completo: la biblioteca de resoluciones, año a año
# ---------------------------------------------------------------------------
#
# Los nombres de fichero son **reales**: los de PDFs publicados en
# hacienda.gob.es bajo `/tacrc/resoluciones/año AAAA/`, localizados por búsqueda
# web el 2026-10-12. El sobre JSON es el formato documentado de la API REST de
# SharePoint (`GetFolderByServerRelativeUrl(...)/Files`, en sus dos formas:
# `odata=verbose` → `{"d": {"results": [...]}}` y `odata=nometadata` →
# `{"value": [...]}`). Que el servidor del ministerio sirva esa API a un
# visitante anónimo NO se ha podido comprobar (la sesión no tenía salida al
# host): `--check` es lo primero que hay que correr al encenderlo.

_NOMBRES_REALES = {
    2016: [
        "Recursos 1036, 1037 y 1038-2016 AST 65, 66 y 67-2016 (Res 1048) 16-12-2016.pdf",
    ],
    2020: ["recurso 0209-2020 (res 507) 02-04-2020.pdf"],
    2023: [
        "recurso 0339-2023 val 74-2023 (res 468) 20-04-2023.pdf",
        "recurso 1131-2023 mu 83-2023 (res 1411) 27-10-2023.pdf",
    ],
    2025: ["recurso 1745-2025 (res 1758) 04-12-2025.pdf"],
}


def _listado_verbose(anio: int) -> str:
    return json.dumps(
        {
            "d": {
                "results": [
                    {
                        "Name": nombre,
                        "ServerRelativeUrl": f"/tacrc/resoluciones/año {anio}/{nombre}",
                        "TimeLastModified": f"{anio}-12-31T10:00:00Z",
                    }
                    for nombre in _NOMBRES_REALES.get(anio, [])
                ]
            }
        }
    )


_URL_ANIO = (
    "https://www.hacienda.gob.es/tacrc/_api/web/"
    "GetFolderByServerRelativeUrl('/tacrc/resoluciones/año {anio}')/Files"
)


def test_el_listado_json_de_la_biblioteca_se_parsea_con_los_mismos_patrones():
    items = parse_index(_listado_verbose(2023), base_url=_URL_ANIO.replace("{anio}", "2023"))

    por_numero = {r.numero_resolucion: r for r in items}
    assert set(por_numero) == {"468/2023", "1411/2023"}
    res = por_numero["1411/2023"]
    assert res.numero_recurso == "1131/2023"
    assert res.fecha == "2023-10-27"
    assert res.url_pdf == (
        "https://www.hacienda.gob.es/tacrc/resoluciones/a%C3%B1o%202023/"
        "recurso%201131-2023%20mu%2083-2023%20(res%201411)%2027-10-2023.pdf"
    )


def test_el_listado_json_en_forma_nometadata():
    nombre = _NOMBRES_REALES[2016][0]
    texto = json.dumps(
        {
            "value": [
                {"Name": nombre, "ServerRelativeUrl": f"/tacrc/resoluciones/año 2016/{nombre}"},
                {"Name": "Forms", "ServerRelativeUrl": "/tacrc/resoluciones/Forms"},
            ]
        }
    )

    items = parse_index(texto, base_url="https://www.hacienda.gob.es/tacrc/_api/x")

    # Tres recursos acumulados en una resolución: el número sale del «(Res N)»
    # con el año de la fecha. Lo que no es un PDF (la carpeta Forms) se ignora.
    assert [(r.numero_resolucion, r.fecha) for r in items] == [("1048/2016", "2016-12-16")]


def test_un_json_que_no_es_un_listado_no_da_resoluciones():
    assert parse_index('{"error": {"code": "-2147024894"}}', base_url=_URL_ANIO) == []


def test_las_paginas_de_un_indice_por_anios_van_del_cursor_a_hoy():
    urls = tacrc.urls_del_indice(_URL_ANIO, desde_anio=2023, hoy=date(2025, 3, 1))

    assert [anio for anio, _ in urls] == [2023, 2024, 2025]
    assert urls[0][1].endswith("año 2023')/Files")


def test_un_indice_sin_marcador_es_una_sola_pagina():
    url = (
        "https://www.hacienda.gob.es/es-ES/Areas%20Tematicas/Contratacion/"
        "TACRC/Paginas/Resoluciones-Pleno.aspx"
    )

    assert tacrc.urls_del_indice(url, desde_anio=2010, hoy=date(2026, 1, 1)) == [(None, url)]


def test_el_valor_por_defecto_de_produccion_sigue_siendo_el_pleno():
    """Cambiarlo encendería el índice completo en el plano del worker sin decidirlo.

    En `scrape-daily.yml` la variable de repo vacía apaga TACRC; en el worker,
    sin la variable, manda este valor por defecto.
    """
    from config.settings import Settings

    assert Settings.model_fields["TACRC_INDEX_URL"].default.endswith("Resoluciones-Pleno.aspx")
    assert Settings.model_fields["TACRC_PRIMER_ANIO"].default == 2010
    assert tacrc.MARCADOR_ANIO in tacrc.URL_BIBLIOTECA_RESOLUCIONES


def test_a_la_api_de_sharepoint_se_le_pide_json():
    pedidas: list[dict[str, str]] = []

    class _Respuesta:
        text = "{}"

        def raise_for_status(self) -> None:
            return None

    class _Sesion:
        def get(self, url: str, **kw: object) -> _Respuesta:
            pedidas.append(dict(kw.get("headers") or {}))  # type: ignore[call-overload]
            return _Respuesta()

    tacrc.fetch_index(_URL_ANIO.replace("{anio}", "2025"), session=_Sesion())  # type: ignore[arg-type]
    tacrc.fetch_index("https://tribunal.example/index.html", session=_Sesion())  # type: ignore[arg-type]

    assert pedidas[0]["Accept"].startswith("application/json")
    assert "Accept" not in pedidas[1]


def _fetch_por_anio(roto: dict[int, Exception] | None = None):
    pedidos: list[int] = []

    def fetch(url: str | None = None, session: object = None) -> str:
        anio = int(str(url).split("año ")[1][:4])
        pedidos.append(anio)
        if roto and anio in roto:
            raise roto[anio]
        return _listado_verbose(anio)

    return fetch, pedidos


def _http_404() -> requests.HTTPError:
    respuesta = requests.Response()
    respuesta.status_code = 404
    return requests.HTTPError("404 Client Error", response=respuesta)


def test_run_con_indice_por_anios_desde_el_primer_anio_configurado(db, monkeypatch):
    from config import settings
    from db.database import get_cursor

    monkeypatch.setattr(settings, "TACRC_PRIMER_ANIO", 2022)
    fetch, pedidos = _fetch_por_anio(roto={2024: _http_404()})
    monkeypatch.setattr("scraper.connectors.tacrc.fetch_index", fetch)

    stats = run(_URL_ANIO, hoy=date(2025, 6, 1))

    # 2024 no tiene carpeta (404): un año sin índice no es un error.
    assert pedidos == [2022, 2023, 2024, 2025]
    assert stats["errores"] == 0
    assert stats["nuevas"] == 3
    assert get_cursor("tacrc")["last_seen_updated"] == "2025-12-04"


def test_run_con_indice_por_anios_retoma_desde_el_anio_del_cursor(db, monkeypatch):
    from db.database import set_cursor

    set_cursor("tacrc", last_seen_updated="2023-06-01")
    fetch, pedidos = _fetch_por_anio()
    monkeypatch.setattr("scraper.connectors.tacrc.fetch_index", fetch)

    stats = run(_URL_ANIO, hoy=date(2025, 6, 1))

    assert pedidos == [2023, 2024, 2025]
    # Del 2023 solo entra lo posterior al cursor (la 1411, de octubre).
    assert stats["nuevas"] == 2


def test_un_anio_roto_conserva_lo_anterior_y_no_salta_al_siguiente(db, monkeypatch):
    """Por años ascendentes y cursor por año: un corte no tira lo ya escrito.

    Saltar el año roto y seguir movería el cursor por encima de él, y ese año
    no se volvería a pedir nunca.
    """
    from config import settings
    from db.database import get_cursor

    monkeypatch.setattr(settings, "TACRC_PRIMER_ANIO", 2020)
    fetch, pedidos = _fetch_por_anio(roto={2023: RuntimeError("timeout")})
    monkeypatch.setattr("scraper.connectors.tacrc.fetch_index", fetch)

    stats = run(_URL_ANIO, hoy=date(2025, 6, 1))

    assert pedidos == [2020, 2021, 2022, 2023]
    assert stats["errores"] == 1
    assert stats["nuevas"] == 1
    assert get_cursor("tacrc")["last_seen_updated"] == "2020-04-02"


def test_desde_anio_fuerza_un_backfill_que_ignora_el_cursor(db, monkeypatch):
    from db.database import set_cursor

    set_cursor("tacrc", last_seen_updated="2025-01-01")
    fetch, pedidos = _fetch_por_anio()
    monkeypatch.setattr("scraper.connectors.tacrc.fetch_index", fetch)

    stats = run(_URL_ANIO, desde_anio=2016, hoy=date(2016, 12, 31))

    assert pedidos == [2016]
    assert stats["nuevas"] == 1


def test_check_con_indice_por_anios_mira_el_anio_en_curso(monkeypatch):
    from unittest.mock import MagicMock

    registro = MagicMock()
    fetch, pedidos = _fetch_por_anio()
    monkeypatch.setattr("scraper.connectors.tacrc.fetch_index", fetch)
    monkeypatch.setattr(tacrc, "_hoy", lambda: date(2023, 11, 2))
    monkeypatch.setattr(tacrc, "log", registro)

    codigo = tacrc.main(["--check", "--url", _URL_ANIO])

    assert codigo == 0
    assert pedidos == [2023]
    # El informe del --check va al log estructurado (sin print() en scraper/).
    informe = next(c.kwargs for c in registro.info.call_args_list if c.args == ("tacrc_check",))
    assert informe["resoluciones"] == 2


def test_upsert_por_lotes_cuenta_bien_y_no_pisa_la_vinculacion(db):
    from db.database import connect

    assert upsert_resoluciones(
        [_resolucion_estimada(), _resolucion_estimada(numero_resolucion="124/2026")]
    ) == (2, 0)
    with connect() as c:
        c.execute(
            "INSERT INTO licitaciones (id_externo, titulo, fuente, fecha_extraccion) "
            "VALUES ('EXP-L', 'x', 'placsp', CURRENT_TIMESTAMP)"
        )
        c.execute(
            "UPDATE resoluciones_recurso SET licitacion_id = 'EXP-L' "
            "WHERE numero_resolucion = '123/2026'"
        )

    assert upsert_resoluciones(
        [
            _resolucion_estimada(sentido="desestimado"),
            _resolucion_estimada(numero_resolucion="125/2026"),
        ]
    ) == (1, 1)

    filas = {r["numero_resolucion"]: r for r in resoluciones()}
    assert filas["123/2026"]["licitacion_id"] == "EXP-L"
    assert filas["123/2026"]["sentido"] == "desestimado"
    assert set(filas) == {"123/2026", "124/2026", "125/2026"}


# ---------------------------------------------------------------------------
# Recorte real del índice del Pleno (bajado el 2026-10-24)
# ---------------------------------------------------------------------------

_URL_PLENO = (
    "https://www.hacienda.gob.es/es-ES/Areas%20Tematicas/Contratacion/"
    "TACRC/Paginas/Resoluciones-Pleno.aspx"
)


def _pleno_real() -> list[Resolucion]:
    from pathlib import Path

    html = (Path(__file__).parent / "fixtures" / "tacrc" / "resoluciones_pleno.html").read_bytes()
    return parse_index(html, base_url=_URL_PLENO)


def test_el_indice_real_del_pleno_se_parsea_entero():
    items = _pleno_real()

    assert len(items) == 19
    assert all(r.url_pdf and r.numero_recurso and r.fecha for r in items)
    assert all(r.url_pdf.startswith("https://www.hacienda.gob.es/tacrc/") for r in items)
    assert [r.fecha[:4] for r in items] == sorted(r.fecha[:4] for r in items)


def test_el_indice_real_del_pleno_saca_numero_recurso_y_fecha_del_nombre_del_pdf():
    por_numero = {r.numero_resolucion: r for r in _pleno_real()}

    # «recurso 590-2022 ast 33-2022 (res 696) 16-06-2022.pdf»: el recurso es el
    # primer número, no el «33-2022» que sigue a «ast», y la fecha va al final.
    r = por_numero["696/2022"]
    assert (r.numero_recurso, r.fecha) == ("590/2022", "2022-06-16")
    # Un recurso de 2024 resuelto en 2025: el número de resolución lleva el año
    # de la fecha de la resolución, el del recurso es el suyo.
    r = por_numero["144/2025"]
    assert (r.numero_recurso, r.fecha) == ("1312/2024", "2025-01-31")
    # Día de un dígito («27-9-2022») y sufijo «. corregida» tras la fecha.
    assert por_numero["1113/2022"].fecha == "2022-09-27"
    assert por_numero["1014/2026"].fecha == "2026-06-11"


def test_el_indice_real_del_pleno_no_trae_el_sentido():
    """Son resoluciones doctrinales: el índice las titula por materia, no por fallo."""
    assert {r.sentido for r in _pleno_real()} == {None}


def test_la_api_de_sharepoint_que_redirige_a_pagenotfound_es_un_error_no_cero_resoluciones():
    """El sitio no contesta 401/403: redirige a su página de «no encontrado».

    ``requests`` la sigue y devuelve 200 con HTML, y sin esta guarda una pasada
    con la plantilla candidata habría terminado «bien» con 0 resoluciones.
    """

    class _Respuesta:
        url = "https://www.hacienda.gob.es/es-es/Paginas/pagenotfound.aspx"
        text = "<html>Pagina de archivo no encontrado</html>"

        def raise_for_status(self) -> None:
            return None

    class _Sesion:
        def get(self, url: str, **kw: object) -> _Respuesta:
            return _Respuesta()

    with pytest.raises(RuntimeError, match="pagenotfound"):
        tacrc.fetch_index(
            tacrc.URL_BIBLIOTECA_RESOLUCIONES.replace("{anio}", "2026"),
            session=_Sesion(),  # type: ignore[arg-type]
        )
