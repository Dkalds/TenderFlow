"""Puerta de `npm audit` con excepciones fechadas (job «Security audit» de CI).

Por qué existe
--------------
`npm audit --audit-level=high` no admite excepciones: pasa todo o falla todo. El
2026-10-03 eso dejó el job en rojo en todas las ramas por GHSA-vfj7-8cjw-p6xm
(`braces <= 3.0.3`), un aviso **sin versión corregida** que solo entra por el
plugin de ESLint de Next. Un check que está siempre rojo no distingue el aviso
siguiente: el job ya fallaba antes de que llegara.

Este script mantiene la puerta —cualquier aviso `high` o `critical` falla,
también en dependencias de desarrollo— y añade lo que `pip-audit` ya tiene en el
mismo job con `--ignore-vuln`: una lista de excepciones. Con dos reglas para que
la lista no se pudra:

1. **Caducan.** Pasada la fecha, la excepción deja de valer y el job vuelve a
   fallar: toca re-evaluar (¿ya hay parche?) y renovarla o retirarla.
2. **No pueden sobrar.** Una excepción que ya no tapa ningún aviso bloqueante
   falla también: se retira en el mismo cambio que arregla la dependencia.

Uso::

    python scripts/check_npm_audit.py

Exit 0 si no hay avisos bloqueantes fuera de excepción; 1 si los hay, si una
excepción caducó o sobra, o si `npm audit` no devolvió un informe — es una
puerta de CI, y «no medido» no es «limpio».
"""

from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
import sys
from dataclasses import dataclass
from datetime import UTC, date, datetime
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parent.parent
_WEB = _REPO_ROOT / "web"

#: Las mismas severidades que tumbaban el job con `--audit-level=high`.
_BLOQUEANTES = frozenset({"high", "critical"})
_GHSA = re.compile(r"GHSA(?:-[0-9a-z]{4}){3}")

#: Vida máxima de una excepción, de `alta` a `caduca`. Es el «re-evaluar
#: trimestralmente» de los `--ignore-vuln` de `pip-audit`, pero comprobado.
MAX_DIAS_EXCEPCION = 90


@dataclass(frozen=True)
class Excepcion:
    ghsa: str
    paquete: str
    alta: date
    #: Último día en que vale, incluido.
    caduca: date
    motivo: str


EXCEPCIONES: tuple[Excepcion, ...] = (
    Excepcion(
        ghsa="GHSA-vfj7-8cjw-p6xm",
        paquete="braces",
        alta=date(2026, 10, 3),
        caduca=date(2026, 11, 3),
        motivo=(
            "Sin versión corregida: 3.0.3 es la última publicada y el arreglo "
            "(micromatch/braces#72) sigue sin fusionar. Solo entra por "
            "eslint-config-next (@next/eslint-plugin-next, fast-glob, micromatch), "
            "que expande los globs de `rootDir` de nuestra propia configuración de "
            "ESLint: no viaja a producción ni recibe entrada ajena. Al renovar, "
            "comprobar antes `npm view braces version`."
        ),
    ),
)


@dataclass(frozen=True)
class Aviso:
    ident: str
    paquete: str
    severidad: str
    titulo: str


def avisos(informe: dict) -> dict[str, Aviso]:
    """Avisos reales del informe, por identificador.

    Solo cuentan las entradas de `via` que son objetos. Las que son cadenas
    nombran al paquete del que se hereda el aviso (`micromatch` → `braces`): el
    informe del 2026-10-03 lista cinco paquetes «vulnerables» y un solo aviso.
    """
    encontrados: dict[str, Aviso] = {}
    for vulnerable in informe.get("vulnerabilities", {}).values():
        for via in vulnerable.get("via", []):
            if not isinstance(via, dict):
                continue
            url = str(via.get("url") or "")
            ghsa = _GHSA.search(url)
            # Sin GHSA en la URL el aviso sigue contando; lo que no puede es
            # exceptuarse, y eso es lo prudente con un aviso que no se sabe citar.
            ident = ghsa.group(0) if ghsa else url or f"{via.get('name')}#{via.get('source')}"
            encontrados[ident] = Aviso(
                ident=ident,
                paquete=str(via.get("name") or vulnerable.get("name") or "?"),
                severidad=str(via.get("severity") or "").lower(),
                titulo=str(via.get("title") or ""),
            )
    return encontrados


