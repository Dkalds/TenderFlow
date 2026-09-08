"""Triaje de los avisos de Dependabot contra la política de `docs/SECURITY.md` (C2.5).

Por qué existe
--------------
La política fija plazos —alta ≤ 7 días, moderada ≤ 30— y `docs/SECURITY.md`
decía que medirlos «no tiene comando que lo derive del árbol: los avisos son
estado de GitHub». Es cierto que el estado vive en GitHub, y por eso este script
lo **consulta** en vez de derivarlo; lo que sí aporta el árbol es la mitad que
convierte una lista de avisos en un triaje:

1. **Si el manifiesto del aviso todavía existe.** Los tres avisos abiertos el
   2026-09-08 apuntan a `uv.lock`, retirado del árbol. Un aviso contra un
   fichero que ya no está no se parchea: se descarta con motivo (§ «Avisos
   fantasma»).
2. **Qué versión fija el manifiesto vivo.** `cryptography` está en
   `requirements.txt` como `==50.0.0` y los dos avisos se parchean en `49.0.0`:
   la versión que se despliega no es vulnerable, aunque el `uv.lock` del
   historial lo fuera.

Sin esas dos comprobaciones, «tres avisos abiertos, dos altos» parece deuda de
seguridad y es ruido de un fichero borrado — y confundirlos es lo que hace que
la siguiente vulnerabilidad de verdad se pierda entre los fantasmas.

Uso::

    python scripts/check_security_alerts.py            # informe
    python scripts/check_security_alerts.py --check    # falla si se incumple el SLA

Necesita `gh` autenticado con acceso al repositorio. Sin `gh`, informa y sale
con 0: es una herramienta de triaje, no una puerta de CI que pueda tumbar un
merge porque falte una credencial local.
"""

from __future__ import annotations

import json
import re
import shutil
import subprocess
import sys
from datetime import UTC, datetime
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parent.parent

#: Plazos de `docs/SECURITY.md`, en días. `None` = sin plazo fijo.
SLA_DIAS: dict[str, int | None] = {
    "critical": 2,
    "high": 7,
    "medium": 30,
    "low": None,
}

#: Manifiestos donde se busca la versión realmente desplegada, en orden.
_MANIFIESTOS_VIVOS = ("requirements.txt", "requirements.in", "pyproject.toml")


def _alertas() -> list[dict] | None:
    """Avisos abiertos, o ``None`` si `gh` no está disponible."""
    # Ruta absoluta: ruff S607 no admite rutas parciales, mismo criterio que
    # `scripts/run_mutation_sample.py::_mutmut_bin`.
    gh = shutil.which("gh")
    if gh is None:
        return None
    try:
        salida = subprocess.run(
            [
                gh,
                "api",
                "repos/{owner}/{repo}/dependabot/alerts",
                "--paginate",
                # `--slurp` y no `--jq`: con `--paginate`, `gh` emite un array
                # JSON **por página** y los concatena, así que `json.loads` solo
                # leería el primero y el informe saldría corto sin decir que lo
                # está. `--slurp` los envuelve en un array de arrays.
                "--slurp",
            ],
            cwd=_REPO_ROOT,
            capture_output=True,
            text=True,
            # Explícito: en Windows `text=True` decodifica con la codepage
            # local (cp1252) y un resumen de aviso con un guion largo la revienta.
            # Ese fallo llegaba como salida vacía, o sea «0 avisos abiertos»:
            # otra vez «sin datos» disfrazado de «todo bien».
            encoding="utf-8",
            errors="replace",
            timeout=60,
            check=False,
        )
    except (OSError, subprocess.TimeoutExpired):
        return None
    if salida.returncode != 0:
        return None
    try:
        paginas = json.loads(salida.stdout or "[]")
    except json.JSONDecodeError:
        return None
    # El filtro por estado va aquí y no en `--jq` para que la forma de la salida
    # no dependa de cuántas páginas devuelva la API.
    return [a for pagina in paginas for a in pagina if a.get("state") == "open"]


def _version_en_manifiestos_vivos(paquete: str) -> str | None:
    """Versión que fija algún manifiesto que SÍ está en el árbol, si alguno."""
    patron = re.compile(rf"^\s*[\"']?{re.escape(paquete)}\s*([=<>~!][^\s\\;\"']*)", re.M | re.I)
    for nombre in _MANIFIESTOS_VIVOS:
        fichero = _REPO_ROOT / nombre
        if not fichero.exists():
            continue
        m = patron.search(fichero.read_text(encoding="utf-8"))
        if m:
            return f"{nombre}: {paquete}{m.group(1)}"
    return None


def _dias_abierto(creado: str) -> int:
    nacido = datetime.fromisoformat(creado.replace("Z", "+00:00"))
    return (datetime.now(UTC) - nacido).days


def triar() -> tuple[list[str], list[str], bool]:
    """``(incumplimientos, informe, medido)``."""
    alertas = _alertas()
    if alertas is None:
        return (
            [],
            [
                "gh no disponible o sin acceso al repositorio: no se pudo consultar la "
                "pestaña de seguridad. El triaje sigue siendo acción del mantenedor."
            ],
            False,
        )

    incumplimientos: list[str] = []
    informe: list[str] = [f"Avisos abiertos: {len(alertas)}"]
    for a in alertas:
        sev = str(a["security_advisory"]["severity"]).lower()
        pkg = a["dependency"]["package"]["name"]
        manifiesto = a["dependency"].get("manifest_path") or "?"
        dias = _dias_abierto(a["created_at"])
        vive = (_REPO_ROOT / manifiesto).exists()
        parcheado = (a["security_vulnerability"].get("first_patched_version") or {}).get(
            "identifier", "?"
        )
        en_vivo = _version_en_manifiestos_vivos(pkg)

        etiqueta = f"  #{a['number']} [{sev}] {pkg} ({manifiesto}) — {dias} d abierto"
        if not vive:
            etiqueta += "  ⟶ FANTASMA: el manifiesto no está en el árbol"
            if en_vivo:
                etiqueta += f"; el vivo fija {en_vivo} (parcheado en {parcheado})"
            else:
                etiqueta += f"; ningún manifiesto vivo declara {pkg}"
            informe.append(etiqueta)
            # Un fantasma no incumple el plazo: no hay nada que parchear. Lo que
            # queda es descartarlo con motivo, y eso es acción del mantenedor.
            continue

        informe.append(etiqueta + f"  ⟶ parcheado en {parcheado}")
        limite = SLA_DIAS.get(sev)
        if limite is not None and dias > limite:
            incumplimientos.append(
                f"#{a['number']} {pkg} [{sev}] lleva {dias} días abierto; "
                f"el plazo de docs/SECURITY.md es {limite}."
            )
    return incumplimientos, informe, True


def main(argv: list[str]) -> int:
    incumplimientos, informe, medido = triar()
    print("\n".join(informe))
    if not medido:
        # No decir «cumplido» cuando no se ha medido nada: confundir «sin datos»
        # con «todo bien» es exactamente el error que este script existe para
        # evitar, y cometerlo aquí sería peor que no tenerlo.
        print("\nSLA de docs/SECURITY.md: NO MEDIDO.")
        return 0
    if not incumplimientos:
        print("\nSLA de docs/SECURITY.md: cumplido.")
        return 0
    print("\nFuera de plazo:")
    for linea in incumplimientos:
        print(f"  - {linea}")
    return 1 if "--check" in argv else 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
