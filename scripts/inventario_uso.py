#!/usr/bin/env python3
"""Inventario de uso: qué espacios, vistas y operaciones de la API se usan.

Cierra la mitad «con datos» del ítem de backlog *La telemetría de producto:
medir el uso por espacio antes de la siguiente ola*. AGENTS.md §0 pide
comprobar que una superficie nueva hace falta; este script da el dato para
comprobar que una existente sobra.

Dos tablas, cada una con su fuente:

``espacios``
    Aperturas por espacio y por vista a partir del evento ``espacio_abierto``
    de ``web/src/lib/analytics.ts``. Ese evento va a **Vercel Web Analytics**
    (``track`` de ``@vercel/analytics``) y no hay forma de leerlo desde el repo:
    el script lee un CSV exportado del panel (ver ``docs/UX_AUDIT.md``, «Uso
    por espacio y por vista», para los pasos). Columnas, sin importar
    mayúsculas: ``espacio``, ``vista`` (vacía en la fila del total del
    espacio) y una cuenta (``visitantes``/``visitors``, ``sesiones``,
    ``eventos``/``events``/``total``/``count``; si hay varias, gana la primera
    de esa lista). El catálogo de espacios y vistas se lee de
    ``web/src/lib/console-spaces.ts`` y ``web/src/lib/space-views.ts``, así
    que un espacio sin ninguna apertura sale con 0 en vez de desaparecer.

``api``
    Llamadas por operación a partir de ``http_requests_total`` (etiquetas
    ``method`` y ``handler`` de ``prometheus-fastapi-instrumentator``,
    ``api/app.py``). Tres fuentes, de mejor a peor:

    * ``--prometheus URL``: consulta en vivo al Prometheus de Render
      (``tenderflow-prometheus``, ``pserv`` privado, retención 30 días) con
      ``increase(...[30d])``. Solo se alcanza desde la red privada de Render.
    * ``--prom-json FICHERO``: la respuesta de ``/api/v1/query`` guardada (la
      misma consulta, ejecutada desde la shell del servicio o Grafana).
    * ``--metrics FICHERO``: un volcado del texto de ``GET /metrics``. Los
      contadores cuentan **desde el último arranque** del proceso, no 30 días:
      el script lo avisa en la cabecera.

    El catálogo de operaciones es ``api/superficie_congelada.txt`` más las
    ``NUEVAS`` de ``scripts/check_api_surface.py``. Una operación sin ninguna
    serie en la ventana cuenta 0 y sale en la lista de candidatas a encoger.

Sin fuentes, cada tabla sale con el catálogo y «pendiente de exportar»: no se
inventa ninguna cifra.

Solo biblioteca estándar. Uso::

    python scripts/inventario_uso.py                         # ambas, sin datos
    python scripts/inventario_uso.py espacios --csv export.csv
    python scripts/inventario_uso.py api --prom-json respuesta.json
    python scripts/inventario_uso.py api --prometheus http://tenderflow-prometheus:9090
    make inventario-uso ARGS="espacios --csv export.csv"
"""

from __future__ import annotations

import argparse
import csv
import importlib.util
import json
import re
import sys
import urllib.parse
import urllib.request
from collections.abc import Iterable, Sequence
from dataclasses import dataclass, field
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[1]
_CONSOLE_SPACES = _ROOT / "web" / "src" / "lib" / "console-spaces.ts"
_SPACE_VIEWS = _ROOT / "web" / "src" / "lib" / "space-views.ts"
_SUPERFICIE = _ROOT / "api" / "superficie_congelada.txt"
_CHECK_API_SURFACE = _ROOT / "scripts" / "check_api_surface.py"

#: Por debajo de este porcentaje, el espacio o la vista necesita una decisión
#: escrita (se queda, se fusiona o se retira): criterio del backlog.
UMBRAL_PCT = 2.0

#: Consulta de 30 días. ``increase`` absorbe los reinicios del proceso; ``sum
#: by`` junta los códigos de estado (``should_group_status_codes=False``).
CONSULTA_PROMQL = (
    'sum by (method, handler) (increase(http_requests_total{job="tenderflow-api"}[30d]))'
)

#: Columnas de cuenta aceptadas en el CSV, por preferencia: los visitantes
#: únicos del evento se parecen más a «sesiones» que el total de eventos.
_COLUMNAS_CUENTA = ("visitantes", "visitors", "sesiones", "eventos", "events", "total", "count")

PENDIENTE = "pendiente de exportar"


# ── Catálogo del frontend ───────────────────────────────────────────────────


