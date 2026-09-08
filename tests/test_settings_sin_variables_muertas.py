"""Guardarraíl: ``config/settings.py`` no declara variables que nadie lee (C5.7).

Motivación
----------
Una variable de configuración declarada y no leída es peor que ninguna: promete
un comportamiento que no existe. ``EMBEDDING_VERSION`` llevaba desde el alta del
RAG con el comentario «si cambia, se re-embebe» y **cero lectores**; quien la
cambiara habría creído que forzaba un re-embebido y se habría quedado con los
vectores viejos y ningún error. ``ML_USE_TIMESERIES_CV`` prometía elegir el
esquema de validación cruzada, y su estrategia se había sustituido por
``GroupKFold`` — el propio código lo dice: «nunca llegaba a ejecutarse».

Ninguna herramienta las veía. Ruff no sabe que un atributo de un modelo de
configuración es un contrato con quien despliega, y los tests pasan igual: una
variable muerta no rompe nada, sólo miente.

Heurística
----------
Para cada campo en mayúsculas de ``Settings``, se busca su nombre en el resto
del repositorio (código, workflows, docs, `.env.example`, frontend). Basta una
mención: una variable puede leerse por ``os.environ`` en un script, aparecer en
un `render.yaml` o documentarse en un runbook, y todas ellas son usos legítimos.
Lo que este test detecta es el caso extremo —**ni una sola mención en ninguna
parte**—, que no admite interpretación benévola.

Como el resto de ratchets del repo, la allowlist sólo puede encoger: el test
falla tanto por una variable nueva sin listar como por una entrada que ya no
corresponde a nada.
"""

from __future__ import annotations

import re
from pathlib import Path

_RAIZ = Path(__file__).resolve().parents[1]
_SETTINGS = _RAIZ / "config" / "settings.py"

_EXTENSIONES = {
    ".py",
    ".yml",
    ".yaml",
    ".md",
    ".ts",
    ".tsx",
    ".toml",
    ".cfg",
    ".json",
    ".example",
    ".sh",
}
_EXCLUIDOS = {".venv", "node_modules", "graphify-out", "__pycache__", ".git", ".next", "dist"}

# ── Allowlist: SOLO puede encoger ───────────────────────────────────────────
#
# Vacía. El barrido que introdujo este test encontró exactamente una variable
# muerta (`ML_USE_TIMESERIES_CV`) y se borró en vez de listarla. Una entrada
# aquí es una variable que se decidió conservar sin lectores, y debe explicar
# por qué alguien la leerá.
_ALLOWLIST: frozenset[str] = frozenset()


def _campos_declarados() -> list[str]:
    fuente = _SETTINGS.read_text(encoding="utf-8")
    cuerpo = fuente[fuente.index("class Settings(") :]
    return re.findall(r"^    ([A-Z][A-Z0-9_]*)\s*:", cuerpo, re.M)


def _corpus() -> str:
    partes: list[str] = []
    for ruta in _RAIZ.rglob("*"):
        if not ruta.is_file() or ruta.suffix not in _EXTENSIONES:
            continue
        if set(ruta.parts) & _EXCLUIDOS or ruta == _SETTINGS:
            continue
        try:
            partes.append(ruta.read_text(encoding="utf-8", errors="replace"))
        except OSError:  # pragma: no cover - ficheros efímeros
            continue
    return "\n".join(partes)


def test_ninguna_variable_de_settings_esta_muerta() -> None:
    campos = _campos_declarados()
    assert len(campos) > 100, "el parseo de Settings dejó de encontrar campos"

    corpus = _corpus()
    muertas = sorted(c for c in campos if not re.search(rf"\b{c}\b", corpus))

    nuevas = [c for c in muertas if c not in _ALLOWLIST]
    assert not nuevas, (
        "Variables declaradas en config/settings.py que no lee ni menciona nadie. "
        "Una variable así promete un comportamiento que no existe: usala de "
        f"verdad o borrala (C5.7): {nuevas}"
    )

    obsoletas = sorted(_ALLOWLIST - set(muertas))
    assert not obsoletas, f"Estas ya tienen lectores: quitalas de la allowlist. {obsoletas}"
