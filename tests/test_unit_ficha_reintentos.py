"""Las clases de fallo del selector de fichas siguen casando con los mensajes reales.

``list_pending_licitaciones`` decide si una ficha ``failed`` vuelve al lote
según su ``error_detail`` (``LIKE`` contra subcadenas). Los mensajes los
escriben otros módulos: si uno se reescribe y su subcadena deja de existir, la
ficha cae en la clase genérica sin que nada falle. Esto lo hace fallar aquí.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from db.repositories.tender_fact_sheets import (
    FALLOS_DE_DOCUMENTOS,
    FALLOS_DEL_PROVEEDOR,
    _patrones_like,
)

_RAIZ = Path(__file__).resolve().parent.parent
_FUENTES_DOCUMENTOS = (_RAIZ / "services" / "rag" / "fact_sheet.py",)
_FUENTES_PROVEEDOR = (
    _RAIZ / "llm" / "providers" / "__init__.py",
    _RAIZ / "llm" / "client.py",
    _RAIZ / "services" / "rag" / "fact_sheet.py",
)


def _texto(fuentes: tuple[Path, ...]) -> str:
    return "\n".join(f.read_text(encoding="utf-8") for f in fuentes)


@pytest.mark.parametrize("subcadena", FALLOS_DE_DOCUMENTOS)
def test_cada_fallo_de_documentos_sale_de_fact_sheet(subcadena: str) -> None:
    assert subcadena in _texto(_FUENTES_DOCUMENTOS)


@pytest.mark.parametrize("subcadena", FALLOS_DEL_PROVEEDOR)
def test_cada_fallo_del_proveedor_sale_de_su_modulo(subcadena: str) -> None:
    assert subcadena in _texto(_FUENTES_PROVEEDOR)


def test_las_dos_clases_no_se_solapan() -> None:
    """Un mensaje que casara con las dos tendría dos políticas de reintento."""
    for doc in FALLOS_DE_DOCUMENTOS:
        for prov in FALLOS_DEL_PROVEEDOR:
            assert doc not in prov and prov not in doc


def test_ninguna_subcadena_lleva_comodines_de_like() -> None:
    for patron in _patrones_like((*FALLOS_DE_DOCUMENTOS, *FALLOS_DEL_PROVEEDOR)):
        cuerpo = patron[1:-1]
        assert patron.startswith("%") and patron.endswith("%")
        assert "%" not in cuerpo and "_" not in cuerpo