def _bloque(texto: str, inicio: str) -> str:
    """El literal que empieza en la línea de ``inicio`` y acaba en ``];``/``};`` de columna 0."""
    pos = texto.find(inicio)
    if pos < 0:
        raise ValueError(f"no se encontró {inicio!r}")
    fin = re.search(r"^[\]}];", texto[pos:], flags=re.MULTILINE)
    if fin is None:
        raise ValueError(f"{inicio!r} no cierra")
    return texto[pos : pos + fin.start()]


def leer_espacios(ruta: Path = _CONSOLE_SPACES) -> list[str]:
    """Claves de ``CONSOLE_SPACES``, en el orden del rail."""
    bloque = _bloque(ruta.read_text(encoding="utf-8"), "export const CONSOLE_SPACES")
    return re.findall(r'^ {4}key: "([^"]+)"', bloque, flags=re.MULTILINE)


def leer_vistas(ruta: Path = _SPACE_VIEWS) -> dict[str, list[str]]:
    """``SPACE_VIEWS``: slug del espacio → claves de sus vistas, en orden."""
    bloque = _bloque(ruta.read_text(encoding="utf-8"), "export const SPACE_VIEWS")
    vistas: dict[str, list[str]] = {}
    actual: str | None = None
    for linea in bloque.splitlines():
        cabecera = re.match(r'^ {2}"?([a-z0-9-]+)"?: \[', linea)
        if cabecera:
            actual = cabecera.group(1)
            vistas[actual] = []
        if actual is not None:
            vistas[actual].extend(re.findall(r'\bkey: "([^"]+)"', linea))
    return vistas


# ── Espacios y vistas ───────────────────────────────────────────────────────


@dataclass
class UsoEspacios:
    """Cuentas leídas del CSV: total por espacio y por (espacio, vista)."""

    metrica: str
    por_espacio: dict[str, int] = field(default_factory=dict)
    por_vista: dict[tuple[str, str], int] = field(default_factory=dict)


def _entero(valor: str) -> int:
    limpio = valor.strip().replace("\xa0", "").replace(" ", "").replace(".", "").replace(",", "")
    return int(limpio) if limpio else 0


def leer_csv_espacios(ruta: Path) -> UsoEspacios:
    """Lee el CSV exportado de Vercel Analytics (ver la docstring del módulo)."""
    with ruta.open(encoding="utf-8-sig", newline="") as fh:
        lector = csv.DictReader(fh)
        cabeceras = {c.strip().lower(): c for c in (lector.fieldnames or [])}
        if "espacio" not in cabeceras:
            raise ValueError(f"{ruta}: falta la columna 'espacio' (hay: {sorted(cabeceras)})")
        metrica = next((c for c in _COLUMNAS_CUENTA if c in cabeceras), None)
        if metrica is None:
            raise ValueError(f"{ruta}: falta una columna de cuenta ({', '.join(_COLUMNAS_CUENTA)})")
        uso = UsoEspacios(metrica=metrica)
        col_esp, col_cta = cabeceras["espacio"], cabeceras[metrica]
        col_vista = cabeceras.get("vista")
        for fila in lector:
            espacio = (fila.get(col_esp) or "").strip()
            if not espacio:
                continue
            vista = (fila.get(col_vista) or "").strip() if col_vista else ""
            cuenta = _entero(fila.get(col_cta) or "")
            if vista:
                clave = (espacio, vista)
                uso.por_vista[clave] = uso.por_vista.get(clave, 0) + cuenta
            else:
                uso.por_espacio[espacio] = uso.por_espacio.get(espacio, 0) + cuenta
    return uso


def _pct(parte: int, total: int) -> float:
    return 100.0 * parte / total if total else 0.0


def tabla_espacios(
    espacios: Sequence[str],
    vistas: dict[str, list[str]],
    uso: UsoEspacios | None,
    umbral: float = UMBRAL_PCT,
) -> str:
    """Tabla Markdown de espacios y vistas, con la marca de decisión bajo el umbral.

    El % de un espacio es sobre el total de aperturas de espacios; el de una
    vista, sobre las aperturas de vistas de su espacio (el conmutador solo
    emite al cambiar de vista, así que no se mezcla con las del rail).
    """
    if uso is None:
        cabecera = "| Espacio | Vista | Aperturas | % | ¿Decisión? |\n|---|---|---:|---:|---|"
        filas: list[str] = []
        for e in espacios:
            filas.append(f"| `{e}` | — | {PENDIENTE} | — | — |")
            filas.extend(f"| `{e}` | `{v}` | {PENDIENTE} | — | — |" for v in vistas.get(e, []))
        return "\n".join([cabecera, *filas])

    total = sum(uso.por_espacio.values())
    cabecera = f"| Espacio | Vista | {uso.metrica} | % | ¿Decisión? |\n|---|---|---:|---:|---|"
    filas = []
    fuera = sorted(set(uso.por_espacio) - set(espacios))
    for e in [*espacios, *fuera]:
        n = uso.por_espacio.get(e, 0)
        pct = _pct(n, total)
        marca = (
            "fuera del catálogo" if e in fuera else ("**sí** (< umbral)" if pct < umbral else "")
        )
        filas.append(f"| `{e}` | — | {n} | {pct:.1f} | {marca} |")
        catalogo_v = vistas.get(e, [])
        medidas_v = sorted(v for (esp, v) in uso.por_vista if esp == e and v not in catalogo_v)
        total_v = sum(c for (esp, _), c in uso.por_vista.items() if esp == e)
        for v in [*catalogo_v, *medidas_v]:
            nv = uso.por_vista.get((e, v), 0)
            pv = _pct(nv, total_v)
            if v in medidas_v:
                mv = "fuera del catálogo"
            elif not total_v:
                mv = "sin aperturas de vista"
            else:
                mv = "**sí** (< umbral)" if pv < umbral else ""
            filas.append(f"| `{e}` | `{v}` | {nv} | {pv:.1f} | {mv} |")
    return "\n".join([cabecera, *filas, "", f"Total de aperturas de espacio: {total}."])