def evaluar(
    informe: dict, excepciones: tuple[Excepcion, ...], hoy: date
) -> tuple[list[str], list[str]]:
    """``(fallos, exceptuados)`` de aplicar las excepciones al informe."""
    bloqueantes = {i: a for i, a in avisos(informe).items() if a.severidad in _BLOQUEANTES}
    por_ghsa = {e.ghsa: e for e in excepciones}

    fallos: list[str] = []
    exceptuados: list[str] = []
    for ident, aviso in sorted(bloqueantes.items()):
        etiqueta = f"{ident} [{aviso.severidad}] {aviso.paquete}"
        excepcion = por_ghsa.get(ident)
        if excepcion is None:
            fallos.append(f"{etiqueta}: {aviso.titulo}")
        elif hoy > excepcion.caduca:
            fallos.append(
                f"{etiqueta}: la excepción caducó el {excepcion.caduca.isoformat()}. "
                "Re-evaluala: si ya hay versión corregida, actualizá el lockfile y "
                "retirala de EXCEPCIONES; si no, renovala con fecha nueva."
            )
        else:
            dias = (excepcion.caduca - hoy).days
            exceptuados.append(
                f"{etiqueta}: exceptuado hasta el {excepcion.caduca.isoformat()} "
                f"(quedan {dias} días). {excepcion.motivo}"
            )

    for excepcion in excepciones:
        if excepcion.ghsa not in bloqueantes:
            fallos.append(
                f"{excepcion.ghsa} ({excepcion.paquete}): la excepción sobra, ya no tapa "
                "ningún aviso high/critical. Retirala de EXCEPCIONES."
            )
    return fallos, exceptuados


def _parsear(salida: str) -> dict | None:
    """El informe, o ``None`` si lo que devolvió `npm audit --json` no lo es.

    Cuando el registro no contesta, `npm` emite `{"error": {...}}` en vez del
    informe. Sin `vulnerabilities` no hay nada que contar, y contar cero ahí
    sería dar por limpio lo que no se midió.
    """
    try:
        informe = json.loads(salida)
    except json.JSONDecodeError:
        return None
    if not isinstance(informe, dict) or "error" in informe:
        return None
    if not isinstance(informe.get("vulnerabilities"), dict):
        return None
    return informe


def _informe() -> dict | None:
    """Informe de `npm audit` sobre el lockfile de `web/`, o ``None`` si no se obtuvo."""
    # Ruta absoluta: ruff S607 no admite rutas parciales, mismo criterio que
    # `scripts/check_security_alerts.py::_alertas`.
    npm = shutil.which("npm")
    if npm is None:
        print("npm no está en el PATH.", file=sys.stderr)
        return None
    try:
        salida = subprocess.run(
            # `--package-lock-only`: se audita el lockfile commiteado, no lo que
            # haya (o no) en `node_modules`.
            [npm, "audit", "--json", "--package-lock-only"],
            cwd=_WEB,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=120,
            check=False,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        print(f"npm audit no terminó: {exc}", file=sys.stderr)
        return None
    # El código de salida no sirve para decidir: `npm audit` sale con 1 tanto si
    # encuentra avisos como si falla. Decide la forma de lo que imprimió.
    informe = _parsear(salida.stdout)
    if informe is None:
        print((salida.stderr or salida.stdout).strip()[-2000:], file=sys.stderr)
    return informe


def _hoy() -> date:
    return datetime.now(UTC).date()


def main() -> int:
    informe = _informe()
    if informe is None:
        print("npm audit: NO MEDIDO. Sin informe no hay veredicto.", file=sys.stderr)
        return 1

    fallos, exceptuados = evaluar(informe, EXCEPCIONES, _hoy())
    # En Actions la excepción sale como anotación del run: una excepción que
    # solo se ve abriendo el log del paso es la que nadie re-evalúa.
    prefijo = "::notice title=npm audit::" if os.environ.get("GITHUB_ACTIONS") else "EXCEPTUADO "
    for linea in exceptuados:
        print(f"{prefijo}{linea}")

    if fallos:
        for linea in fallos:
            print(f"ERROR {linea}", file=sys.stderr)
        print(f"\nnpm audit: {len(fallos)} problema/s high/critical.", file=sys.stderr)
        return 1
    print(
        f"npm audit: ningún aviso high/critical fuera de excepción "
        f"({len(exceptuados)} exceptuado/s)."
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
