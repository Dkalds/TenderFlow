"""Auditoría de verdad del dato — Ola 0 del plan de corrección de dominio.

Mide, contra la BD y los ZIP mensuales ya cacheados, el tamaño real de los
defectos identificados (ver docs/IMPROVEMENT_BACKLOG.md):

  (a) % de licitaciones sin ``fecha_limite`` por fuente.
  (b) Expedientes con >1 ``TenderResult`` en los ZIP cacheados — proxy de
      multi-lote no modelado.
  (c) Adjudicaciones que comparten (licitacion_id, fecha_adjudicacion,
      importe_adjudicado) con distinto NIF — proxy de UTE mal contada.
  (d) Delta de ``baja_media_pct`` calculada por-adjudicación (código actual)
      vs. agregada por-licitación (el cálculo correcto).

Cada sección es independiente: un fallo en una no bloquea las demás.

Modos
-----
Sin flags imprime el informe legible, como siempre. Además:

  ``--json``   vuelca las mediciones como JSON (para diffear entre ejecuciones).
  ``--check``  compara contra los umbrales de abajo; sale 1 si alguno se supera.
  ``--alert``  manda un email por ``observability.notify`` con las violaciones.

``--alert`` implica ``--check`` y **siempre sale 0**: mismo contrato que
``scheduler/healthcheck.py`` — en un workflow programado la alerta es el correo,
no el rojo del job, que solo debe significar "la auditoría no pudo ejecutarse".

Uso::

    python scripts/audit_domain_truth.py                    # informe local
    python scripts/audit_domain_truth.py --check            # gate local (exit 1)
    python scripts/audit_domain_truth.py --check --alert    # cron nocturno

Umbrales
--------
Los de abajo son de arranque, elegidos holgados a propósito: el objetivo del
primer mes es detectar **empeoramientos bruscos**, no ratchear la calidad
actual. Tras una semana de ejecuciones hay que bajarlos al valor medido con
margen, igual que hizo el eval RAG (ver ``tests/eval/test_eval_rag.py``). Está
anotado en el backlog.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

# ── Umbrales (ver "Umbrales" en el docstring) ────────────────────────────────

# Antes del fix de Ola 1 esto era ~100% en PLACSP: el parser nunca extraía el
# campo. El umbral vigila que no vuelva a subir, no que baje a cero.
MAX_PCT_SIN_FECHA_LIMITE = 60.0

# Fuentes con poco volumen dan porcentajes ruidosos (3 de 4 licitaciones sin
# plazo es 75% y no significa nada). Por debajo de esto solo se informa.
MIN_LICITACIONES_PARA_EVALUAR = 50

# Proporción de filas de adjudicación que parecen una UTE expandida en N filas
# con el importe repetido. Es un defecto de modelado conocido y acumulado: el
# umbral detecta que crezca de golpe, no su existencia.
MAX_PCT_FILAS_UTE = 8.0

# Distancia entre la baja calculada por adjudicación y la agregada por
# licitación. Cuanto mayor, más expedientes multi-lote comparan cada lote
# contra el presupuesto total del expediente.
MAX_DELTA_BAJA_PUNTOS = 5.0


# ── Medición ─────────────────────────────────────────────────────────────────


def _medir_fecha_limite() -> dict[str, Any]:
    from db.domain_truth_audit import fecha_limite_gap_by_source

    return {"por_fuente": fecha_limite_gap_by_source()}


def _medir_multi_lote(max_zips: int) -> dict[str, Any]:
    from lxml import etree

    from config import settings
    from scraper.bulk_downloader import iter_xml_files
    from scraper.codice_parser import NS

    downloads_dir = settings.DOWNLOADS_DIR
    if downloads_dir is None or not downloads_dir.exists():
        return {"disponible": False, "motivo": f"Sin ZIP cacheados en {downloads_dir}"}

    zips = sorted(downloads_dir.glob("placsp_*.zip"), reverse=True)[:max_zips]
    if not zips:
        return {"disponible": False, "motivo": f"Sin ZIP cacheados en {downloads_dir}"}

    cfs = "./cacext:ContractFolderStatus"
    total_expedientes = 0
    multi_lote = 0
    parser = etree.XMLParser(huge_tree=False, recover=True, resolve_entities=False, no_network=True)

    for zip_path in zips:
        for _name, content in iter_xml_files(zip_path):
            try:
                root = etree.fromstring(content, parser=parser)
            except etree.XMLSyntaxError:
                continue
            for entry in root.iter("{http://www.w3.org/2005/Atom}entry"):
                results = entry.xpath(f"{cfs}/cac:TenderResult", namespaces=NS)
                total_expedientes += 1
                if len(results) > 1:
                    multi_lote += 1

    return {
        "disponible": True,
        "zips": [z.name for z in zips],
        "total_expedientes": total_expedientes,
        "multi_lote": multi_lote,
        "pct_multi_lote": (
            round(100.0 * multi_lote / total_expedientes, 2) if total_expedientes else 0.0
        ),
    }


def _medir_ute() -> dict[str, Any]:
    from db.domain_truth_audit import ute_candidate_stats

    return ute_candidate_stats()


def _medir_baja() -> dict[str, Any]:
    from db.domain_truth_audit import baja_media_delta

    stats = baja_media_delta()
    por_adj = stats["baja_media_pct_por_adjudicacion"]
    por_lic = stats["baja_media_pct_por_licitacion"]
    stats["delta_puntos"] = (
        round(float(por_adj) - float(por_lic), 2)
        if por_adj is not None and por_lic is not None
        else None
    )
    return stats


def medir_todo(max_zips: int) -> dict[str, Any]:
    """Ejecuta las cuatro secciones aislando el fallo de cada una.

    Una sección que revienta deja ``{"error": ...}`` en su hueco y no impide
    medir el resto -- la auditoría es más útil parcial que ausente.
    """
    secciones: dict[str, Any] = {}
    for clave, fn in (
        ("fecha_limite", _medir_fecha_limite),
        ("multi_lote", lambda: _medir_multi_lote(max_zips)),
        ("ute", _medir_ute),
        ("baja", _medir_baja),
    ):
        try:
            secciones[clave] = fn()
        except Exception as exc:
            secciones[clave] = {"error": str(exc)}
    return secciones


# ── Umbrales ─────────────────────────────────────────────────────────────────


def evaluar(datos: dict[str, Any]) -> list[str]:
    """Devuelve la lista de violaciones de umbral, vacía si todo está en rango.

    La sección (b) no se evalúa: depende de que haya ZIP en disco, y en un
    runner efímero no los hay. Se mide igual y se informa, pero no puede
    disparar una alerta que dependería del entorno y no del dato.
    """
    violaciones: list[str] = []

    fecha_limite = datos.get("fecha_limite", {})
    for fila in fecha_limite.get("por_fuente", []):
        total = int(fila["total"])
        pct = float(fila["pct_sin_fecha_limite"] or 0.0)
        if total >= MIN_LICITACIONES_PARA_EVALUAR and pct > MAX_PCT_SIN_FECHA_LIMITE:
            violaciones.append(
                f"fecha_limite: fuente '{fila['fuente']}' tiene {pct}% sin plazo "
                f"({fila['sin_fecha_limite']}/{total}), umbral {MAX_PCT_SIN_FECHA_LIMITE}%"
            )

    ute = datos.get("ute", {})
    pct_ute = float(ute.get("pct_filas_afectadas") or 0.0)
    if pct_ute > MAX_PCT_FILAS_UTE:
        violaciones.append(
            f"UTE: {pct_ute}% de las adjudicaciones parecen una UTE expandida "
            f"({ute.get('filas_afectadas')}/{ute.get('total_filas')}), "
            f"umbral {MAX_PCT_FILAS_UTE}%"
        )

    delta = datos.get("baja", {}).get("delta_puntos")
    if delta is not None and abs(float(delta)) > MAX_DELTA_BAJA_PUNTOS:
        violaciones.append(
            f"baja_media_pct: {delta} puntos entre el cálculo por adjudicación y "
            f"el agregado por licitación, umbral {MAX_DELTA_BAJA_PUNTOS}"
        )

    for clave, seccion in datos.items():
        if isinstance(seccion, dict) and "error" in seccion:
            violaciones.append(f"sección '{clave}' no pudo medirse: {seccion['error']}")

    return violaciones


# ── Presentación ─────────────────────────────────────────────────────────────


def render(datos: dict[str, Any]) -> None:
    print("── (a) Cobertura de fecha_limite por fuente ──")
    seccion = datos["fecha_limite"]
    if "error" in seccion:
        print(f"  ERROR: {seccion['error']}")
    elif not seccion["por_fuente"]:
        print("  Sin licitaciones en la BD.")
    else:
        for fila in seccion["por_fuente"]:
            print(
                f"  {fila['fuente']:<20} total={fila['total']:>7}  "
                f"sin_fecha_limite={fila['sin_fecha_limite']:>7}  "
                f"({fila['pct_sin_fecha_limite']}%)"
            )

    print("\n── (b) Expedientes con >1 TenderResult (proxy multi-lote) ──")
    seccion = datos["multi_lote"]
    if "error" in seccion:
        print(f"  ERROR: {seccion['error']}")
    elif not seccion.get("disponible"):
        print(f"  {seccion['motivo']} — nada que auditar.")
    else:
        print(f"  ZIP muestreados: {', '.join(seccion['zips'])}")
        print(
            f"  Total: {seccion['multi_lote']}/{seccion['total_expedientes']} "
            f"({seccion['pct_multi_lote']}%) expedientes con >1 TenderResult"
        )

    print("\n── (c) Adjudicaciones candidatas a UTE mal contada ──")
    seccion = datos["ute"]
    if "error" in seccion:
        print(f"  ERROR: {seccion['error']}")
    else:
        print(f"  Grupos candidatos: {seccion['grupos_candidatos']}")
        print(
            f"  Filas afectadas:   {seccion['filas_afectadas']}/{seccion['total_filas']} "
            f"({seccion['pct_filas_afectadas']}%)"
        )
        for g in seccion["muestra"]:
            print(
                f"    licitacion={g['licitacion_id']}  fecha={g['fecha_adjudicacion']}  "
                f"importe={g['importe_adjudicado']}  empresas_distintas={g['empresas_distintas']}  "
                f"filas={g['filas']}"
            )

    print("\n── (d) Delta baja_media_pct: por-adjudicación vs por-licitación ──")
    seccion = datos["baja"]
    if "error" in seccion:
        print(f"  ERROR: {seccion['error']}")
    else:
        print(
            f"  Por adjudicación (código actual, bajas.py):  "
            f"{seccion['baja_media_pct_por_adjudicacion']} (n={seccion['n_por_adjudicacion']})"
        )
        print(
            f"  Por licitación (agregado, correcto):          "
            f"{seccion['baja_media_pct_por_licitacion']} (n={seccion['n_por_licitacion']})"
        )
        if seccion["delta_puntos"] is not None:
            print(f"  Delta: {seccion['delta_puntos']} puntos porcentuales")


def _alertar(violaciones: list[str], datos: dict[str, Any]) -> None:
    from observability import AlertLevel, notify

    ute = datos.get("ute", {})
    notify(
        AlertLevel.WARN,
        "Auditoría de verdad del dato: umbrales superados",
        body="\n".join(f"- {v}" for v in violaciones),
        violaciones=len(violaciones),
        pct_filas_ute=ute.get("pct_filas_afectadas"),
        delta_baja_puntos=datos.get("baja", {}).get("delta_puntos"),
    )


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--max-zips",
        type=int,
        default=3,
        help="Nº de ZIP mensuales cacheados (más recientes) a muestrear para (b).",
    )
    parser.add_argument("--json", action="store_true", help="Vuelca las mediciones como JSON")
    parser.add_argument(
        "--check", action="store_true", help="Compara contra los umbrales; sale 1 si se superan"
    )
    parser.add_argument(
        "--alert",
        action="store_true",
        help="Envía las violaciones por email (implica --check y sale 0 siempre)",
    )
    args = parser.parse_args()

    from db.database import init_db

    init_db()

    datos = medir_todo(args.max_zips)

    if args.json:
        print(json.dumps(datos, indent=2, default=str))
    else:
        render(datos)

    if not (args.check or args.alert):
        return 0

    violaciones = evaluar(datos)
    if violaciones:
        print("\n── Umbrales superados ──", file=sys.stderr)
        for v in violaciones:
            print(f"  {v}", file=sys.stderr)
    else:
        print("\nTodos los umbrales dentro de rango.")

    if args.alert:
        if violaciones:
            _alertar(violaciones, datos)
        # Exit 0 deliberado: en un workflow programado el rojo debe significar
        # "la auditoría no pudo ejecutarse", no "el dato está mal" (que es lo
        # que comunica el email). Mismo contrato que scheduler/healthcheck.py.
        return 0

    return 1 if violaciones else 0


if __name__ == "__main__":
    sys.exit(main())