# ── Operaciones de la API ───────────────────────────────────────────────────


def _normalizar_ruta(ruta: str) -> str:
    """Quita los convertidores de Starlette (``{id:path}`` → ``{id}``)."""
    return re.sub(r"\{([^}:]+):[^}]+\}", r"{\1}", ruta)


def _clave(metodo: str, ruta: str) -> str:
    return f"{metodo.upper()} {_normalizar_ruta(ruta)}"


def leer_operaciones(
    superficie: Path = _SUPERFICIE, check_api_surface: Path = _CHECK_API_SURFACE
) -> list[str]:
    """Operaciones de la API: la línea base congelada más las ``NUEVAS`` justificadas.

    ``check_api_surface`` se carga por ruta para no depender de que
    ``scripts/`` esté en ``sys.path``; importarlo no arrastra la app (solo
    ``operaciones()`` lo hace, y aquí no se llama).
    """
    lineas = superficie.read_text(encoding="utf-8").splitlines()
    ops = {s for linea in lineas if (s := linea.strip()) and not s.startswith("#")}
    if check_api_surface.exists():
        spec = importlib.util.spec_from_file_location("_check_api_surface", check_api_surface)
        if spec is not None and spec.loader is not None:
            modulo = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(modulo)
            ops |= set(getattr(modulo, "NUEVAS", {}))
    return sorted(ops)


def contar_prom_json(datos: object) -> dict[str, float]:
    """Cuentas por operación de una respuesta de ``/api/v1/query`` (tipo ``vector``)."""
    if not isinstance(datos, dict) or datos.get("status") != "success":
        raise ValueError("la respuesta de Prometheus no es status=success")
    resultado = datos.get("data", {}).get("result", [])
    cuentas: dict[str, float] = {}
    for serie in resultado:
        metrica = serie.get("metric", {})
        metodo, handler = metrica.get("method"), metrica.get("handler")
        if not metodo or not handler:
            continue
        clave = _clave(metodo, handler)
        cuentas[clave] = cuentas.get(clave, 0.0) + float(serie["value"][1])
    return cuentas


# Voraz hasta la última ``}``: el valor de ``handler`` lleva llaves (``{id}``).
_LINEA_METRICA = re.compile(r"^http_requests_total\{(?P<etiquetas>.*)\}\s+(?P<valor>\S+)")
_ETIQUETA = re.compile(r'(\w+)="((?:[^"\\]|\\.)*)"')


def contar_metrics_texto(texto: str) -> dict[str, float]:
    """Cuentas por operación del texto de exposición de ``GET /metrics``."""
    cuentas: dict[str, float] = {}
    for linea in texto.splitlines():
        m = _LINEA_METRICA.match(linea)
        if not m:
            continue
        etiquetas = dict(_ETIQUETA.findall(m.group("etiquetas")))
        metodo, handler = etiquetas.get("method"), etiquetas.get("handler")
        if not metodo or not handler:
            continue
        clave = _clave(metodo, handler)
        cuentas[clave] = cuentas.get(clave, 0.0) + float(m.group("valor"))
    return cuentas


