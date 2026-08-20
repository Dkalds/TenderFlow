"""Corpus golden del parser CODICE: casos reales congelados como snapshot.

Por qué existe
--------------
``tests/test_codice_parser.py`` construye su XML con builders parametrizados:
prueba la lógica del parser contra la forma que el propio test decide. Eso deja
fuera la clase de bug que más ha costado en producción -- ``fecha_limite`` que
llegaba NULL, lotes sin modelar, UTE contadas como una sola adjudicación,
la baja calculada contra el presupuesto del expediente en vez del del lote.
Ninguno era una regresión del parser: eran formas del feed real que ningún
fixture inventado codificaba.

Este test fija el contrato completo de salida para un corpus de expedientes,
comparando el árbol entero (licitación + lotes + adjudicaciones + documentos)
contra ``golden.jsonl``. Un cambio en cualquier campo derivado -- provincia
inferida del NUTS, importe con fallback a ``TotalAmount``, plazo convertido a
UTC -- rompe el test aunque nadie hubiera escrito una aserción para él.

Se parsea por el **camino de producción** (``_PlacspParseCore.parse_entry_elem``
de ``scraper/connectors/placsp.py``), no llamando a ``parse_entry`` directo: es
el único que además invoca ``parse_lotes`` y ``parse_document_references``, así
que es el que de verdad corre cuando el conector ingiere.

Disciplina del corpus
---------------------
**Cada incidente de datos en producción añade su expediente aquí ANTES del
fix.** El caso entra en rojo, el fix lo pone en verde, y a partir de ahí queda
protegido. El corpus solo crece: ``test_golden_corpus_no_encoge`` lo verifica.

Regenerar el golden tras un cambio intencionado del parser::

    ENV=dev python -m tests.test_codice_parser_golden --update

Revisá el diff resultante línea a línea: es la lista exacta de lo que el cambio
altera en la salida. Si aparece algo que no esperabas, el cambio tiene un efecto
que no habías previsto -- que es justo lo que este test existe para enseñar.

``fecha_extraccion`` se excluye de la comparación: lo rellena un
``default_factory`` con la hora actual y haría fallar el test cada segundo.
"""

from __future__ import annotations

import dataclasses
import json
from pathlib import Path
from typing import Any
from unittest.mock import patch

import pytest

_FIXTURES = Path(__file__).parent / "fixtures" / "placsp"
_GOLDEN = _FIXTURES / "golden.jsonl"

# El corpus solo crece (ver docstring). Bajar este número es un error, no un
# ajuste: significa que alguien borró un caso que un incidente real justificó.
_MIN_CASOS = 14

# Rellenado por `default_factory=now_utc_iso`: no es salida del parseo.
_CAMPOS_NO_DETERMINISTAS = frozenset({"fecha_extraccion"})


def _limpiar(payload: dict[str, Any]) -> dict[str, Any]:
    return {k: v for k, v in payload.items() if k not in _CAMPOS_NO_DETERMINISTAS}


def _as_dict(obj: Any) -> dict[str, Any]:
    return _limpiar(dataclasses.asdict(obj))


def _parse_fixture(path: Path) -> dict[str, Any] | None:
    """Parsea un fixture por el camino de producción del conector PLACSP.

    Devuelve ``None`` si el expediente se descarta (fuera del universo
    tecnológico), que también es un resultado que el golden congela.

    El rescate ML (``_ml_classify_entry``) se anula: depende de un modelo
    entrenado que no está en el repo, así que dejarlo activo haría que el
    resultado dependiese de qué artefacto haya en disco. Lo que este test
    verifica es el parseo CODICE, no la clasificación.
    """
    from lxml import etree

    import scraper.pipeline  # noqa: F401  -- registra el submódulo para el patch
    from scraper.connectors.placsp import _PlacspParseCore

    entry_elem = etree.fromstring(path.read_bytes())

    with patch("scraper.pipeline._ml_classify_entry", return_value=None):
        parsed = _PlacspParseCore().parse_entry_elem(entry_elem, fuente="placsp")

    if parsed is None:
        return None
    return {
        "licitacion": _as_dict(parsed.licitacion),
        "lotes": [_as_dict(lote) for lote in parsed.lotes],
        "adjudicaciones": [_as_dict(adj) for adj in parsed.adjudicaciones],
        "documentos": [_as_dict(doc) for doc in parsed.documentos],
    }


