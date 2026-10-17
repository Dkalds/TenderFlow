"""Índice de ADR (``scripts/gen_adr_index.py``).

El primer test corre el gate de verdad sobre el repo —así CI lo ejecuta sin un
paso propio en el workflow—; el resto mueven una pieza cada uno sobre un
directorio de ADR mínimo.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from scripts import gen_adr_index


def test_el_indice_del_repo_esta_al_dia() -> None:
    adrs, errores = gen_adr_index.leer_adrs()
    assert not errores, "\n".join(errores)
    actual = gen_adr_index._INDEX.read_text(encoding="utf-8")
    esperado = gen_adr_index._reemplaza(actual, gen_adr_index.render_block(adrs))
    assert actual == esperado, "docs/adr/README.md desfasado: python scripts/gen_adr_index.py"


def _adr(numero: int, slug: str, cuerpo_frontmatter: str) -> tuple[str, str]:
    return f"ADR-{numero:03d}-{slug}.md", f"---\n{cuerpo_frontmatter}\n---\n\n# ADR-{numero:03d}\n"


@pytest.fixture()
def directorio(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    monkeypatch.setattr(gen_adr_index, "_ADR_DIR", tmp_path)
    monkeypatch.setattr(gen_adr_index, "_INDEX", tmp_path / "README.md")
    (tmp_path / "README.md").write_text(
        f"# ADR\n\n{gen_adr_index._BEGIN}\n{gen_adr_index._END}\n", encoding="utf-8"
    )
    return tmp_path


def _escribe(directorio: Path, *adrs: tuple[str, str]) -> None:
    for nombre, texto in adrs:
        (directorio / nombre).write_text(texto, encoding="utf-8")


def test_referencias_sueltas_y_wikilink_se_resuelven_a_links_markdown(directorio: Path) -> None:
    _escribe(
        directorio,
        _adr(1, "viejo", 'id: ADR-001\ntitle: "Viejo"\nstatus: superseded\nsuperseded_by: ADR-002'),
        _adr(
            2,
            "nuevo",
            'id: ADR-002\ntitle: "Nuevo | con barra"\nstatus: accepted\n'
            'superseded_parcialmente_por: "[[ADR-003-otro]]"',
        ),
        _adr(3, "otro", 'id: ADR-003\ntitle: "Otro"\nstatus: accepted\ndate: 2026-10-17'),
    )

    adrs, errores = gen_adr_index.leer_adrs()
    bloque = gen_adr_index.render_block(adrs)

    assert errores == []
    assert (
        "| [ADR-001](ADR-001-viejo.md) | Viejo | `superseded` | — | [ADR-002](ADR-002-nuevo.md) |"
        in bloque
    )
    assert "Nuevo \\| con barra" in bloque
    assert "[ADR-003](ADR-003-otro.md) (en parte)" in bloque
    assert "[[" not in bloque


@pytest.mark.parametrize(
    ("frontmatter", "error"),
    [
        ('title: "Sin id"\nstatus: accepted', "sin `id: ADR-NNN`"),
        ("id: ADR-001\nstatus: aceptado", "`status: aceptado` no está en el vocabulario"),
        ("id: ADR-001\nstatus: superseded", "`status: superseded` sin `superseded_by`"),
        ("id: ADR-001\nstatus: superseded\nsuperseded_by: ADR-099", "cita ADR-099, que no existe"),
    ],
)
def test_frontmatter_invalido_falla(directorio: Path, frontmatter: str, error: str) -> None:
    _escribe(directorio, _adr(1, "uno", frontmatter))

    _, errores = gen_adr_index.leer_adrs()

    assert any(error in e for e in errores), errores


def test_adr_sin_frontmatter_falla(directorio: Path) -> None:
    (directorio / "ADR-001-uno.md").write_text(
        "# ADR-001\n\n- **Estado:** aceptado\n", encoding="utf-8"
    )

    _, errores = gen_adr_index.leer_adrs()

    assert errores == ["ADR-001-uno.md: sin frontmatter YAML"]


def test_id_repetido_falla(directorio: Path) -> None:
    _escribe(
        directorio,
        _adr(1, "uno", "id: ADR-001\nstatus: accepted"),
        ("0001-otro.md", "---\nid: ADR-0001\nstatus: accepted\n---\n"),
    )

    _, errores = gen_adr_index.leer_adrs()

    assert any("repetido" in e for e in errores), errores
