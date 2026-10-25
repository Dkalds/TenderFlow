"""El frontmatter de DESIGN.md no se separa de los tokens de globals.css.

DESIGN.md lleva en su frontmatter una copia de los tokens que Impeccable y su
panel live leen como norma. La fuente de verdad sigue siendo
`web/src/app/globals.css`: este test falla en cuanto un valor de la copia deja
de coincidir, para que un cambio de token se haga en los dos sitios a la vez.
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any

import pytest
import yaml

ROOT = Path(__file__).resolve().parent.parent
DESIGN_MD = ROOT / "DESIGN.md"
GLOBALS_CSS = ROOT / "web/src/app/globals.css"

DECLARACION = re.compile(r"^\s*--([a-z0-9-]+)\s*:\s*([^;]+);", re.MULTILINE)

# Rol tipográfico del frontmatter → paso de la escala `--text-tf-*`.
PASO_POR_ROL = {
    "display": "hero",
    "headline": "title",
    "kpi": "title",
    "title": "lede",
    "body": "body",
    "meta": "meta",
    "label": "micro",
    "label-column": "micro",
}


def _frontmatter() -> dict[str, Any]:
    texto = DESIGN_MD.read_text(encoding="utf-8")
    match = re.match(r"---\n(.*?)\n---\n", texto, re.DOTALL)
    assert match, "DESIGN.md no abre con un frontmatter YAML"
    datos = yaml.safe_load(match.group(1))
    assert isinstance(datos, dict)
    return datos


def _bloque(css: str, selector: str) -> str:
    """El cuerpo del primer bloque `selector { ... }`, sin sus bloques anidados."""
    inicio = css.index(f"{selector} {{") + len(selector) + 2
    profundidad, fin, plano = 1, inicio, []
    while profundidad:
        caracter = css[fin]
        if caracter == "{":
            profundidad += 1
        elif caracter == "}":
            profundidad -= 1
        elif profundidad == 1:
            plano.append(caracter)
        fin += 1
    return "".join(plano)


def _sin_comentarios(css: str) -> str:
    return re.sub(r"/\*.*?\*/", "", css, flags=re.DOTALL)


@pytest.fixture(scope="module")
def css() -> str:
    return _sin_comentarios(GLOBALS_CSS.read_text(encoding="utf-8"))


def _variables(cuerpo: str) -> dict[str, str]:
    return {nombre: valor.strip() for nombre, valor in DECLARACION.findall(cuerpo)}


def test_los_colores_del_frontmatter_son_los_de_globals_css(css: str) -> None:
    claro = _variables(_bloque(css, ":root"))
    oscuro = _variables(_bloque(css, ".dark"))
    distintos = []
    for clave, valor in _frontmatter()["colors"].items():
        tema, nombre = (
            (oscuro, clave.removesuffix("-dark")) if clave.endswith("-dark") else (claro, clave)
        )
        esperado = f"hsl({tema.get(nombre)})"
        if valor != esperado:
            distintos.append(f"{clave}: DESIGN.md dice {valor}, globals.css {esperado}")
    assert distintos == []


def test_la_tipografia_del_frontmatter_sigue_la_escala_tf(css: str) -> None:
    escala = _variables(css)
    distintos = []
    for rol, estilo in _frontmatter()["typography"].items():
        paso = PASO_POR_ROL.get(rol)
        if paso is None:
            continue
        base = f"text-tf-{paso}"
        if estilo["fontSize"] != escala[base]:
            distintos.append(f"{rol}.fontSize: {estilo['fontSize']} != {escala[base]}")
        if str(estilo["lineHeight"]) != escala[f"{base}--line-height"]:
            distintos.append(f"{rol}.lineHeight: {estilo['lineHeight']}")
        # El peso y el tracking solo los fija la escala en los pasos de titular;
        # en el resto los pone el rótulo que los usa (ROTULO_DATO, CABECERA_COLUMNA).
        for prop, sufijo in (("fontWeight", "font-weight"), ("letterSpacing", "letter-spacing")):
            fijado = escala.get(f"{base}--{sufijo}")
            if fijado is not None and str(estilo.get(prop)) != fijado and rol != "kpi":
                distintos.append(f"{rol}.{prop}: {estilo.get(prop)} != {fijado}")
    assert distintos == []


def test_los_radios_del_frontmatter_salen_de_radius(css: str) -> None:
    base_rem = float(_variables(_bloque(css, ":root"))["radius"].removesuffix("rem"))
    base_px = base_rem * 16
    esperado = {
        "sm": base_px - 4,
        "md": base_px - 2,
        "lg": base_px,
        "xl": base_px + 4,
    }
    rounded = _frontmatter()["rounded"]
    assert {k: float(rounded[k].removesuffix("px")) for k in esperado} == esperado
