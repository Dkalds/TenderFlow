"""El recorte de expedientes reales al corpus golden (``scripts/capture_placsp_fixtures.py``).

Lo que se prueba es que el fixture escrito es el mismo XML que se leyó y que
los hooks de pre-commit no tienen nada que cambiarle: si ``trailing-whitespace``
quitase un espacio dentro de una descripción, el golden dejaría de casar con
el expediente real que dice congelar. Sin red: todo sale de bytes en memoria.
"""

from __future__ import annotations

from pathlib import Path

from lxml import etree

from scripts.capture_placsp_fixtures import SINTETICO_POR_CASO, _entry_id, serializar

_FIXTURES = Path(__file__).parent / "fixtures" / "placsp"

_FEED = (
    b'<feed xmlns="http://www.w3.org/2005/Atom">'
    b"<entry><id>https://contrataciondelestado.es/sindicacion/"
    b"licitacionesPerfilContratante/20767321</id>"
    b"<title>Linea con espacio final \n y tabulador\t\nfin</title></entry>\n"
    b"</feed>"
)


def _entry() -> etree._Element:
    return next(etree.fromstring(_FEED).iter("{http://www.w3.org/2005/Atom}entry"))


def test_serializar_deja_el_xml_intacto_y_sin_espacios_finales() -> None:
    entry = _entry()

    salida = serializar(entry)

    assert salida.startswith(b'<?xml version="1.0" encoding="UTF-8"?>\n<entry')
    assert salida.endswith(b"</entry>\n")
    assert not any(linea.endswith((b" ", b"\t")) for linea in salida.split(b"\n"))
    releido = etree.fromstring(salida)
    assert releido.findtext("{http://www.w3.org/2005/Atom}title") == entry.findtext(
        "{http://www.w3.org/2005/Atom}title"
    )


def test_el_id_es_el_numero_final_del_id_atom() -> None:
    assert _entry_id(_entry()) == "20767321"


def test_cada_sustitucion_apunta_a_un_fixture_que_existe() -> None:
    faltan = sorted(n for n in SINTETICO_POR_CASO.values() if not (_FIXTURES / n).exists())
    assert not faltan
