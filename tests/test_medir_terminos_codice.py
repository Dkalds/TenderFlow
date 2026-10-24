"""La medición de ``cac:TenderingTerms`` sobre el corpus del parser (v148).

El script existe para contestar con un comando qué porcentaje de entradas trae
cada bloque y a qué nivel. Lo que se prueba es que cuenta lo que dice contar:
denominador de **todas** las entradas, nivel de expediente y de lote por
separado, y los dos supuestos que permite verificar (códigos crudos y
``AmountRate`` en porcentaje). Sin red: las entradas salen de los fixtures.
Los casos 03, 16, 17 y 21 son expedientes reales del ATOM de PLACSP (ver
``tests/fixtures/placsp/README.md``); el 12 es sintético.
"""

from __future__ import annotations

from pathlib import Path

from lxml import etree

from scripts.medir_terminos_codice import informe_markdown, main, medir

_FIXTURES = Path(__file__).parent / "fixtures" / "placsp"


def _entradas(*nombres: str) -> list[etree._Element]:
    return [etree.fromstring((_FIXTURES / nombre).read_bytes()) for nombre in nombres]


def test_cuenta_bloques_por_nivel_sobre_todas_las_entradas() -> None:
    medicion = medir(
        _entradas(
            "03_sin_fecha_limite.xml",
            "12_procedimiento_tramitacion_criterios.xml",
            "16_condiciones_expediente.xml",
            "17_condiciones_por_lote.xml",
            "21_solvencia_umbral_real.xml",
        )
    )

    assert medicion.entradas == 5
    assert medicion.con_lotes == 1
    # El 03 (anuncio previo) trae `TenderingTerms` sin ninguno de los bloques.
    assert medicion.terms_expediente == 5
    assert medicion.terms_lote == 1
    assert medicion.por_bloque["criterios"] == {"expediente": 3, "lote": 1, "cualquiera": 4}
    # Como en el feed: ninguna garantía ni solvencia a nivel de lote.
    assert medicion.por_bloque["garantias"] == {"expediente": 3, "lote": 0, "cualquiera": 3}
    assert medicion.por_bloque["solvencia_tecnica"] == {
        "expediente": 3,
        "lote": 0,
        "cualquiera": 3,
    }
    assert medicion.por_bloque["solvencia_economica"]["cualquiera"] == 3
    assert medicion.por_bloque["clasificacion"]["cualquiera"] == 1
    # 5 del caso 12 (con subcriterios) + 4 del 16 + 9 del 17 (dos lotes) + 2 del 21.
    assert medicion.criterios_filas == 20
    assert medicion.porcentajes_garantia == [5.0, 5.0, 5.0, 5.0]
    assert medicion.garantias_con_importe == 0
    assert medicion.codigos_garantia == {"2": 3, "3": 1}
    # El 21 publica el volumen de negocios en `ThresholdQuantity`.
    assert medicion.solvencia_economica_con_umbral == 1
    assert {e: c["entradas"] for e, c in medicion.por_estado.items()} == {
        "PRE": 1,
        "PUB": 2,
        "EV": 2,
    }
    assert medicion.updated_min is not None and medicion.updated_max is not None


def test_el_informe_lleva_muestra_fecha_y_porcentajes() -> None:
    medicion = medir(_entradas("16_condiciones_expediente.xml", "03_sin_fecha_limite.xml"))

    informe = informe_markdown(medicion, muestra="dos fixtures", fecha="2026-10-12")

    assert "Muestra: dos fixtures — 2 entradas" in informe
    assert "Medido el 2026-10-12" in informe
    assert "| criterios | 50.0 % | 0.0 % | — | 50.0 % |" in informe
    assert "| EV | 1 | 100.0 % |" in informe
    assert "`AmountRate` de garantía: min 5.0" in informe


def test_main_lee_ficheros_atom(tmp_path: Path, capsys) -> None:  # type: ignore[no-untyped-def]
    """Un feed con dos entradas, leído desde disco como lo haría quien lo guardó."""
    cuerpos = b"".join(
        (_FIXTURES / nombre).read_bytes().split(b"?>", 1)[1]
        for nombre in ("16_condiciones_expediente.xml", "17_condiciones_por_lote.xml")
    )
    feed = tmp_path / "pagina_01.atom"
    feed.write_bytes(b'<feed xmlns="http://www.w3.org/2005/Atom">' + cuerpos + b"</feed>")

    assert main([str(feed)]) == 0

    salida = capsys.readouterr().out
    assert "2 entradas" in salida
    assert "| criterios | 50.0 % | 50.0 % | 100.0 % | 100.0 % |" in salida


def test_main_lee_un_zip_mensual_y_desglosa_por_estado(tmp_path: Path, capsys) -> None:  # type: ignore[no-untyped-def]
    """Los ZIP mensuales se miden igual que las páginas, y con la tabla por estado.

    La tabla por ``ContractFolderStatusCode`` es la que dice si una fase deja
    de publicar el bloque, que es lo que decide si el histórico se rellena.
    """
    import zipfile

    cuerpos = b"".join(
        (_FIXTURES / nombre).read_bytes().split(b"?>", 1)[1]
        for nombre in ("16_condiciones_expediente.xml", "03_sin_fecha_limite.xml")
    )
    feed = b'<feed xmlns="http://www.w3.org/2005/Atom">' + cuerpos + b"</feed>"
    zip_mensual = tmp_path / "licitacionesPerfilesContratanteCompleto3_202609.zip"
    with zipfile.ZipFile(zip_mensual, "w", compression=zipfile.ZIP_DEFLATED) as zf:
        zf.writestr("licitacionesPerfilesContratanteCompleto3.atom", feed)

    assert main([str(zip_mensual)]) == 0

    salida = capsys.readouterr().out
    assert "2 entradas" in salida
    assert "| PRE | 1 | 0.0 % |" in salida
    assert "| EV | 1 | 100.0 % |" in salida
