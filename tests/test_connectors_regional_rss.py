"""Contrato de parseo de las fuentes autonómicas oficiales.

Galicia sigue siendo un RSS; Euskadi pasó al buscador oficial paginado en C4.3
(ver el docstring de ``scraper/connectors/euskadi.py``), así que sus casos ya
no comparten conector.

**Las fixtures de Euskadi están grabadas de la fuente real.** El test anterior
usaba un enlace inventado (``https://www.euskadi.eus/x?N=100``) que traía el
``?N=`` que el extractor de ids necesitaba; el feed real no lo trae, así que la
suite pasaba en verde sobre un conector que en producción ingería **cero**
filas. Una fixture inventada sólo prueba que el código hace lo que el propio
autor supuso.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest

from scraper.connectors.base import ConnectorRunResult
from scraper.connectors.euskadi import EuskadiApiConnector
from scraper.connectors.galicia import GaliciaRssConnector


class _Response:
    def __init__(self, content: bytes) -> None:
        self.content = content

    def raise_for_status(self) -> None:
        return None


class _Session:
    def __init__(self, content: bytes) -> None:
        self.content = content
        self.calls: list[tuple[str, dict[str, Any]]] = []

    def get(self, url: str, **kwargs: Any) -> _Response:
        self.calls.append((url, kwargs))
        return _Response(self.content)


_GALICIA_RSS = b"""<?xml version="1.0" encoding="ISO-8859-1"?>
<rss version="2.0"><channel><item>
<title><![CDATA[AXI-2026-0028: Servizo de mantemento SAP - ID: 828765]]></title>
<link>https://www.contratosdegalicia.gal/licitacion?N=828765</link>
<description><![CDATA[<p><b>Estado:</b> En curso</p><p><b>&Oacute;rgano de contrataci&oacute;n:</b> Axencia Galega</p><p><b>Tipo de contrato:</b> Servizos</p><p><b>Importe:</b> 2.364.210,48 &euro;</p><p><b>Data de publicaci&oacute;n na plataforma:</b> 29-07-2026 07:53</p><p><b>Data e hora l&iacute;mite de presentaci&oacute;n de ofertas:</b> 07-09-2026 23:59</p>]]></description>
<guid>https://www.contratosdegalicia.gal/licitacion?N=828765</guid><pubDate>29-07-2026 07:53</pubDate>
</item></channel></rss>"""


def test_galicia_rss_fetches_and_parses_an_official_shape() -> None:
    session = _Session(_GALICIA_RSS)
    connector = GaliciaRssConnector(session=session)

    notices = list(connector.fetch(None))
    parsed = connector.parse(notices[0])

    assert session.calls[0][0] == connector.feed_url
    assert notices[0].natural_id == "828765"
    assert parsed is not None
    assert parsed.licitacion.id_externo == "galicia_rss:828765"
    assert parsed.licitacion.ccaa == "Galicia"
    assert parsed.licitacion.importe == 2364210.48
    assert parsed.licitacion.fecha_limite == "2026-09-07T23:59:00+00:00"
    assert connector.new_cursor() == {"last_seen_updated": "2026-07-29T07:53:00+00:00"}


def _fixture_euskadi() -> bytes:
    return (Path(__file__).parent / "fixtures" / "euskadi" / "busqueda_pagina.xml").read_bytes()


def test_euskadi_lee_los_campos_estructurados_de_la_pagina_real() -> None:
    """Los ``contratacion_*`` cuelgan de ``<documentMetaData>``, no del ``<item>``.

    Con una búsqueda entre hijos directos el conector leía el id y **todo lo
    demás en blanco**: filas sin título, sin fecha y sin órgano, persistidas sin
    que nada fallara.
    """
    session = _Session(_fixture_euskadi())
    connector = EuskadiApiConnector(session=session, page_size=3, max_paginas=1)

    avisos = list(connector.fetch(None))

    assert [a.natural_id for a in avisos] == [
        "expjaso739369",
        "expjaso739239",
        "expjaso739623",
    ]
    primero = avisos[0].payload
    assert primero["expediente"]
    assert primero["titulo"]
    assert primero["publicado"] == "2026-09-04"
    assert primero["estado"] == "AL"


def test_euskadi_pide_las_dos_claves_de_paginacion() -> None:
    """``r01kTgtPg`` sin ``r01kPgCmd`` devuelve 200 y la página 1 otra vez.

    Es un paginador roto en silencio: el run creería haber recorrido veinte
    páginas y habría releído la primera veinte veces.
    """
    session = _Session(_fixture_euskadi())
    connector = EuskadiApiConnector(session=session, page_size=3, max_paginas=1)

    list(connector.fetch(None))

    params = session.calls[0][1]["params"]
    assert params["r01kTgtPg"] == params["r01kPgCmd"] == "1"
    assert "pp:r01PageSize.3" in params["r01kQry"]


def test_euskadi_mapea_el_aviso_a_la_licitacion_canonica() -> None:
    session = _Session(_fixture_euskadi())
    connector = EuskadiApiConnector(session=session, page_size=3, max_paginas=1)
    avisos = list(connector.fetch(None))

    lic = connector.parse(avisos[0]).licitacion  # type: ignore[union-attr]

    assert lic.id_externo == "euskadi:expjaso739369"
    assert lic.fuente == "euskadi"
    assert lic.ccaa == "País Vasco"
    assert lic.tecnologia == "ORACLE"
    # `AL` es «Abierto / Plazo de presentación» en la ficha pública.
    assert lic.estado == "PUB"
    assert lic.fecha_publicacion == "2026-09-04"
    assert lic.fecha_limite == "2026-09-18T23:59:00"
    assert lic.url.endswith("/expjaso739369/es_doc/index.html")  # type: ignore[union-attr]
    # El NIF que la fuente antepone no viaja al nombre del órgano.
    assert not (lic.organo_contratacion or "").startswith(("S", "P", "Q"))
    # El buscador no publica importe: `None` dice eso, y no «cero».
    assert lic.importe is None and lic.importe_tipo is None


def test_euskadi_descarta_lo_que_no_es_tecnologia() -> None:
    session = _Session(_fixture_euskadi())
    connector = EuskadiApiConnector(session=session, page_size=3, max_paginas=1)
    avisos = list(connector.fetch(None))

    # El tercer aviso de la fixture es una encuesta de Eustat: pasa el fetch y
    # muere en el filtro, que es donde tiene que morir.
    assert connector.parse(avisos[2]) is None


def test_euskadi_para_cuando_la_pagina_es_toda_mas_vieja_que_el_cursor() -> None:
    """El resultado viene newest-first: detrás de una página vieja no hay nada nuevo."""
    session = _Session(_fixture_euskadi())
    connector = EuskadiApiConnector(session=session, page_size=3, max_paginas=9)

    avisos = list(connector.fetch({"last_seen_updated": "2026-12-31"}))

    assert avisos == []
    assert len(session.calls) == 1, "una página bastó para saber que no hay nada nuevo"


def test_euskadi_el_cursor_es_la_fecha_maxima_vista() -> None:
    session = _Session(_fixture_euskadi())
    connector = EuskadiApiConnector(session=session, page_size=3, max_paginas=1)

    list(connector.fetch(None))

    assert connector.new_cursor() == {"last_seen_updated": "2026-09-06"}


def test_euskadi_rechaza_una_url_fuera_del_dominio_oficial() -> None:
    connector = EuskadiApiConnector(base_url="https://example.invalid/buscador.jsp")

    with pytest.raises(ValueError, match="dominio oficial"):
        list(connector.fetch(None))


def test_galicia_cli_initializes_db_and_returns_connector_status(monkeypatch: Any) -> None:
    monkeypatch.setattr("db.database.init_db", lambda: None)
    monkeypatch.setattr(
        "scraper.connectors.base.run_connector",
        lambda connector: ConnectorRunResult(source_id=connector.source_id),
    )

    assert GaliciaRssConnector.source_id == "galicia_rss"
    from scraper.connectors.galicia import main

    assert main([]) == 0


def test_euskadi_cli_returns_nonzero_when_connector_reports_errors(monkeypatch: Any) -> None:
    monkeypatch.setattr("db.database.init_db", lambda: None)
    monkeypatch.setattr(
        "scraper.connectors.base.run_connector",
        lambda connector: ConnectorRunResult(source_id=connector.source_id, errores=1),
    )

    from scraper.connectors.euskadi import main

    assert main([]) == 1
