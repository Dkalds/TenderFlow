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
**Calibrados contra producción el 2026-09-06** (C4.5). Cada uno lleva su valor
medido, su fecha y su margen, y el límite se *deriva* de los tres: nadie escribe
un número a mano. ``--explain`` imprime la tabla.

Lo que la calibración encontró, y explica por qué el ítem existía: el umbral
anterior de ``fecha_limite`` era 60 % y **todas** las fuentes con volumen lo
superaban —PSCP 96,6 %, PLACSP 93,1 %, TED 65,6 %, los backfills mensuales
100 %—. Un gate que no puede estar verde no mide nada: o el cron llevaba meses
en rojo o no corría. Un umbral que la realidad nunca ha cumplido no es un
objetivo de calidad, es una alarma rota.

La calibración cambia lo que el control **afirma**: ya no dice "así de bueno
tiene que ser el dato" (una afirmación que nadie había validado), sino "así de
bueno es hoy, y no puede empeorar más de un 10 %". Subir la calidad es otro
trabajo, con su propio ítem; lo que este control protege es que no baje.
"""

from __future__ import annotations

import argparse
import json
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

# ── Umbrales calibrados (ver "Umbrales" en el docstring) ─────────────────────

#: Margen por defecto sobre el valor medido, en porcentaje relativo.
#:
#: Diez puntos porcentuales relativos: si hoy el 96,6 % de PSCP no tiene plazo,
#: salta a partir del 106,3 %... que es imposible, y por eso los porcentajes se
#: recortan a 100. Para una métrica ya cerca del techo el margen protege poco;
#: para las que están lejos —la UTE en 8 %, el delta de baja— es donde el 10 %
#: hace su trabajo.
MARGEN_RELATIVO_PCT = 10.0


@dataclass(frozen=True, slots=True)
class Umbral:
    """Un umbral con procedencia: qué se midió, cuándo, y cuánto se tolera.

    Un número suelto en una constante no dice si es un objetivo de calidad o una
    foto de la realidad, y esas dos cosas se rompen de forma distinta. Aquí el
    límite se deriva del valor medido, así que recalibrar es cambiar `medido` y
    `fecha` — no inventar otro número.
    """

    nombre: str
    #: Valor observado en producción el día de `fecha`.
    medido: float
    fecha: str
    unidad: str
    motivo: str
    margen_pct: float = MARGEN_RELATIVO_PCT
    #: Techo natural de la métrica. Un porcentaje no puede pasar de 100.
    tope: float | None = None

    @property
    def limite(self) -> float:
        """Valor a partir del cual se considera regresión."""
        bruto = self.medido * (1.0 + self.margen_pct / 100.0)
        if self.tope is not None:
            bruto = min(bruto, self.tope)
        return round(bruto, 2)

    def supera(self, valor: float) -> bool:
        return valor > self.limite


#: Porcentaje de licitaciones sin `fecha_limite`, calibrado **por fuente**.
#:
#: Por fuente y no global porque las fuentes no son comparables: los backfills
#: mensuales (`bulk_YYYYMM`) están al 100 % y es correcto —son expedientes
#: históricos ya cerrados, donde el plazo no aplica—, mientras que PLACSP al
#: 93,1 % sí es un defecto del parser. Un umbral único obliga a elegir entre no
#: detectar nada o alertar siempre.
UMBRALES_FECHA_LIMITE: dict[str, Umbral] = {
    "pscp": Umbral(
        "fecha_limite/pscp",
        96.6,
        "2026-09-06",
        "%",
        "Censo de la Generalitat: la mayoría son publicaciones de fase sin plazo propio.",
        tope=100.0,
    ),
    "placsp": Umbral(
        "fecha_limite/placsp",
        93.1,
        "2026-09-06",
        "%",
        "El fix de Ola 1 extrae el campo, pero el histórico ingerido antes sigue sin él.",
        tope=100.0,
    ),
    "ted": Umbral(
        "fecha_limite/ted",
        65.6,
        "2026-09-06",
        "%",
        "TED publica plazo solo en una parte de los formularios.",
        tope=100.0,
    ),
}

#: Fuente no calibrada (un `bulk_YYYYMM` nuevo, un conector recién añadido).
#:
#: Al 100 % no detecta nada, y es deliberado: alertar sobre una fuente que nadie
#: ha medido produce ruido el día que se añade, justo cuando hay menos contexto
#: para interpretarlo. Lo que sí hace `--explain` es listarla como pendiente.
UMBRAL_FECHA_LIMITE_POR_DEFECTO = Umbral(
    "fecha_limite/(sin calibrar)",
    100.0,
    "2026-09-06",
    "%",
    "Fuente sin calibrar: se informa, no se alerta. Calibrala midiendo y añadiéndola arriba.",
    tope=100.0,
)

# Fuentes con poco volumen dan porcentajes ruidosos (3 de 4 licitaciones sin
# plazo es 75% y no significa nada). Por debajo de esto solo se informa.
MIN_LICITACIONES_PARA_EVALUAR = 50

UMBRAL_UTE = Umbral(
    "ute/pct_filas_afectadas",
    8.0,
    "2026-07-26",
    "%",
    "Defecto de modelado conocido y acumulado: detecta que crezca de golpe, no que exista.",
    tope=100.0,
)

UMBRAL_DELTA_BAJA = Umbral(
    "baja/delta_puntos",
    5.0,
    "2026-07-26",
    "puntos",
    "Distancia entre la baja por adjudicación y la agregada por licitación (multi-lote).",
)

#: Adjudicaciones con fecha anterior a 1990 (C4.4).
#:
#: 50 medidas el 2026-09-06 —el backlog contaba 47 el 2026-09-03, o sea que
#: crecían—. La mayoría son `1899-12-30`, el cero de la epoch de Excel: como
#: PSCP exporta una celda vacía. Desde C4.4 el conector las corta en el origen,
#: así que este umbral vigila que el histórico **no crezca**; bajarlo a 0 exige
#: limpiar las que ya están, que es otro trabajo.
UMBRAL_FECHAS_IMPOSIBLES = Umbral(
    "fechas/adjudicaciones_antes_de_1990",
    50,
    "2026-09-06",
    "filas",
    "Cero de la epoch de Excel exportado por PSCP. Cortado en el conector desde C4.4.",
    margen_pct=0.0,
)

#: Fecha desde la que una fila cuenta como "nueva" para la semántica del
#: importe: el día en que se aplicó `v112`. Las anteriores están en
#: `desconocido` por construcción.
IMPORTE_TIPO_DESDE = "2026-09-06"

#: Filas nuevas con importe y sin base declarada. Umbral 0 y margen 0: a partir
#: de `v112` todo camino de escritura pasa por un parser que sabe de dónde viene
#: el número. Una sola fila sin tipo significa que hay un camino que no lo
#: puebla, y eso no admite tolerancia.
UMBRAL_IMPORTE_SIN_TIPO = Umbral(
    "importe/filas_nuevas_sin_tipo",
    0,
    "2026-09-06",
    "filas",
    "Desde v112 el parser declara la base del importe; una fila nueva sin tipo es un "
    "camino de escritura que no la puebla.",
    margen_pct=0.0,
)

TODOS_LOS_UMBRALES: tuple[Umbral, ...] = (
    *UMBRALES_FECHA_LIMITE.values(),
    UMBRAL_FECHA_LIMITE_POR_DEFECTO,
    UMBRAL_UTE,
    UMBRAL_DELTA_BAJA,
    UMBRAL_FECHAS_IMPOSIBLES,
    UMBRAL_IMPORTE_SIN_TIPO,
)


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


def _medir_importe_sin_tipo() -> dict[str, Any]:
    """Filas nuevas cuyo importe no declara su base (C1.1)."""
    from db.domain_truth_audit import importe_sin_base_declarada

    return importe_sin_base_declarada(desde=IMPORTE_TIPO_DESDE)


def _medir_fechas_imposibles() -> dict[str, Any]:
    """Adjudicaciones con fecha anterior al año plausible (C4.4)."""
    from db.domain_truth_audit import adjudicaciones_con_fecha_imposible

    return adjudicaciones_con_fecha_imposible()


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
        ("fechas_imposibles", _medir_fechas_imposibles),
        ("importe_tipo", _medir_importe_sin_tipo),
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
        if total < MIN_LICITACIONES_PARA_EVALUAR:
            continue
        umbral = UMBRALES_FECHA_LIMITE.get(str(fila["fuente"]), UMBRAL_FECHA_LIMITE_POR_DEFECTO)
        if umbral.supera(pct):
            violaciones.append(
                f"fecha_limite: fuente '{fila['fuente']}' tiene {pct}% sin plazo "
                f"({fila['sin_fecha_limite']}/{total}); calibrado en "
                f"{umbral.medido}% el {umbral.fecha}, límite {umbral.limite}%"
            )

    ute = datos.get("ute", {})
    pct_ute = float(ute.get("pct_filas_afectadas") or 0.0)
    if UMBRAL_UTE.supera(pct_ute):
        violaciones.append(
            f"UTE: {pct_ute}% de las adjudicaciones parecen una UTE expandida "
            f"({ute.get('filas_afectadas')}/{ute.get('total_filas')}); calibrado en "
            f"{UMBRAL_UTE.medido}% el {UMBRAL_UTE.fecha}, límite {UMBRAL_UTE.limite}%"
        )

    delta = datos.get("baja", {}).get("delta_puntos")
    if delta is not None and UMBRAL_DELTA_BAJA.supera(abs(float(delta))):
        violaciones.append(
            f"baja_media_pct: {delta} puntos entre el cálculo por adjudicación y "
            f"el agregado por licitación; calibrado en {UMBRAL_DELTA_BAJA.medido} "
            f"el {UMBRAL_DELTA_BAJA.fecha}, límite {UMBRAL_DELTA_BAJA.limite}"
        )

    # C1.1 — importe sin base declarada en filas nuevas.
    importe = datos.get("importe_tipo", {})
    sin_tipo = importe.get("sin_tipo")
    if sin_tipo is not None and UMBRAL_IMPORTE_SIN_TIPO.supera(float(sin_tipo)):
        violaciones.append(
            f"importe: {sin_tipo} licitaciones ingeridas desde "
            f"{importe.get('desde')} tienen importe y no declaran su base "
            f"(`importe_tipo IS NULL`); umbral {UMBRAL_IMPORTE_SIN_TIPO.limite:.0f}. "
            f"Hay un camino de escritura que no pasa por el parser de v112."
        )

    # C4.4 — fechas de adjudicación imposibles.
    fechas = datos.get("fechas_imposibles", {})
    antes_de_1990 = fechas.get("antes_de_1990")
    if antes_de_1990 is not None and UMBRAL_FECHAS_IMPOSIBLES.supera(float(antes_de_1990)):
        violaciones.append(
            f"fechas: {antes_de_1990} adjudicaciones con fecha anterior a 1990; "
            f"calibrado en {UMBRAL_FECHAS_IMPOSIBLES.medido:.0f} el "
            f"{UMBRAL_FECHAS_IMPOSIBLES.fecha}. El conector las corta en el origen "
            f"desde C4.4, así que un aumento significa que entran por otro camino."
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

    print("\n── (e) Adjudicaciones con fecha imposible (C4.4) ──")
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