def _fixture_paths() -> list[Path]:
    return sorted(_FIXTURES.glob("*.xml"))


def _cargar_golden() -> dict[str, Any]:
    """Lee ``golden.jsonl`` ignorando cabecera de comentarios y líneas vacías."""
    entradas: dict[str, Any] = {}
    for linea in _GOLDEN.read_text(encoding="utf-8").splitlines():
        linea = linea.strip()
        if not linea or linea.startswith("#"):
            continue
        registro = json.loads(linea)
        entradas[registro["fixture"]] = registro["esperado"]
    return entradas


def test_golden_corpus_no_encoge() -> None:
    """El corpus solo crece: cada incidente de producción deja su caso aquí."""
    fixtures = _fixture_paths()
    assert len(fixtures) >= _MIN_CASOS, (
        f"El corpus tiene {len(fixtures)} casos y el mínimo es {_MIN_CASOS}. "
        "Borrar un caso elimina la protección que un incidente real justificó."
    )

    golden = _cargar_golden()
    sin_golden = sorted({p.name for p in fixtures} - set(golden))
    assert not sin_golden, (
        "Fixture(s) sin entrada en golden.jsonl -- regenerá con "
        f"`python -m tests.test_codice_parser_golden --update`: {sin_golden}"
    )

    huerfanos = sorted(set(golden) - {p.name for p in fixtures})
    assert not huerfanos, f"Entrada(s) de golden.jsonl sin fixture XML: {huerfanos}"


@pytest.mark.parametrize("fixture_path", _fixture_paths(), ids=lambda p: p.stem)
def test_parseo_coincide_con_el_golden(fixture_path: Path) -> None:
    """El árbol parseado completo coincide campo a campo con el golden."""
    esperado = _cargar_golden()[fixture_path.name]
    obtenido = _parse_fixture(fixture_path)

    assert obtenido == esperado, (
        f"El parseo de {fixture_path.name} cambió respecto al golden.\n"
        "Si el cambio es intencionado, regenerá el golden y revisá el diff:\n"
        "  ENV=dev python -m tests.test_codice_parser_golden --update"
    )


def _regenerar() -> None:
    """Reescribe ``golden.jsonl`` desde el parseo actual de cada fixture."""
    cabecera = [
        "# Golden del parser CODICE -- generado, NO editar a mano.",
        "#",
        '# Cada línea es {"fixture": <archivo XML>, "esperado": <árbol parseado>},',
        "# donde el árbol lleva licitacion + lotes + adjudicaciones + documentos y",
        "# omite `fecha_extraccion` (no determinista).",
        "#",
        "# Disciplina: cada incidente de datos en producción añade su expediente al",
        "# corpus ANTES del fix. El set solo crece.",
        "#",
        "# Regenerar: ENV=dev python -m tests.test_codice_parser_golden --update",
    ]
    lineas = list(cabecera)
    for path in _fixture_paths():
        registro = {"fixture": path.name, "esperado": _parse_fixture(path)}
        lineas.append(json.dumps(registro, ensure_ascii=False, sort_keys=True))
    _GOLDEN.write_text("\n".join(lineas) + "\n", encoding="utf-8")
    print(f"golden.jsonl regenerado con {len(_fixture_paths())} casos")


if __name__ == "__main__":
    import sys

    if "--update" in sys.argv:
        _regenerar()
    else:
        print(__doc__)
