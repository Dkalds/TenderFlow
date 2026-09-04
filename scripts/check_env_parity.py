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
#
# ALERTMANAGER_WEBHOOK_URL: la añade el Alertmanager (S6.3). Línea propuesta
# para `.env.example`, a la espera del OK humano:
#     # Segundo canal de alertas — dead-man's-switch del Watchdog. Opcional:
#     # vacío deshabilita el receptor `webhook` sin romper el de email.
#     # ALERTMANAGER_WEBHOOK_URL=https://hc-ping.com/<uuid>
_DOCUMENTACION_PENDIENTE = frozenset({"FRONTEND_URL", "SENTRY_DSN", "ALERTMANAGER_WEBHOOK_URL"})

WORKFLOWS_DIR = REPO_ROOT / ".github" / "workflows"

# ── RATCHET: `|| 'literal'` dentro de bloques `env:` de workflow ─────────────
# El idioma `X: ${{ vars.X || 'literal' }}` parece un default inocente y no lo
# es: cuando la variable de repositorio no está definida, el literal del YAML
# **sustituye** al default de `config/settings.py`, que es el que está probado.
# Son dos fuentes de verdad para el mismo valor y gana la del YAML, sin que
# ningún test la vea. Ya costó dos incidentes documentados en los comentarios de
# los propios ficheros: `deepseek-v4-pro` quedó EOL en NVIDIA el 2026-08-07 y
# devolvía 410; el default de `settings` ya estaba corregido, pero el literal
# del workflow lo pisaba y tumbó el lote entero de fichas.
#
# La forma correcta es exportar la variable a `$GITHUB_ENV` SOLO si está
# definida, de modo que el default vigente sea siempre el del código.
#
# Whitelist congelada: solo se QUITAN entradas, nunca se añaden. Las tres son
# trabajo pendiente, no excepciones permanentes:
#   - backup.yml / restore-drill.yml: fuera del alcance de S6 por decisión
#     explícita del responsable (tocan la cadena de copias y su restauración).
#   - train-predictivos.yml: lo lleva otro stream de trabajo; editarlo desde
#     aquí sería pisarle el fichero. Su caso es `ALERT_MIN_LEVEL`, el mismo
#     patrón que ya se corrigió en los otros seis workflows.
_ENV_FALLBACK_PENDIENTE = frozenset({"backup.yml", "restore-drill.yml", "train-predictivos.yml"})

# `${{ ... || 'literal' }}`. Solo el fallback a literal entrecomillado: un
# `a || b` entre dos expresiones no inventa un valor que compita con el default
# del código, que es lo que este ratchet persigue.
_FALLBACK_RE = re.compile(r"\|\|\s*'")


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


def _bloques_env(texto: str) -> list[tuple[int, str]]:
    """Devuelve ``(nº de línea, línea)`` de todo lo que cuelga de un ``env:``.

    Recorrido por indentación en vez de parseo YAML: este script es stdlib-only
    y la pregunta es puramente textual. Un ``env:`` abre bloque; el bloque dura
    mientras las líneas no vacías tengan MÁS indentación que él.

    Solo mira bloques ``env:``. Un ``|| '…'`` en un ``with:`` (por ejemplo
    ``aws-region``) o en un ``if:`` no es el problema que persigue el ratchet:
    lo que importa es lo que acaba en el ENTORNO del proceso pisando el default
    de ``config/settings.py``.
    """
    dentro: list[tuple[int, str]] = []
    sangria_env: int | None = None
    for numero, linea in enumerate(texto.splitlines(), start=1):
        if not linea.strip():
            continue
        sangria = len(linea) - len(linea.lstrip())
        if sangria_env is not None:
            if sangria > sangria_env:
                dentro.append((numero, linea))
                continue
            sangria_env = None
        if re.match(r"^\s*(-\s+)?env:\s*$", linea):
            # `- env:` (primer campo de un ítem de lista) indenta su contenido
            # respecto al guion, no respecto a la palabra `env`.
            sangria_env = sangria
    return dentro


def _fallbacks_en_workflows() -> list[str]:
    """Hallazgos de ``|| 'literal'`` dentro de bloques ``env:`` de workflow."""
    hallazgos: list[str] = []
    if not WORKFLOWS_DIR.is_dir():
        return hallazgos
    for ruta in sorted(WORKFLOWS_DIR.glob("*.yml")):
        if ruta.name in _ENV_FALLBACK_PENDIENTE:
            continue
        texto = ruta.read_text(encoding="utf-8")
        for numero, linea in _bloques_env(texto):
            # Los comentarios son inertes, y varios explican precisamente por
            # qué se quitó el `|| '…'` de esa línea. Marcarlos convertiría la
            # documentación del arreglo en un fallo del propio arreglo.
            if linea.lstrip().startswith("#"):
                continue
            if _FALLBACK_RE.search(linea):
                hallazgos.append(f"{ruta.name}:{numero}: {linea.strip()}")
    return hallazgos


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

    fallbacks = _fallbacks_en_workflows()
    if fallbacks:
        fallos = True
        print("[check-env-parity] Workflows con `|| 'literal'` dentro de un bloque `env:`:\n")
        for hallazgo in fallbacks:
            print(f"  - {hallazgo}")
        print(
            "\nEse literal SUSTITUYE al default de config/settings.py cuando la\n"
            "variable de repositorio no está definida, y el default del código es\n"
            "el que está probado. Ya costó dos incidentes (el modelo EOL\n"
            "deepseek-v4-pro tumbando el lote de fichas). En su lugar, exportá la\n"
            "variable a $GITHUB_ENV solo si está definida:\n\n"
            "      - name: Exportar overrides definidos\n"
            "        env:\n"
            "          VAR_X: ${{ vars.X }}\n"
            "        run: |\n"
            '          if [ -n "${VAR_X:-}" ]; then echo "X=$VAR_X" >> "$GITHUB_ENV"; fi\n'
        )

    if fallos:
        return 1

    print(
        f"[check-env-parity] OK — las {len(requeridas)} variables obligatorias en "
        f"producción están en render.yaml, sus {len(declaradas)} envVars están "
        "documentadas en .env.example, y ningún bloque `env:` de workflow pisa "
        "un default de config/settings.py."
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
