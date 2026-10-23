"""Verdad del dato: umbrales calibrados, medición sobre la BD y evaluación.

Es la parte de ``scripts/audit_domain_truth.py`` que no depende de ficheros en
disco, bajada a ``services/`` para que la consola la pueda servir
(``GET /admin/revision/verdad``) sin que ``api/`` importe un script ni
``scraper/`` (AGENTS.md §2: si dos capas necesitan la misma pieza, la pieza
baja). El script sigue siendo el que corre el cron y manda el correo; mide lo
mismo que aquí y añade la sección (b), multi-lote, que lee los ZIP cacheados
con el parser de ``scraper/`` y por eso no puede vivir en esta capa.

El SQL está en ``db/domain_truth_audit.py`` (ADR-022). Aquí queda lo que es
criterio: contra qué se compara cada número y cuándo es una regresión.

Los resultados de ``db/`` llegan como ``dict[str, Any]``: son filas agregadas
de forma distinta por sección, y tiparlas una a una duplicaría el contrato de
``db/domain_truth_audit.py`` sin añadir verificación. Lo que sale hacia la API
sí va tipado (:class:`SeccionVerdad`).

Umbrales
--------
**Calibrados contra producción el 2026-09-06** (C4.5). Cada uno lleva su valor
medido, su fecha y su margen, y el límite se *deriva* de los tres: nadie escribe
un número a mano. ``scripts/audit_domain_truth.py --explain`` imprime la tabla.

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

**Recalibración del 2026-09-18** sobre los ``domain-truth.json`` archivados de
siete ejecuciones programadas (12→18/09, artefacto
``domain-truth-measurements``). Histórico, por día:

=====  ======  =====  =====  =====  =====  ===========  ========
día    placsp  ted    pscp   UTE %  Δbaja  fechas<1990  sin_tipo
=====  ======  =====  =====  =====  =====  ===========  ========
09-12  89,8    65,4   96,6   0,02   1,10   50           131
09-13  89,8    65,4   96,6   0,02   1,10   50           131
09-14  89,8    65,2   96,6   0,02   1,10   50           152
09-15  85,0    65,5   96,6   0,02   1,11   50           190
09-16  84,0    65,5   96,6   0,02   1,11   50           238
09-17  82,9    65,3   96,6   0,02   1,12   50           279
09-18  81,9    65,9   96,6   0,02   1,12   50           316
=====  ======  =====  =====  =====  =====  ===========  ========

Cambian ``placsp`` (93,1 → 81,9: el límite estaba topado en 100 y no podía
saltar), ``ted`` (65,6 → 65,9, el máximo de la semana), la UTE (8 → 0,02) y
el delta de baja (5 → 1,12). Los dos últimos eran holgura de primer mes, no
calidad medida. ``pscp`` y las fechas imposibles no se mueven.

``sin_tipo`` es el umbral de ``importe_tipo`` (cero, sin margen): la serie dice
que **se viola todos los días y crece** (131 → 316). No se recalibra —un cero
que es una corrección no se relaja para silenciar el correo—: es un camino de
escritura que no puebla ``importe_tipo``, anotado como P2 propio en el backlog
el mismo día.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from typing import Any, Literal

from db import domain_truth_audit as auditoria
from db.repositories.ml_dataset import distribucion_ml_proba
from observability.logging import get_logger

log = get_logger(__name__)

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
    # 2026-09-18: bajando cada día (89,8 → 81,9 en la semana) a medida que el
    # feed reingiere expedientes con el parser arreglado. Se recalibra al
    # último valor, no al máximo: con 93,1 el límite estaba topado en 100 y no
    # podía saltar nunca.
    "placsp": Umbral(
        "fecha_limite/placsp",
        81.9,
        "2026-09-18",
        "%",
        "El fix de Ola 1 extrae el campo, pero el histórico ingerido antes sigue sin él.",
        tope=100.0,
    ),
    # 2026-09-18: entre 65,2 y 65,9 en la semana; se toma el máximo.
    "ted": Umbral(
        "fecha_limite/ted",
        65.9,
        "2026-09-18",
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

#: Recalibrado el 2026-09-18 sobre las siete ejecuciones archivadas de
#: `domain-truth.yml` (12→18/09): 0,02 % las siete (109 filas de ~695k). El 8 %
#: del 2026-07-26 era holgura de primer mes —400 veces el valor real— y no
#: habría saltado ni con el defecto multiplicado por cien. El JSON redondea a
#: dos decimales, así que con el límite en 0,022 la alerta salta al leer 0,03:
#: en la práctica, cuando las filas afectadas suben ~50 %.
UMBRAL_UTE = Umbral(
    "ute/pct_filas_afectadas",
    0.02,
    "2026-09-18",
    "%",
    "Defecto de modelado conocido y acumulado: detecta que crezca de golpe, no que exista.",
    tope=100.0,
)

#: Recalibrado el 2026-09-18 con la misma serie: 1,10 / 1,10 / 1,10 / 1,11 /
#: 1,11 / 1,12 / 1,12 puntos. Se toma el máximo de la semana (1,12) y el margen
#: por defecto: límite 1,23. El 5,0 anterior era cuatro veces el valor real.
UMBRAL_DELTA_BAJA = Umbral(
    "baja/delta_puntos",
    1.12,
    "2026-09-18",
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
#: importe: el día en que se aplicó `v113`. Las anteriores están en
#: `desconocido` por construcción.
IMPORTE_TIPO_DESDE = "2026-09-06"

#: Filas nuevas con importe y sin base declarada. Umbral 0 y margen 0: a partir
#: de `v113` todo camino de escritura pasa por un parser que sabe de dónde viene
#: el número. Una sola fila sin tipo significa que hay un camino que no lo
#: puebla, y eso no admite tolerancia.
UMBRAL_IMPORTE_SIN_TIPO = Umbral(
    "importe/filas_nuevas_sin_tipo",
    0,
    "2026-09-06",
    "filas",
    "Desde v113 el parser declara la base del importe; una fila nueva sin tipo es un "
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

# Umbral de "alta probabilidad" del clasificador SAP y proporción máxima de
# filas puntuadas que puede superarlo. El 2026-09-04 el modelo de mayo daba
# 90,64% del corpus por encima de su umbral servido: sobre una población que
# nunca vio (683k filas de PSCP). El criterio de aceptación de S6.1 es que esa
# proporción baje de la mitad, así que el umbral ES la mitad — no un valor
# holgado como los de arriba, porque aquí no se vigila un empeoramiento sino
# que se comprueba una corrección.
UMBRAL_ML_PROBA_ALTA = 0.7
MAX_PCT_ML_PROBA_ALTA = 50.0

# Fechas no ISO toleradas: CERO, y no por severidad gratuita. Las escrituras
# nuevas ya no pueden producirlas en las seis columnas con CHECK (``v59``), así
# que cualquier cuenta > 0 es histórico anterior al cutover — un conjunto que
# solo puede encoger. Es el mismo criterio del resto de ratchets del repo: no
# se vigila un empeoramiento, se comprueba una corrección. Mientras no sea
# cero, T2 no puede convertir estas columnas a `timestamptz` sin perder filas.
MAX_FECHAS_NO_ISO = 0


# ── Medición ─────────────────────────────────────────────────────────────────


def _medir_fecha_limite() -> dict[str, Any]:
    return {"por_fuente": auditoria.fecha_limite_gap_by_source()}


def _medir_ute() -> dict[str, Any]:
    return auditoria.ute_candidate_stats()


def _medir_baja() -> dict[str, Any]:
    stats = auditoria.baja_media_delta()
    por_adj = stats["baja_media_pct_por_adjudicacion"]
    por_lic = stats["baja_media_pct_por_licitacion"]
    stats["delta_puntos"] = (
        round(float(por_adj) - float(por_lic), 2)
        if por_adj is not None and por_lic is not None
        else None
    )
    return stats


def _medir_ml_proba() -> dict[str, Any]:
    return distribucion_ml_proba(UMBRAL_ML_PROBA_ALTA)


def _medir_importe_sin_tipo() -> dict[str, Any]:
    """Filas nuevas cuyo importe no declara su base (C1.1)."""
    return auditoria.importe_sin_base_declarada(desde=IMPORTE_TIPO_DESDE)


def _medir_fechas_imposibles() -> dict[str, Any]:
    """Adjudicaciones con fecha anterior al año plausible (C4.4)."""
    return auditoria.adjudicaciones_con_fecha_imposible()


def _medir_fechas_iso() -> dict[str, Any]:
    return auditoria.fechas_no_iso()


#: Secciones que se miden contra la BD, en el orden del informe. La (b),
#: multi-lote, no está: lee ZIP en disco con el parser de ``scraper/`` y la
#: añade ``scripts/audit_domain_truth.py``.
SECCIONES_BD: tuple[tuple[str, Callable[[], dict[str, Any]]], ...] = (
    ("fecha_limite", _medir_fecha_limite),
    ("ute", _medir_ute),
    ("baja", _medir_baja),
    ("ml_proba", _medir_ml_proba),
    ("fechas_imposibles", _medir_fechas_imposibles),
    ("importe_tipo", _medir_importe_sin_tipo),
    ("fechas_iso", _medir_fechas_iso),
)


def medir_bd() -> dict[str, Any]:
    """Mide las secciones de BD aislando el fallo de cada una.

    Una sección que revienta deja ``{"error": ...}`` en su hueco y no impide
    medir el resto: la auditoría es más útil parcial que ausente.
    """
    secciones: dict[str, Any] = {}
    for clave, fn in SECCIONES_BD:
        try:
            secciones[clave] = fn()
        except Exception as exc:
            log.warning("verdad_dominio_seccion_fallida", seccion=clave, exc_info=True)
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
            f"Hay un camino de escritura que no pasa por el parser de v113."
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

    ml = datos.get("ml_proba", {})
    # Se evalúa sobre las filas PUNTUADAS y no sobre el corpus entero: es lo
    # que describe al clasificador. Con la mitad del corpus sin score (lo
    # normal desde que la población está acotada), el porcentaje sobre el total
    # bajaría solo por dejar de puntuar, que no es la mejora que se busca.
    pct_alta = ml.get("pct_puntuadas_por_encima")
    if pct_alta is not None and float(pct_alta) > MAX_PCT_ML_PROBA_ALTA:
        violaciones.append(
            f"ml_proba: {pct_alta}% de las filas puntuadas supera "
            f"{ml.get('umbral')} ({ml.get('por_encima')}/{ml.get('puntuadas')}), "
            f"umbral {MAX_PCT_ML_PROBA_ALTA}% — el clasificador no discrimina"
        )
    fuera = ml.get("fuera_poblacion", {})
    if int(fuera.get("puntuadas") or 0) > 0:
        violaciones.append(
            f"ml_proba: {fuera['puntuadas']} filas fuera de la población del "
            "clasificador conservan un score; deberían haberse limpiado en "
            "precompute_ml_proba"
        )

    fechas = datos.get("fechas_iso", {})
    total_no_iso = int(fechas.get("total_no_iso") or 0)
    if total_no_iso > MAX_FECHAS_NO_ISO:
        peores = ", ".join(
            f"{f['tabla']}.{f['columna']}={f['no_iso']}"
            for f in sorted(
                (f for f in fechas.get("por_columna", []) if f["no_iso"]),
                key=lambda f: int(f["no_iso"]),
                reverse=True,
            )[:3]
        )
        violaciones.append(
            f"fechas_iso: {total_no_iso} fechas de texto no empiezan por ISO-8601 "
            f"({peores}), umbral {MAX_FECHAS_NO_ISO} — bloquean el VALIDATE "
            "CONSTRAINT de v59 y la conversión a timestamptz de T2"
        )

    for clave, seccion in datos.items():
        if isinstance(seccion, dict) and "error" in seccion:
            violaciones.append(f"sección '{clave}' no pudo medirse: {seccion['error']}")

    return violaciones


# ── Resumen tipado para la consola ───────────────────────────────────────────

EstadoSeccion = Literal["ok", "violacion", "error", "sin_datos"]


@dataclass(frozen=True, slots=True)
class MetricaVerdad:
    """Un número de una sección, con el límite contra el que se compara."""

    etiqueta: str
    valor: float | None
    unidad: str
    #: ``None`` cuando el número se informa pero no se evalúa (una fuente con
    #: menos de :data:`MIN_LICITACIONES_PARA_EVALUAR` licitaciones).
    limite: float | None = None
    supera: bool = False
    detalle: str | None = None


@dataclass(frozen=True, slots=True)
class SeccionVerdad:
    """Una sección de la auditoría, lista para pintar."""

    clave: str
    titulo: str
    metricas: tuple[MetricaVerdad, ...] = ()
    error: str | None = None

    @property
    def estado(self) -> EstadoSeccion:
        if self.error is not None:
            return "error"
        if any(m.supera for m in self.metricas):
            return "violacion"
        if not self.metricas:
            return "sin_datos"
        return "ok"


TITULOS: dict[str, str] = {
    "fecha_limite": "Licitaciones sin plazo de presentación, por fuente",
    "ute": "Adjudicaciones con pinta de UTE contada varias veces",
    "baja": "Baja media: por adjudicación frente a por licitación",
    "ml_proba": "Discriminación del clasificador SAP",
    "fechas_imposibles": "Adjudicaciones con fecha anterior a 1990",
    "importe_tipo": "Importes nuevos sin base declarada",
    "fechas_iso": "Fechas de texto que no son ISO-8601",
}


def _num(valor: Any) -> float | None:
    """``float`` o ``None``: los agregados de ``db/`` llegan como Decimal, int o NULL."""
    if valor is None:
        return None
    try:
        return float(valor)
    except (TypeError, ValueError):
        return None


def _metricas_fecha_limite(seccion: dict[str, Any]) -> list[MetricaVerdad]:
    metricas: list[MetricaVerdad] = []
    for fila in seccion.get("por_fuente", []):
        fuente = str(fila.get("fuente") or "")
        total = int(fila.get("total") or 0)
        pct = float(fila.get("pct_sin_fecha_limite") or 0.0)
        detalle = f"{int(fila.get('sin_fecha_limite') or 0)} de {total}"
        if total < MIN_LICITACIONES_PARA_EVALUAR:
            # Mismo criterio que `evaluar`: con poco volumen se informa sin límite.
            metricas.append(MetricaVerdad(fuente, pct, "%", detalle=detalle))
            continue
        umbral = UMBRALES_FECHA_LIMITE.get(fuente, UMBRAL_FECHA_LIMITE_POR_DEFECTO)
        metricas.append(MetricaVerdad(fuente, pct, "%", umbral.limite, umbral.supera(pct), detalle))
    return metricas


def _metricas_ute(seccion: dict[str, Any]) -> list[MetricaVerdad]:
    pct = float(seccion.get("pct_filas_afectadas") or 0.0)
    detalle = f"{seccion.get('filas_afectadas', 0)} de {seccion.get('total_filas', 0)} filas"
    return [
        MetricaVerdad(
            "Filas afectadas", pct, "%", UMBRAL_UTE.limite, UMBRAL_UTE.supera(pct), detalle
        )
    ]


def _metricas_baja(seccion: dict[str, Any]) -> list[MetricaVerdad]:
    delta = _num(seccion.get("delta_puntos"))
    detalle = (
        f"por adjudicación {seccion.get('baja_media_pct_por_adjudicacion')} · "
        f"por licitación {seccion.get('baja_media_pct_por_licitacion')}"
    )
    supera = delta is not None and UMBRAL_DELTA_BAJA.supera(abs(delta))
    return [MetricaVerdad("Diferencia", delta, "puntos", UMBRAL_DELTA_BAJA.limite, supera, detalle)]


def _metricas_ml_proba(seccion: dict[str, Any]) -> list[MetricaVerdad]:
    pct = _num(seccion.get("pct_puntuadas_por_encima"))
    fuera = int((seccion.get("fuera_poblacion") or {}).get("puntuadas") or 0)
    return [
        MetricaVerdad(
            f"Puntuadas por encima de {seccion.get('umbral', UMBRAL_ML_PROBA_ALTA)}",
            pct,
            "%",
            MAX_PCT_ML_PROBA_ALTA,
            pct is not None and pct > MAX_PCT_ML_PROBA_ALTA,
            f"{seccion.get('por_encima', 0)} de {seccion.get('puntuadas', 0)} puntuadas",
        ),
        MetricaVerdad("Fuera de población con score", float(fuera), "filas", 0.0, fuera > 0),
    ]


def _conteo(
    numero: float | None, etiqueta: str, umbral_limite: float, detalle: str | None = None
) -> list[MetricaVerdad]:
    """Una métrica de filas que salta en cuanto pasa de su límite. Sin dato, ninguna."""
    if numero is None:
        return []
    return [
        MetricaVerdad(etiqueta, numero, "filas", umbral_limite, numero > umbral_limite, detalle)
    ]


def _metricas(clave: str, seccion: dict[str, Any]) -> list[MetricaVerdad]:
    """Traduce una sección cruda a métricas con el mismo criterio que :func:`evaluar`."""
    if clave == "fecha_limite":
        return _metricas_fecha_limite(seccion)
    if clave == "ute":
        return _metricas_ute(seccion)
    if clave == "baja":
        return _metricas_baja(seccion)
    if clave == "ml_proba":
        return _metricas_ml_proba(seccion)
    if clave == "fechas_imposibles":
        return _conteo(
            _num(seccion.get("antes_de_1990")),
            "Anteriores a 1990",
            UMBRAL_FECHAS_IMPOSIBLES.limite,
        )
    if clave == "importe_tipo":
        return _conteo(
            _num(seccion.get("sin_tipo")),
            "Sin base declarada",
            UMBRAL_IMPORTE_SIN_TIPO.limite,
            f"ingeridas desde {seccion.get('desde', IMPORTE_TIPO_DESDE)}",
        )
    if clave == "fechas_iso":
        return _conteo(
            float(int(seccion.get("total_no_iso") or 0)),
            "Fechas no ISO",
            float(MAX_FECHAS_NO_ISO),
        )
    return []


def resumir(datos: dict[str, Any]) -> list[SeccionVerdad]:
    """Las secciones medidas, como métricas con su límite y su estado.

    Es la vista para personas de lo que :func:`evaluar` decide para el correo:
    los dos aplican los mismos umbrales, y una sección está en ``violacion``
    exactamente cuando alguna de sus métricas supera el suyo. Las secciones que
    no tienen título aquí (la (b) del script) no se resumen.
    """
    secciones: list[SeccionVerdad] = []
    for clave, seccion in datos.items():
        if clave not in TITULOS or not isinstance(seccion, dict):
            continue
        titulo = TITULOS[clave]
        if "error" in seccion:
            secciones.append(SeccionVerdad(clave, titulo, error=str(seccion["error"])))
            continue
        secciones.append(SeccionVerdad(clave, titulo, tuple(_metricas(clave, seccion))))
    return secciones
