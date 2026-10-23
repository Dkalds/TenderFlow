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
  (e) Proporción del corpus que el clasificador SAP marca por encima de
      ``ml_proba > 0.7`` — un binario que dice "SAP" a nueve de cada diez es
      una constante, no un clasificador (backlog P2, S6.1 del plan 2026-09).
  (f) Fechas guardadas como texto que no empiezan por ISO-8601. Es el contador
      que pide T2 del plan de arquitectura v2 («cuenta cero fechas no ISO») y,
      de paso, el número exacto de filas que hoy impiden promover a VALID los
      seis CHECK que ``v59`` dejó ``NOT VALID``.

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
Viven en ``services/verdad_dominio.py``, con su procedencia (valor medido,
fecha, margen) y el histórico de calibraciones. Están allí y no aquí porque la
consola los sirve también (``GET /admin/revision/verdad``) y ``api/`` no puede
importar un script. ``--explain`` imprime la tabla.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

# Re-exporta lo que bajó a `services/`: los tests y quien lea este script
# siguen encontrando aquí los umbrales con los que decide el cron.
from services.verdad_dominio import (
    IMPORTE_TIPO_DESDE,
    MARGEN_RELATIVO_PCT,
    MAX_FECHAS_NO_ISO,
    MAX_PCT_ML_PROBA_ALTA,
    MIN_LICITACIONES_PARA_EVALUAR,
    TODOS_LOS_UMBRALES,
    UMBRAL_DELTA_BAJA,
    UMBRAL_FECHA_LIMITE_POR_DEFECTO,
    UMBRAL_FECHAS_IMPOSIBLES,
    UMBRAL_IMPORTE_SIN_TIPO,
    UMBRAL_ML_PROBA_ALTA,
    UMBRAL_UTE,
    UMBRALES_FECHA_LIMITE,
    Umbral,
    evaluar,
    medir_bd,
)

__all__ = [
    "IMPORTE_TIPO_DESDE",
    "MARGEN_RELATIVO_PCT",
    "MAX_FECHAS_NO_ISO",
    "MAX_PCT_ML_PROBA_ALTA",
    "MIN_LICITACIONES_PARA_EVALUAR",
    "TODOS_LOS_UMBRALES",
    "UMBRALES_FECHA_LIMITE",
    "UMBRAL_DELTA_BAJA",
    "UMBRAL_FECHAS_IMPOSIBLES",
    "UMBRAL_FECHA_LIMITE_POR_DEFECTO",
    "UMBRAL_IMPORTE_SIN_TIPO",
    "UMBRAL_ML_PROBA_ALTA",
    "UMBRAL_UTE",
    "Umbral",
    "evaluar",
    "medir_todo",
]


# ── Medición ─────────────────────────────────────────────────────────────────


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


def medir_todo(max_zips: int) -> dict[str, Any]:
    """Las secciones de BD (``services.verdad_dominio.medir_bd``) más la (b).

    Cada sección aísla su fallo: una que revienta deja ``{"error": ...}`` en
    su hueco y no impide medir el resto -- la auditoría es más útil parcial
    que ausente. El orden es el del informe: la (b) va segunda.
    """
    bd = medir_bd()
    try:
        multi_lote: dict[str, Any] = _medir_multi_lote(max_zips)
    except Exception as exc:
        multi_lote = {"error": str(exc)}
    secciones: dict[str, Any] = {"fecha_limite": bd.pop("fecha_limite")}
    secciones["multi_lote"] = multi_lote
    secciones.update(bd)
    return secciones


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

    print("\n── (e) Discriminación del clasificador SAP (ml_proba) ──")
    seccion = datos["ml_proba"]
    if "error" in seccion:
        print(f"  ERROR: {seccion['error']}")
    else:
        print(f"  Población de scoring: {seccion['poblacion']}  (umbral {seccion['umbral']})")
        print(
            f"  Puntuadas: {seccion['puntuadas']}/{seccion['total_corpus']} filas; "
            f"por encima del umbral: {seccion['por_encima']}"
        )
        print(
            f"  % de las puntuadas por encima: {seccion['pct_puntuadas_por_encima']}   "
            f"(% del corpus: {seccion['pct_corpus_por_encima']})"
        )
        fuera = seccion["fuera_poblacion"]
        print(
            f"  Fuera de población: {fuera['total']} filas, {fuera['puntuadas']} con score "
            "(deberían ser 0)"
        )
    print("\n── (f) Adjudicaciones con fecha imposible (C4.4) ──")
    seccion = datos.get("fechas_imposibles", {})
    if "error" in seccion:
        print(f"  ERROR: {seccion['error']}")
    elif seccion:
        print(
            f"  Anteriores a {seccion['corte']}: {seccion['antes_de_1990']} "
            f"(límite {UMBRAL_FECHAS_IMPOSIBLES.limite:.0f})"
        )
        for fila in seccion.get("por_fuente", []):
            print(f"    · {fila['fuente']}: {fila['filas']}")

    print("\n── (g) Fechas de texto que no empiezan por ISO-8601 ──")
    seccion = datos["fechas_iso"]
    if "error" in seccion:
        print(f"  ERROR: {seccion['error']}")
    else:
        for fila in seccion["por_columna"]:
            check = "CHECK v59" if fila["tiene_check"] else "sin CHECK"
            print(
                f"  {fila['tabla']}.{fila['columna']:<28} "
                f"no_iso={fila['no_iso']:>7}/{fila['total']:<8} "
                f"({fila['pct_no_iso']}%)  [{check}]"
            )
        print(f"  Total no ISO: {seccion['total_no_iso']}  (objetivo {MAX_FECHAS_NO_ISO})")


def explicar_umbrales() -> None:
    """Imprime la tabla de umbrales con su procedencia (C4.5).

    Existe porque un umbral sin fecha ni valor medido no se puede recalibrar:
    quien lo mira dentro de seis meses no sabe si el número era un objetivo, una
    foto de la realidad o un placeholder que nadie tocó.
    """
    print("── Umbrales calibrados ──")
    print(f"  {'Umbral':<44} {'Medido':>10} {'Margen':>8} {'Límite':>10}  Fecha")
    for u in TODOS_LOS_UMBRALES:
        medido = f"{u.medido:g} {u.unidad}"
        print(f"  {u.nombre:<44} {medido:>10} {u.margen_pct:>7.0f}% {u.limite:>10g}  {u.fecha}")
    print()
    for u in TODOS_LOS_UMBRALES:
        print(f"  · {u.nombre}: {u.motivo}")
    print(
        "\n  El límite se DERIVA del valor medido y el margen; no se escribe a mano."
        "\n  Recalibrar = volver a medir, cambiar `medido` y `fecha`, y anotar el delta."
    )


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
    parser.add_argument(
        "--explain",
        action="store_true",
        help="Imprime la tabla de umbrales con su valor medido, margen y fecha, y sale",
    )
    args = parser.parse_args()

    # `--explain` no mide nada: responde "¿contra qué se compara?", que es una
    # pregunta sobre el script y no sobre la BD. Por eso no necesita conexión y
    # sale antes de abrirla.
    if args.explain:
        explicar_umbrales()
        return 0

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
