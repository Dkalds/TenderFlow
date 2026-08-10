#!/usr/bin/env python3
"""Verifica que lo que ``config/settings.py`` EXIGE en producción esté declarado.

Motivación (revisión de arquitectura 2026-08): ``.env.example`` documenta ~63
variables y ``render.yaml`` declara 21, y nada comprobaba la relación entre
ambos. Un validador nuevo en ``Settings`` que exija una variable en
``ENV=prod``/``APP_PROFILE=api`` pasa CI en verde y revienta en el arranque del
contenedor, que es el peor sitio para enterarse.

Qué comprueba, en dos direcciones:

1. **Obligatorias sin declarar.** Toda variable que los ``model_validator`` de
   ``Settings`` exijan en producción tiene que aparecer en ``render.yaml`` (con
   valor o con ``sync: false``, que es como Render marca "la pongo yo en el
   dashboard").
2. **Documentación al día.** Toda variable declarada en ``render.yaml`` debería
   estar en ``.env.example``, que es donde un humano descubre qué se puede
   configurar.

Deliberadamente NO exige que todo ``.env.example`` esté en ``render.yaml``: hay
variables de scraper, de tests y de desarrollo local que no pintan nada en el
servicio web.

Uso::

    python scripts/check_env_parity.py

Exit 0 si todo cuadra; 1 con el detalle de lo que falta.
"""

from __future__ import annotations

import ast
import re
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).parent.parent
SETTINGS_PY = REPO_ROOT / "config" / "settings.py"
RENDER_YAML = REPO_ROOT / "render.yaml"
ENV_EXAMPLE = REPO_ROOT / ".env.example"

# Variables que los validadores exigen pero que no viven en el servicio web:
# las consumen los jobs de GitHub Actions, que llevan su propio bloque `env:`.
_NO_APLICA_AL_SERVICIO_WEB = frozenset(
    {
        "TEST_DATABASE_URL",
        "BACKUP_ENCRYPTION_KEY",
        "SMOKE_BASE_URL",
        "SMOKE_API_KEY",
        # Plano de alertas: lo consume `scheduler/healthcheck.py` desde GitHub
        # Actions (ver healthcheck.yml), que lleva su propio bloque `env:`.
        "ALERT_EMAIL_TO",
        "ALERT_SMTP_USER",
        "ALERT_SMTP_PASSWORD",
    }
)

# Huecos de documentación reales, pendientes de añadir a `.env.example`.
# Tocar `.env*` requiere OK explícito del responsable (AGENTS.md §6), así que
# quedan anotados aquí y en docs/IMPROVEMENT_BACKLOG.md en vez de arreglados de
# tapadillo. La lista solo puede encoger: al documentarlas, borrá la entrada.
_DOCUMENTACION_PENDIENTE = frozenset({"FRONTEND_URL", "SENTRY_DSN"})


def _sin_valor_por_defecto(node: ast.AnnAssign) -> bool:
    """True si el campo nace vacío, o sea que *puede* faltar en el entorno.

    Distingue "obligatoria" de "validada". ``ML_UNCERTAINTY_LO`` aparece en un
    ``raise`` porque su validador comprueba el rango, pero tiene default 0.4: no
    puede faltar. ``SIGNING_KEY`` nace como ``SecretStr("")`` y sí.
    """
    valor = node.value
    if valor is None:
        return True
    if isinstance(valor, ast.Constant):
        return valor.value in ("", None)
    # SecretStr("") y equivalentes: una llamada con un único literal vacío.
    if isinstance(valor, ast.Call) and len(valor.args) == 1:
        arg = valor.args[0]
        return isinstance(arg, ast.Constant) and arg.value == ""
    return False


def _required_in_prod() -> set[str]:
    """Variables que ``Settings`` exige y que pueden faltar en el entorno.

    Se leen del AST y no con un import: importar ``config.settings`` construye
    un ``Settings()``, que en un entorno sin variables falla precisamente por lo
    que este script quiere reportar.
    """
    tree = ast.parse(SETTINGS_PY.read_text(encoding="utf-8"))
    campos = {
        node.target.id: node
        for node in ast.walk(tree)
        if isinstance(node, ast.AnnAssign) and isinstance(node.target, ast.Name)
    }

    requeridas: set[str] = set()
    for node in ast.walk(tree):
        if not isinstance(node, ast.Raise):
            continue
        for texto in (n.value for n in ast.walk(node) if isinstance(n, ast.Constant)):
            if not isinstance(texto, str):
                continue
            for palabra in re.findall(r"\b[A-Z][A-Z0-9_]{3,}\b", texto):
                campo = campos.get(palabra)
                if campo is not None and _sin_valor_por_defecto(campo):
                    requeridas.add(palabra)
    return requeridas


def _declared_in_render() -> set[str]:
    """Claves de ``envVars`` de render.yaml (sin dependencias: regex sobre el YAML)."""
    texto = RENDER_YAML.read_text(encoding="utf-8")
    return set(re.findall(r"^\s*-\s*key:\s*([A-Z][A-Z0-9_]*)\s*$", texto, re.MULTILINE))


def _documented_in_example() -> set[str]:
    """Variables citadas en .env.example, tanto activas como comentadas."""
    texto = ENV_EXAMPLE.read_text(encoding="utf-8")
    return set(re.findall(r"^#?\s*([A-Z][A-Z0-9_]*)=", texto, re.MULTILINE))


def main() -> int:
    for ruta in (SETTINGS_PY, RENDER_YAML, ENV_EXAMPLE):
        if not ruta.exists():
            print(f"[check-env-parity] No existe {ruta.relative_to(REPO_ROOT)}.")
            return 1

    requeridas = _required_in_prod() - _NO_APLICA_AL_SERVICIO_WEB
    declaradas = _declared_in_render()
    documentadas = _documented_in_example()

    fallos = False

    sin_declarar = sorted(requeridas - declaradas)
    if sin_declarar:
        fallos = True
        print(
            "[check-env-parity] Variables que config/settings.py exige en producción "
            "y render.yaml no declara:\n"
        )
        for nombre in sin_declarar:
            print(f"  - {nombre}")
        print(
            "\nAñadilas a render.yaml (con `sync: false` si el valor se pone en el "
            "dashboard). Sin esto, el contenedor arranca y muere en el validador.\n"
        )

    sin_documentar = sorted(declaradas - documentadas - _DOCUMENTACION_PENDIENTE)
    sin_documentar = [n for n in sin_documentar if not n.startswith("GF_")]
    if sin_documentar:
        fallos = True
        print("[check-env-parity] Variables en render.yaml que .env.example no documenta:\n")
        for nombre in sin_documentar:
            print(f"  - {nombre}")
        print("\nDocumentalas en .env.example para que se puedan descubrir.\n")

    if fallos:
        return 1

    print(
        f"[check-env-parity] OK — las {len(requeridas)} variables obligatorias en "
        f"producción están en render.yaml, y sus {len(declaradas)} envVars están "
        "documentadas en .env.example."
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