def consultar_prometheus(url: str, token_file: Path | None = None) -> dict[str, float]:
    """Lanza ``CONSULTA_PROMQL`` contra ``url`` (``http``/``https``)."""
    partes = urllib.parse.urlsplit(url)
    if partes.scheme not in ("http", "https"):
        raise ValueError(f"URL de Prometheus no http(s): {url!r}")
    consulta = urllib.parse.urlencode({"query": CONSULTA_PROMQL})
    url_consulta = f"{url.rstrip('/')}/api/v1/query?{consulta}"
    peticion = urllib.request.Request(url_consulta)  # noqa: S310 — esquema validado arriba
    if token_file is not None:
        token = token_file.read_text(encoding="utf-8").strip()
        peticion.add_header("Authorization", f"Bearer {token}")
    with urllib.request.urlopen(peticion, timeout=60) as respuesta:  # noqa: S310  # nosec B310 — idem
        return contar_prom_json(json.loads(respuesta.read().decode("utf-8")))


def sin_uso(operaciones: Iterable[str], cuentas: dict[str, float]) -> list[str]:
    """Operaciones del catálogo sin ninguna llamada (cuenta < 1 tras redondear)."""
    return [op for op in operaciones if round(cuentas.get(_clave(*op.split(" ", 1)), 0.0)) < 1]


def tabla_api(operaciones: Sequence[str], cuentas: dict[str, float] | None, fuente: str) -> str:
    """Resumen y lista de operaciones sin llamadas, en Markdown."""
    if cuentas is None:
        return (
            f"Operaciones en el catálogo: {len(operaciones)}. Llamadas por operación: "
            f"{PENDIENTE} (sin fuente de `http_requests_total`)."
        )
    catalogo = {_clave(*op.split(" ", 1)) for op in operaciones}
    vacias = sin_uso(operaciones, cuentas)
    fuera = sorted(k for k in cuentas if k not in catalogo and round(cuentas[k]) >= 1)
    lineas = [
        f"Fuente: {fuente}.",
        f"Operaciones en el catálogo: {len(operaciones)}; con al menos una llamada: "
        f"{len(operaciones) - len(vacias)}; **sin ninguna: {len(vacias)}**.",
        "",
        "Candidatas a encoger (`api/superficie_congelada.txt`):",
        "",
        *(f"- `{op}`" for op in vacias),
    ]
    if fuera:
        lineas += ["", "Handlers con llamadas que no están en el catálogo:", ""]
        lineas += [f"- `{k}` ({round(cuentas[k])})" for k in fuera]
    return "\n".join(lineas)


# ── CLI ─────────────────────────────────────────────────────────────────────


def _informe_espacios(csv_path: Path | None, umbral: float) -> str:
    uso = leer_csv_espacios(csv_path) if csv_path else None
    origen = f"CSV `{csv_path.name}`" if csv_path else PENDIENTE
    tabla = tabla_espacios(leer_espacios(), leer_vistas(), uso, umbral)
    return f"## Uso por espacio y por vista (fuente: {origen})\n\n{tabla}\n"


def _informe_api(args: argparse.Namespace) -> str:
    cuentas: dict[str, float] | None = None
    fuente = ""
    if args.prometheus:
        cuentas = consultar_prometheus(args.prometheus, args.token_file)
        fuente = f"Prometheus en vivo, `{CONSULTA_PROMQL}`"
    elif args.prom_json:
        cuentas = contar_prom_json(json.loads(args.prom_json.read_text(encoding="utf-8")))
        fuente = f"respuesta guardada de Prometheus `{args.prom_json.name}` (`{CONSULTA_PROMQL}`)"
    elif args.metrics:
        cuentas = contar_metrics_texto(args.metrics.read_text(encoding="utf-8"))
        fuente = (
            f"volcado de `/metrics` `{args.metrics.name}` — **contadores desde el último "
            "arranque del proceso, no 30 días**"
        )
    tabla = tabla_api(leer_operaciones(), cuentas, fuente)
    return f"## Operaciones de la API sin llamadas en 30 días\n\n{tabla}\n"


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Inventario de uso de espacios, vistas y operaciones de la API."
    )
    parser.add_argument("tabla", nargs="?", choices=("espacios", "api", "todo"), default="todo")
    parser.add_argument("--csv", type=Path, help="CSV exportado de Vercel Analytics")
    parser.add_argument(
        "--umbral", type=float, default=UMBRAL_PCT, help="%% bajo el que hay que decidir"
    )
    parser.add_argument("--prometheus", help="URL base de Prometheus (red privada de Render)")
    parser.add_argument("--token-file", type=Path, help="fichero con el Bearer para --prometheus")
    parser.add_argument("--prom-json", type=Path, help="respuesta guardada de /api/v1/query")
    parser.add_argument("--metrics", type=Path, help="volcado de texto de GET /metrics")
    args = parser.parse_args(argv)

    partes: list[str] = []
    if args.tabla in ("espacios", "todo"):
        partes.append(_informe_espacios(args.csv, args.umbral))
    if args.tabla in ("api", "todo"):
        partes.append(_informe_api(args))
    sys.stdout.write("\n".join(partes))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
