"""La medición de ``cac:TenderingTerms`` sobre el corpus del parser (v149).

El script existe para contestar con un comando qué porcentaje de entradas trae
cada bloque y a qué nivel. Lo que se prueba es que cuenta lo que dice contar:
denominador de **todas** las entradas, nivel de expediente y de lote por
separado, y los dos supuestos que permite verificar (códigos crudos y
``AmountRate`` en porcentaje). Sin red: las entradas salen de los fixtures.
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
        )
    )

    assert medicion.entradas == 4
    assert medicion.con_lotes == 1
    assert medicion.terms_expediente == 3
    assert medicion.terms_lote == 1
    assert medicion.por_bloque["criterios"] == {"expediente": 2, "lote": 1, "cualquiera": 3}
    assert medicion.por_bloque["garantias"] == {"expediente": 2, "lote": 1, "cualquiera": 2}
    assert medicion.por_bloque["solvencia_tecnica"] == {
        "expediente": 1,
        "lote": 1,
        "cualquiera": 2,
    }
    assert medicion.por_bloque["solvencia_economica"]["cualquiera"] == 1
    assert medicion.por_bloque["clasificacion"]["cualquiera"] == 1
    # 5 del caso 12 (con subcriterios) + 3 del 16 + 4 del 17.
    assert medicion.criterios_filas == 12
    assert medicion.porcentajes_garantia == [5.0, 5.0]
    assert medicion.garantias_con_importe == 1
    assert medicion.codigos_garantia == {"2": 2, "1": 1}
    assert medicion.updated_min is not None and medicion.updated_max is not None


def test_el_informe_lleva_muestra_fecha_y_porcentajes() -> None:
    medicion = medir(_entradas("16_condiciones_expediente.xml", "03_sin_fecha_limite.xml"))

    informe = informe_markdown(medicion, muestra="dos fixtures", fecha="2026-10-12")

    assert "Muestra: dos fixtures — 2 entradas" in informe
    assert "Medido el 2026-10-12" in informe
    assert "| criterios | 50.0 % | 0.0 % | — | 50.0 % |" in informe
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
