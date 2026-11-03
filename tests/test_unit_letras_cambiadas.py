"""PDF con las tildes cambiadas («ClÆusula»): la reparación pura y el script.

Las palabras de los casos salen de producción (muestra del 2026-11-03): son la
tabla real, no una inventada. Lo que se fija es lo que haría daño: reparar un
documento sano, mover un offset, o no reparar uno afectado.
"""

from __future__ import annotations

import pytest

from scripts.reparar_letras_cambiadas import reparar
from shared.letras_cambiadas import (
    MIN_HUELLAS,
    reparar_paginas,
    reparar_texto,
    tiene_letras_cambiadas,
)

_AFECTADA = "La ClÆusula 5 deberÆ cumplirse segœn los tØrminos; los aæos y el CAP˝TULO II."
_SANA = "La Cláusula 5 deberá cumplirse según los términos; los años y el CAPÍTULO II."


def test_la_tabla_real_se_repara_entera() -> None:
    assert reparar_texto(_AFECTADA) == _SANA


def test_la_sustitucion_no_cambia_el_largo() -> None:
    """Los offsets de ``documento_pages`` y de las citas siguen valiendo."""
    assert len(reparar_texto(_AFECTADA)) == len(_AFECTADA)


def test_un_documento_sano_no_se_toca() -> None:
    paginas = [_SANA, "Sin tildes en esta página."]
    assert reparar_paginas(paginas) is paginas


def test_una_huella_suelta_no_basta() -> None:
    """Un nombre extranjero aislado no convierte el documento en afectado."""
    suelta = "Contrato con aÆb Holding."
    assert not tiene_letras_cambiadas([suelta])
    assert reparar_paginas([suelta]) == [suelta]


def test_el_umbral_se_cuenta_en_todo_el_documento() -> None:
    """Cada página con una huella: juntas pasan el umbral y se reparan todas."""
    paginas = ["deberÆn"] * MIN_HUELLAS + ["Los aæos"]
    assert reparar_paginas(paginas) == ["deberán"] * MIN_HUELLAS + ["Los años"]


class _RepoFalso:
    def __init__(self, documentos: dict[int, list[str]]) -> None:
        self.documentos = documentos
        self.escrito: dict[int, tuple[str, dict[int, str]]] = {}

    def max_documento_id(self) -> int:
        return max(self.documentos, default=0)

    def ids_con_huella(self, huella_sql: str, *, desde_id: int, hasta_id: int) -> list[int]:
        assert huella_sql
        return [
            i
            for i, paginas in self.documentos.items()
            if desde_id <= i < hasta_id and any(c in p for p in paginas for c in "ÆØœ")
        ]

    def get(self, documento_id: int) -> dict[str, object]:
        return {"texto": "\n".join(self.documentos[documento_id])}

    def list_pages(self, documento_id: int) -> list[dict[str, object]]:
        return [
            {"page_number": n, "texto": t} for n, t in enumerate(self.documentos[documento_id], 1)
        ]

    def reescribir_texto(self, documento_id: int, *, texto: str, paginas: dict[int, str]) -> None:
        self.escrito[documento_id] = (texto, paginas)


@pytest.mark.parametrize("aplicar", [False, True])
def test_el_script_cuenta_y_solo_escribe_con_aplicar(aplicar: bool) -> None:
    repo = _RepoFalso(
        {
            1: [_AFECTADA, "Página sin huella."],
            # Preseleccionado por SQL, pero con una sola huella: no se repara.
            5: ["Contrato con aÆb Holding."],
            9: [_SANA],
        }
    )

    recuento = reparar(repo, aplicar=aplicar, tramo=4)

    assert recuento == {"candidatos": 2, "reparados": 1, "paginas": 1}
    if not aplicar:
        assert repo.escrito == {}
        return
    texto, paginas = repo.escrito[1]
    assert paginas == {1: _SANA}
    assert texto == f"{_SANA}\nPágina sin huella."
