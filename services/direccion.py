"""F4.2 (cuadro de mando) y F4.5 (actividad del equipo).

La carga del equipo —quién tiene qué abierto hoy— vive en
``services/carga_equipo.py``, con el mismo permiso que este cuadro.

El Embudo son tres barras y cuatro cifras en 128 líneas. Con eso, un owner no
puede responder ninguna de las preguntas que se hace: dónde ganamos, dónde
perdemos y por qué, cuánto tarda el ciclo, si vamos mejor o peor que antes y
si el equipo está trabajando lo que dijimos que íbamos a trabajar.

Cada tarjeta declara de qué está hecha
--------------------------------------
Universo, ventana y ``n``, siempre (ADR-014). Y **ninguna se pinta por debajo
del mínimo de su métrica**: la regla no es «avisar de que hay pocos casos»,
es no publicar el número. Un win rate del 100 % sobre dos cierres, en la
pantalla que mira dirección, es peor que un hueco — el hueco se pregunta, el
número se cree.

La ventana es de cierres, no de altas
-------------------------------------
Rendimiento (Oportunidades) recorta por ``identified_at``: es una cohorte, y
responde «cómo va lo que entró en el periodo». Dirección responde «qué
resultados tuvimos en el periodo», y eso se cuenta por **fecha de cierre**,
igual que el informe semanal (``services/informes.py``). Una oportunidad que
entró hace dos años y se ganó ayer es un resultado de este trimestre.

Con ventana, cada cifra viaja con la del **mismo periodo de hace un año**
(``ventana_anterior``) y la diferencia ya calculada: «vamos mejor o peor» es
la pregunta de esta pantalla, y la resta es analítica (ADR-014), así que no la
hace la UI. Hace un año y no «los N días anteriores»: con «Este año» los días
anteriores serían el final del año pasado, y comparar enero-octubre con
marzo-diciembre mezcla estacionalidad con resultado.

Lo que **no** depende de la ventana es la foto del pipeline abierto (valor
ponderado, previsión por trimestre, presentadas sin resultado): es un stock de
hoy, y la tarjeta lo dice (``depende_del_periodo=False``).

Permisos
--------
Solo owner y admin, y el control está **en el servicio**, no en el rail: un
`member` que teclee la URL recibe 403, no una pantalla sin enlace. Un rail sin
enlace es una sugerencia; esto es un permiso.
"""

from __future__ import annotations

import json
import math
from collections.abc import Callable, Iterator, Mapping, Sequence
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import UTC, date, datetime, timedelta
from itertools import pairwise
from statistics import median
from typing import Any, Literal, get_args

from pydantic import BaseModel, ConfigDict, Field

from db.repositories.organizations import OrganizationRepository
from db.repositories.pursuits import PursuitRepository
from observability.logging import get_logger
from services.organizations import (
    OrganizationPermissionError,
    alcance_resuelto,
)
from services.pursuits import (
    MINIMO_PERDIDAS_POR_MOTIVO,
    SIN_CODIFICAR,
    PursuitValidationError,
    _parse_iso_datetime,
    _perdidas_por_motivo,
    _valor_ponderado,
    calcular_radar_quality,
)
from shared.dates import a_fecha
from shared.dto import OrganizationSettings, PerdidaPorMotivo, RadarQuality
from shared.procedimientos import etiqueta_procedimiento

log = get_logger(__name__)

__all__ = [
    "MINIMO_CICLO",
    "MINIMO_POR_CORTE",
    "ROLES_DIRECCION",
    "CorteDireccion",
    "CuadroDireccion",
    "TarjetaMetrica",
    "Ventana",
    "construir_cuadro",
    "corte_con_minimo",
    "cuadro_de_direccion",
    "intervalo_wilson",
    "tarjetas_de_direccion",
    "ventana_anterior",
]

#: Roles que pueden abrir Dirección.
ROLES_DIRECCION: frozenset[str] = frozenset({"owner", "admin"})

#: Cierres mínimos por celda de un corte (win rate por tecnología, por órgano).
#: Cinco, el mismo que F3.1 usa para los motivos de pérdida: es la misma
#: pregunta —«¿cuántos casos hacen falta para que esto signifique algo?»— y
#: dos umbrales distintos en la misma pantalla serían dos productos.
MINIMO_POR_CORTE = 5

#: Cierres mínimos para publicar el tiempo de ciclo y la tasa de éxito global.
#: El mismo cinco, por el mismo motivo: con dos cierres, la mediana es la
#: duración de uno de ellos.
MINIMO_CICLO = MINIMO_POR_CORTE

#: z del intervalo de confianza de los cortes: 95 %. El umbral de cinco dice
#: «hay base»; el intervalo dice **cuánta**. Con cinco cierres, un 60 % es
#: compatible con cualquier cosa entre un 23 % y un 88 %, y una diferencia de
#: veinte puntos entre dos tecnologías puede no ser ninguna.
Z_INTERVALO = 1.96

#: Cuántas oportunidades se listan para registrar su resultado o su motivo.
#: Es una lista de trabajo, no un informe: con ocho se ve el patrón y se
#: empieza; el recuento completo viaja aparte.
MUESTRA_PENDIENTES = 8

#: Unidad de la cifra de una tarjeta. Viaja en el contrato para que la
#: pantalla no tenga que deducir de la ``clave`` si formatea euros o días.
UnidadTarjeta = Literal["eur", "dias", "pct"]

#: Cortes del cuadro, en el orden en que se leen.
ClaveCorte = Literal["tecnologia", "tramo_importe", "procedimiento", "organo"]

#: Dónde queda una celda frente a la tasa de la organización.
PosicionCorte = Literal["por_encima", "en_linea", "por_debajo"]


# ── Ventana ─────────────────────────────────────────────────────────────────


@dataclass(frozen=True)
class Ventana:
    """Intervalo semiabierto ``[desde, hasta)``; un extremo ``None`` no acota.

    Sin ningún extremo es el histórico completo, y entonces un cierre sin
    fecha sí cuenta: estaba cerrado, sólo que no se sabe cuándo. Con ventana
    no se puede colocar, y queda fuera.
    """

    desde: datetime | None = None
    hasta: datetime | None = None

    @property
    def acotada(self) -> bool:
        return self.desde is not None or self.hasta is not None

    def contiene(self, momento: datetime | None) -> bool:
        if momento is None:
            return not self.acotada
        if self.desde is not None and momento < self.desde:
            return False
        return not (self.hasta is not None and momento >= self.hasta)


def _un_anio_antes(momento: datetime) -> datetime:
    """El mismo instante un año antes; el 29 de febrero cae en el 28."""
    try:
        return momento.replace(year=momento.year - 1)
    except ValueError:
        return momento.replace(year=momento.year - 1, day=28)


def ventana_anterior(ventana: Ventana, ahora: datetime) -> Ventana | None:
    """La ventana con la que se compara: el mismo periodo, un año antes.

    Sin inicio no hay periodo anterior —el histórico no tiene uno—. Una
    ventana de más de un año se compara con la inmediatamente anterior de la
    misma duración: desplazarla un año la haría solaparse consigo misma.
    """
    if ventana.desde is None:
        return None
    hasta = ventana.hasta or ahora
    try:
        if hasta - ventana.desde <= timedelta(days=366):
            return Ventana(_un_anio_antes(ventana.desde), _un_anio_antes(hasta))
        duracion = hasta - ventana.desde
        return Ventana(ventana.desde - duracion, ventana.desde)
    except (OverflowError, ValueError):
        # Una ventana que empieza en el año 1 no tiene año anterior: se
        # publica sin comparación en vez de reventar.
        return None


def _fecha_corta(momento: datetime) -> str:
    return momento.astimezone(UTC).strftime("%d/%m/%Y")


def _frase_ventana(ventana: Ventana) -> str:
    """La ventana en una frase, para el universo de cada tarjeta."""
    if ventana.desde is not None and ventana.hasta is not None:
        return f"Cerradas del {_fecha_corta(ventana.desde)} al {_fecha_corta(ventana.hasta)}."
    if ventana.desde is not None:
        return f"Cerradas desde el {_fecha_corta(ventana.desde)}."
    if ventana.hasta is not None:
        return f"Cerradas antes del {_fecha_corta(ventana.hasta)}."
    return "Ventana: todo el histórico de la organización."


def _cerradas(filas: Sequence[Mapping[str, Any]], ventana: Ventana) -> list[Mapping[str, Any]]:
    """Ganadas y perdidas con el cierre dentro de la ventana.

    Las retiradas (``cancelled``) no son un resultado: no dicen quién habría
    ganado, y en una tasa de éxito bajarían el denominador sin motivo.
    """
    return [
        fila
        for fila in filas
        if fila.get("outcome") in ("won", "lost")
        and ventana.contiene(_parse_iso_datetime(fila.get("closed_at")))
    ]


# ── Contrato ────────────────────────────────────────────────────────────────


class TarjetaMetrica(BaseModel):
    """Una cifra con todo lo que hace falta para creerla."""

    model_config = ConfigDict(extra="forbid")

    clave: str
    etiqueta: str
    #: `None` = no se publica por debajo del mínimo. La UI enseña el hueco y
    #: `nota` dice por qué; nunca un 0 ni un «—» sin explicación.
    valor: float | None = None
    #: `eur` (importe), `dias` o `pct` (fracción 0-1).
    unidad: UnidadTarjeta
    #: Mínimo de `n` para publicar `valor`.
    n_minimo: int = Field(default=1, ge=1)
    #: Cifras sobre las que se calculó.
    n: int = Field(default=0, ge=0)
    #: Universo y ventana, en una frase.
    universo: str
    #: Por qué no hay valor, cuando no lo hay.
    nota: str | None = None
    #: `False` en las fotos de hoy (el pipeline abierto): no cambian con la
    #: ventana y no tienen periodo anterior con el que compararse.
    depende_del_periodo: bool = True
    #: Hacia dónde es mejor: un ciclo más corto es mejor, un importe más alto
    #: también. Viaja aquí para que la UI no lo deduzca de la `clave`.
    mejor_si: Literal["sube", "baja"] = "sube"
    #: El valor del periodo anterior, con el mismo mínimo. `None` sin
    #: comparación o sin base en el periodo anterior (`n_anterior` lo dice).
    anterior: float | None = None
    #: `n` del periodo anterior. `None` = no hay comparación (sin ventana).
    n_anterior: int | None = Field(default=None, ge=0)
    #: `valor - anterior`, en la unidad de la tarjeta (en `pct`, en fracción:
    #: 0,05 son cinco puntos). Sólo cuando las dos cifras están publicadas.
    delta: float | None = None


class CorteMetrica(BaseModel):
    """Una fila de un corte (por tecnología, por órgano…)."""

    model_config = ConfigDict(extra="forbid")

    clave: str
    #: Etiqueta legible cuando la clave es un código (tramo de importe).
    etiqueta: str | None = None
    valor: float | None = None
    n: int = Field(ge=0)
    #: Intervalo de Wilson al 95 % de `valor`. Sólo con valor publicado.
    intervalo_bajo: float | None = Field(default=None, ge=0, le=1)
    intervalo_alto: float | None = Field(default=None, ge=0, le=1)
    #: Frente a la tasa de la organización en la misma ventana: arriba o abajo
    #: sólo cuando el intervalo **entero** queda a un lado. Si la media cae
    #: dentro, la diferencia no se distingue del azar y se dice `en_linea`.
    posicion: PosicionCorte | None = None


class CorteDireccion(BaseModel):
    """Un corte entero: las filas con base y, aparte, las que no la tienen."""

    model_config = ConfigDict(extra="forbid")

    clave: ClaveCorte
    titulo: str
    #: Filas con base (≥ `n_minimo` cierres), en el orden de lectura del corte.
    filas: list[CorteMetrica] = Field(default_factory=list)
    #: Filas por debajo del mínimo. Se listan aparte en vez de omitirse: que
    #: haya un órgano con tres cierres es información —dice dónde el equipo
    #: está empezando—, pero no es una tasa.
    filas_sin_base: list[CorteMetrica] = Field(default_factory=list)
    #: Cierres que suman las filas sin base.
    cierres_sin_base: int = Field(default=0, ge=0)
    #: Tasa de éxito de la organización en la ventana: la línea de referencia.
    #: `None` por debajo del mínimo global.
    media: float | None = Field(default=None, ge=0, le=1)


class OportunidadPendiente(BaseModel):
    """Una oportunidad a la que le falta un dato que sólo el equipo puede poner."""

    model_config = ConfigDict(extra="forbid")

    pursuit_id: int = Field(ge=1)
    licitacion_id: str
    titulo: str | None = None
    #: Desde cuándo está así (presentada o cerrada), `YYYY-MM-DD`.
    desde: str | None = None
    #: Días desde `desde` hasta hoy.
    dias: int | None = Field(default=None, ge=0)


class CuadroDireccion(BaseModel):
    """Lo que ve owner o admin en Dirección."""

    model_config = ConfigDict(extra="forbid")

    organization_id: int = Field(ge=1)
    #: La ventana de cierres de la que hablan las tarjetas y los cortes.
    periodo_desde: datetime | None = None
    periodo_hasta: datetime | None = None
    #: La ventana con la que se compara. `None` sin ventana (histórico).
    anterior_desde: datetime | None = None
    anterior_hasta: datetime | None = None
    tarjetas: list[TarjetaMetrica] = Field(default_factory=list)
    #: Ganadas + perdidas en la ventana y en todo el histórico. Con menos de
    #: `n_minimo` en el histórico la pantalla no tiene nada que publicar y lo
    #: dice una vez, en vez de pintar un hueco por panel.
    cierres: int = Field(default=0, ge=0)
    cierres_historico: int = Field(default=0, ge=0)
    cortes: list[CorteDireccion] = Field(default_factory=list)
    #: **Obsoletos: usar `cortes`.** Los dos cortes que había antes de `cortes`,
    #: con la misma forma de siempre (lista con el mínimo aplicado dentro) y ya
    #: acotados a la ventana. Quitarlos de la respuesta sería un cambio
    #: incompatible del contrato (`docs/api-design.md`): siguen hasta que una
    #: RFC de retirada los saque con su `api-breaking`.
    win_rate_por_tecnologia: list[CorteMetrica] = Field(
        default_factory=list, json_schema_extra={"deprecated": True}
    )
    win_rate_por_organo: list[CorteMetrica] = Field(
        default_factory=list, json_schema_extra={"deprecated": True}
    )
    #: Mínimo aplicado, declarado en vez de repetido en la UI.
    n_minimo: int = MINIMO_POR_CORTE
    #: Reparto de las pérdidas por motivo codificado (D37). Vacío por debajo
    #: de `perdidas_n_minimo`: el mínimo lo aplica el servicio, no la pantalla.
    perdidas_por_motivo: list[PerdidaPorMotivo] = Field(default_factory=list)
    perdidas_n_minimo: int = MINIMO_PERDIDAS_POR_MOTIVO
    #: Pérdidas en la ventana y cuántas no tienen motivo de la lista cerrada:
    #: es lo que dice cuánto se puede creer el reparto.
    perdidas: int = Field(default=0, ge=0)
    perdidas_sin_motivo: int = Field(default=0, ge=0)
    perdidas_sin_motivo_muestra: list[OportunidadPendiente] = Field(default_factory=list)
    #: Presentadas hoy sin resultado registrado. Foto de hoy, sin ventana: es
    #: lo que hay que registrar para que esta pantalla tenga base.
    pendientes_resultado: int = Field(default=0, ge=0)
    pendientes_resultado_muestra: list[OportunidadPendiente] = Field(default_factory=list)
    #: Precisión del Radar por banda de entrada, sobre las oportunidades
    #: **abiertas** en la ventana (cohorte, como en Rendimiento). `None` cuando
    #: ninguna lleva banda sellada: no se midió, no «acierta el 0 %».
    radar_quality: RadarQuality | None = None
    #: ¿La precisión baja de banda en banda? `True` si, entre las bandas con
    #: base, ninguna supera a la que tiene por encima. `None` con menos de dos
    #: bandas con base: con una sola no hay escalera que mirar.
    radar_ordena_bien: bool | None = None
    #: Probabilidad por etapa con la que se ponderó el pipeline: son supuestos,
    #: y sin ellos la cifra no es reproducible (ADR-014).
    probabilidades_etapa_usadas: dict[str, int] = Field(default_factory=dict)
    #: Valor ponderado repartido por trimestre de adjudicación prevista,
    #: `{"2026-Q4": 340000.0}`. Es la misma cifra que Rendimiento.
    prevision_trimestral: dict[str, float] = Field(default_factory=dict)
    #: Abiertas sin importe publicado: no entran en el valor ponderado.
    pipeline_sin_importe: int = Field(default=0, ge=0)


@contextmanager
def direccion_resuelta(user_id: int, organization_id: int | None) -> Iterator[int]:
    """Resuelve, comprueba el rol de Dirección y **acota el bloque** (ADR-034).

    Es un context manager y no una función que devuelve el id, y la diferencia
    no es de estilo. La versión anterior hacía ``with alcance_resuelto(...) as
    (resuelta, rol): ... return resuelta``, o sea que soltaba el ámbito **antes**
    de que el llamante consultara nada: Dirección y las dos rutas de T6 seguían
    corriendo sin respaldo RLS aunque el código pareciera acotado. Se midió con
    un espía sobre ``db.connection.current_organization`` y salía vacío.

    Es la trampa de envolver una función que sólo resuelve: el ámbito tiene que
    seguir abierto donde están las consultas, y ésas están en quien llama.

    Lanza :class:`OrganizationPermissionError`, que la ruta convierte en 403 —
    el mismo error que el resto de operaciones restringidas, para que no haya
    dos formas de negar un permiso.
    """
    with alcance_resuelto(user_id, organization_id) as (resuelta, rol):
        if str(rol) not in ROLES_DIRECCION:
            raise OrganizationPermissionError(
                "Dirección es para owner y admin: tu rol en esta organización no lo permite."
            )
        yield resuelta


# ── Cortes ──────────────────────────────────────────────────────────────────


def intervalo_wilson(exitos: int, n: int, *, z: float = Z_INTERVALO) -> tuple[float, float]:
    """Intervalo de Wilson de una proporción: ``(bajo, alto)`` en 0-1.

    Wilson y no el de Wald (``p ± z·√(p(1-p)/n)``): con pocos casos y tasas
    extremas Wald da intervalos de anchura cero —un 5/5 sería «100 % ± 0»— o
    que se salen de 0-1. Wilson se comporta con cinco cierres, que es justo
    el régimen de esta pantalla.
    """
    if n <= 0:
        return 0.0, 1.0
    p = exitos / n
    z2 = z * z
    denominador = 1 + z2 / n
    centro = (p + z2 / (2 * n)) / denominador
    margen = z * math.sqrt(p * (1 - p) / n + z2 / (4 * n * n)) / denominador
    return max(0.0, centro - margen), min(1.0, centro + margen)


def _clave_columna(columna: str) -> Callable[[Mapping[str, Any]], str]:
    def _clave(fila: Mapping[str, Any]) -> str:
        return str(fila.get(columna) or "").strip() or "sin clasificar"

    return _clave


def corte_con_minimo(
    filas: Sequence[Mapping[str, Any]],
    *,
    clave: str | Callable[[Mapping[str, Any]], str],
    ganadas: str = "won",
    perdidas: str = "lost",
    minimo: int = MINIMO_POR_CORTE,
    orden: Sequence[str] | None = None,
) -> list[CorteMetrica]:
    """Win rate por ``clave``, con el mínimo aplicado **dentro**.

    ``clave`` es una columna de la fila o una función que la clasifica (el
    tramo de importe no es una columna, es un rango sobre una).

    El corte se devuelve con ``valor=None`` en las celdas por debajo del
    mínimo, en vez de omitirlas. Omitirlas escondería que existe un órgano con
    tres cierres, que es información: dice dónde el equipo está empezando.

    Se aplica aquí y no en la pantalla porque el mismo corte lo consumen el
    cuadro de mando, el informe semanal y el PDF, y un mínimo repartido entre
    tres consumidores es un mínimo que uno de los tres se salta.
    """
    clasificar = _clave_columna(clave) if isinstance(clave, str) else clave
    agregados: dict[str, dict[str, int]] = {}
    for fila in filas:
        resultado = str(fila.get("outcome") or "")
        if resultado not in (ganadas, perdidas):
            continue
        celda = agregados.setdefault(clasificar(fila), {"won": 0, "total": 0})
        celda["total"] += 1
        if resultado == ganadas:
            celda["won"] += 1

    cortes: list[CorteMetrica] = []
    for etiqueta, datos in agregados.items():
        total, won = datos["total"], datos["won"]
        if total >= minimo:
            bajo, alto = intervalo_wilson(won, total)
            cortes.append(
                CorteMetrica(
                    clave=etiqueta,
                    n=total,
                    valor=won / total,
                    intervalo_bajo=bajo,
                    intervalo_alto=alto,
                )
            )
        else:
            cortes.append(CorteMetrica(clave=etiqueta, n=total))
    if orden is not None:
        # Un corte con orden propio (tramos de importe) se lee en ese orden;
        # lo que no esté en él va al final.
        posicion = {clave_orden: i for i, clave_orden in enumerate(orden)}
        cortes.sort(key=lambda c: (posicion.get(c.clave, len(posicion)), c.clave))
    else:
        # Por volumen y, a igualdad, alfabético: dos lecturas seguidas no
        # pueden devolver el corte en distinto orden.
        cortes.sort(key=lambda c: (-c.n, c.clave))
    return cortes


#: Tramos de importe de la licitación: ``(clave, etiqueta, techo)``. El techo
#: es exclusivo; el último tramo no tiene. Cuatro tramos y no diez: con cinco
#: cierres por celda, una pyme no llena diez.
TRAMOS_IMPORTE: tuple[tuple[str, str, float | None], ...] = (
    ("hasta_100k", "Menos de 100.000 €", 100_000.0),
    ("100k_500k", "De 100.000 a 500.000 €", 500_000.0),
    ("500k_1m", "De 500.000 € a 1 M€", 1_000_000.0),
    ("desde_1m", "1 M€ o más", None),
)
TRAMO_SIN_IMPORTE = ("sin_importe", "Sin importe publicado")
_ETIQUETA_TRAMO = {clave: etiqueta for clave, etiqueta, _ in TRAMOS_IMPORTE} | {
    TRAMO_SIN_IMPORTE[0]: TRAMO_SIN_IMPORTE[1]
}


def tramo_importe(fila: Mapping[str, Any]) -> str:
    """Clave del tramo del importe de licitación de la fila."""
    importe = fila.get("tender_importe")
    if importe is None:
        return TRAMO_SIN_IMPORTE[0]
    valor = float(importe)
    for clave, _etiqueta, techo in TRAMOS_IMPORTE:
        if techo is None or valor < techo:
            return clave
    return TRAMOS_IMPORTE[-1][0]  # pragma: no cover - el último tramo no tiene techo


def _procedimiento(fila: Mapping[str, Any]) -> str:
    """Procedimiento por su etiqueta: la fuente publica ``01`` y ``1`` para el mismo."""
    codigo = str(fila.get("tender_procedimiento") or "").strip()
    return etiqueta_procedimiento(codigo, vacio="sin clasificar") if codigo else "sin clasificar"


def _posicion(celda: CorteMetrica, media: float | None) -> PosicionCorte | None:
    if media is None or celda.intervalo_bajo is None or celda.intervalo_alto is None:
        return None
    if celda.intervalo_bajo > media:
        return "por_encima"
    if celda.intervalo_alto < media:
        return "por_debajo"
    return "en_linea"


def corte_direccion(
    filas: Sequence[Mapping[str, Any]],
    *,
    clave: ClaveCorte,
    titulo: str,
    clasificar: str | Callable[[Mapping[str, Any]], str],
    media: float | None,
    etiquetas: Mapping[str, str] | None = None,
    orden: Sequence[str] | None = None,
) -> CorteDireccion:
    """El corte entero tal como lo pinta Dirección: con base, sin base y media."""
    celdas = corte_con_minimo(filas, clave=clasificar, orden=orden)
    con_base: list[CorteMetrica] = []
    sin_base: list[CorteMetrica] = []
    for celda in celdas:
        etiqueta = etiquetas.get(celda.clave) if etiquetas else None
        celda = celda.model_copy(update={"etiqueta": etiqueta, "posicion": _posicion(celda, media)})
        (con_base if celda.valor is not None else sin_base).append(celda)
    return CorteDireccion(
        clave=clave,
        titulo=titulo,
        filas=con_base,
        filas_sin_base=sin_base,
        cierres_sin_base=sum(c.n for c in sin_base),
        media=media,
    )


def cortes_de_direccion(
    cerradas: Sequence[Mapping[str, Any]], media: float | None
) -> list[CorteDireccion]:
    """Los cuatro cortes, en el orden en que se leen: qué, cuánto, cómo, quién."""
    return [
        corte_direccion(
            cerradas,
            clave="tecnologia",
            titulo="Tecnología",
            clasificar="tender_tecnologia",
            media=media,
        ),
        corte_direccion(
            cerradas,
            clave="tramo_importe",
            titulo="Tramo de importe",
            clasificar=tramo_importe,
            media=media,
            etiquetas=_ETIQUETA_TRAMO,
            orden=[clave for clave, _e, _t in TRAMOS_IMPORTE] + [TRAMO_SIN_IMPORTE[0]],
        ),
        corte_direccion(
            cerradas,
            clave="procedimiento",
            titulo="Procedimiento",
            clasificar=_procedimiento,
            media=media,
        ),
        corte_direccion(
            cerradas,
            clave="organo",
            titulo="Órgano",
            clasificar="tender_organo",
            media=media,
        ),
    ]


# ── F4.2: tarjetas ──────────────────────────────────────────────────────────


def _tarjeta_valor_ponderado(
    filas: Sequence[Mapping[str, Any]],
    valor: float,
    sin_importe: int,
    probabilidades: Mapping[str, int],
) -> TarjetaMetrica:
    """El pipeline abierto en euros, ponderado por etapa.

    Es la misma cifra que Oportunidades → Rendimiento (`pipeline_value_eur`),
    sacada de la misma función: dos pantallas con dos valores del pipeline
    serían dos pipelines. `probabilidades` son las etapas con probabilidad > 0
    que aparecieron, o sea, las abiertas.
    """
    abiertas = sum(1 for fila in filas if str(fila.get("status") or "") in probabilidades)
    con_importe = max(abiertas - sin_importe, 0)
    nota: str | None = None
    if con_importe == 0:
        nota = (
            "Sin base: no hay oportunidades abiertas con importe publicado."
            if abiertas == 0
            else f"Sin base: ninguna de las {abiertas} oportunidades abiertas tiene importe publicado."
        )
    elif sin_importe:
        nota = f"{sin_importe} abierta(s) sin importe publicado no se cuentan, tampoco como cero."
    return TarjetaMetrica(
        clave="valor_ponderado",
        etiqueta="Valor ponderado del pipeline",
        valor=valor if con_importe > 0 else None,
        unidad="eur",
        n=con_importe,
        universo=(
            "Oportunidades abiertas hoy con importe publicado, cada una por la "
            "probabilidad de su etapa según la configuración de la organización. "
            "Foto del pipeline actual: no depende del periodo."
        ),
        nota=nota,
        depende_del_periodo=False,
    )


def _tarjeta_importe(cerradas: Sequence[Mapping[str, Any]], ventana: Ventana) -> TarjetaMetrica:
    """Lo que se ganó, en euros: el importe adjudicado de las ganadas.

    Una ganada sin importe registrado no se cuenta como cero: se cuenta aparte
    y se dice, igual que en el valor ponderado.
    """
    ganadas = [fila for fila in cerradas if fila.get("outcome") == "won"]
    con_importe = [fila for fila in ganadas if fila.get("awarded_amount_eur") is not None]
    sin_importe = len(ganadas) - len(con_importe)
    nota: str | None = None
    if not con_importe:
        nota = (
            "Sin base: ninguna oportunidad ganada en el periodo."
            if not ganadas
            else f"Sin base: ninguna de las {len(ganadas)} ganadas tiene importe registrado."
        )
    elif sin_importe:
        nota = f"{sin_importe} ganada(s) sin importe registrado no se cuentan, tampoco como cero."
    return TarjetaMetrica(
        clave="importe_adjudicado",
        etiqueta="Importe adjudicado",
        valor=(
            round(sum(float(f["awarded_amount_eur"]) for f in con_importe), 2)
            if con_importe
            else None
        ),
        unidad="eur",
        n=len(con_importe),
        universo=f"Oportunidades ganadas, por el importe con el que se adjudicaron. {_frase_ventana(ventana)}",
        nota=nota,
    )


def _tarjeta_tasa(cerradas: Sequence[Mapping[str, Any]], ventana: Ventana) -> TarjetaMetrica:
    """Ganadas sobre ganadas + perdidas. La línea de referencia de los cortes."""
    n = len(cerradas)
    ganadas = sum(1 for fila in cerradas if fila.get("outcome") == "won")
    suficiente = n >= MINIMO_POR_CORTE
    return TarjetaMetrica(
        clave="tasa_exito",
        etiqueta="Tasa de éxito",
        valor=(ganadas / n) if suficiente else None,
        unidad="pct",
        n=n,
        n_minimo=MINIMO_POR_CORTE,
        universo=(
            "Ganadas sobre ganadas más perdidas; las retiradas no cuentan. "
            f"{_frase_ventana(ventana)}"
        ),
        nota=None if suficiente else f"Sin base: {n} cierre(s); hacen falta {MINIMO_POR_CORTE}.",
    )


def _tarjeta_ciclo(
    cerradas: Sequence[Mapping[str, Any]], minimo: int, ventana: Ventana | None = None
) -> TarjetaMetrica:
    """Mediana de días entre identificar la oportunidad y cerrarla.

    Solo ganadas y perdidas: una retirada se cierra cuando alguien se acuerda
    de archivarla, y su fecha mediría la limpieza del tablero, no el ciclo.
    Mediana y no media: una oportunidad que se quedó un año olvidada movería
    la media semanas enteras.
    """
    duraciones: list[int] = []
    for fila in cerradas:
        if fila.get("outcome") not in ("won", "lost"):
            continue
        inicio = a_fecha(fila.get("identified_at"))
        fin = a_fecha(fila.get("closed_at"))
        if inicio is None or fin is None or fin < inicio:
            continue
        duraciones.append((fin - inicio).days)
    n = len(duraciones)
    suficiente = n >= minimo
    return TarjetaMetrica(
        clave="ciclo_dias",
        etiqueta="Ciclo de identificada a cerrada (mediana)",
        valor=float(median(duraciones)) if suficiente else None,
        unidad="dias",
        n=n,
        n_minimo=minimo,
        universo=(
            "Oportunidades ganadas o perdidas con fecha de identificación y de cierre. "
            f"{_frase_ventana(ventana or Ventana())}"
        ),
        nota=None if suficiente else f"Sin base: {n} cierre(s) con fechas; hacen falta {minimo}.",
        mejor_si="baja",
    )


def _comparada(actual: TarjetaMetrica, anterior: TarjetaMetrica | None) -> TarjetaMetrica:
    """La tarjeta con su periodo anterior y la diferencia, si las dos tienen base."""
    if anterior is None or not actual.depende_del_periodo:
        return actual
    delta = (
        actual.valor - anterior.valor
        if actual.valor is not None and anterior.valor is not None
        else None
    )
    return actual.model_copy(
        update={"anterior": anterior.valor, "n_anterior": anterior.n, "delta": delta}
    )


def tarjetas_de_direccion(
    filas: Sequence[Mapping[str, Any]],
    *,
    valor: float,
    sin_importe: int,
    probabilidades: Mapping[str, int],
    ventana: Ventana | None = None,
    anterior: Ventana | None = None,
) -> list[TarjetaMetrica]:
    """Las cuatro tarjetas, en el orden en que se leen: lo ganado, el éxito, lo que viene, el tiempo.

    Función pura sobre las filas de ``metric_rows``: las tarjetas y los cortes
    de la misma respuesta hablan de exactamente el mismo universo. Las
    pérdidas codificadas y la precisión del Radar ya no son tarjetas: la
    primera mide si el equipo rellena el dato, no el negocio, y vive junto al
    reparto que sostiene; la segunda repetía el panel del Radar.
    """
    actual = ventana or Ventana()
    cerradas = _cerradas(filas, actual)
    cerradas_antes = _cerradas(filas, anterior) if anterior is not None else None

    def _par(
        construir: Callable[[Sequence[Mapping[str, Any]], Ventana], TarjetaMetrica],
    ) -> TarjetaMetrica:
        previa = (
            construir(cerradas_antes, anterior)
            if cerradas_antes is not None and anterior is not None
            else None
        )
        return _comparada(construir(cerradas, actual), previa)

    return [
        _par(_tarjeta_importe),
        _par(_tarjeta_tasa),
        _tarjeta_valor_ponderado(filas, valor, sin_importe, probabilidades),
        _par(lambda f, v: _tarjeta_ciclo(f, MINIMO_CICLO, v)),
    ]


# ── Lo que hay que registrar ────────────────────────────────────────────────


def _pendiente(fila: Mapping[str, Any], desde: date | None, hoy: date) -> OportunidadPendiente:
    return OportunidadPendiente(
        pursuit_id=int(fila["pursuit_id"]),
        licitacion_id=str(fila.get("licitacion_id") or ""),
        titulo=(str(fila["titulo"]) if fila.get("titulo") else None),
        desde=desde.isoformat() if desde is not None else None,
        dias=max((hoy - desde).days, 0) if desde is not None else None,
    )


def _pendientes_de_resultado(
    filas: Sequence[Mapping[str, Any]], hoy: date
) -> tuple[int, list[OportunidadPendiente]]:
    """Presentadas sin resultado, de la más antigua a la más reciente.

    Es el cuello de botella de esta pantalla: una oferta presentada hace seis
    meses sin resultado registrado es un cierre que el cuadro no puede contar.
    """
    presentadas = [
        fila
        for fila in filas
        if fila.get("status") == "submitted"
        and fila.get("outcome") in (None, "pending")
        and fila.get("pursuit_id") is not None
    ]
    presentadas.sort(
        key=lambda f: (a_fecha(f.get("submitted_at")) or date.max, int(f["pursuit_id"]))
    )
    muestra = [
        _pendiente(fila, a_fecha(fila.get("submitted_at")), hoy)
        for fila in presentadas[:MUESTRA_PENDIENTES]
    ]
    return len(presentadas), muestra


def _perdidas_sin_motivo(
    cerradas: Sequence[Mapping[str, Any]], hoy: date
) -> tuple[int, int, list[OportunidadPendiente]]:
    """``(perdidas, sin motivo, muestra)`` de las pérdidas de la ventana."""
    perdidas = [fila for fila in cerradas if fila.get("outcome") == "lost"]
    sin_motivo = [
        fila
        for fila in perdidas
        if (str(fila.get("outcome_reason_code") or "").strip() or SIN_CODIFICAR) == SIN_CODIFICAR
    ]
    # Las más recientes primero: son las que alguien todavía recuerda.
    sin_motivo.sort(
        key=lambda f: (a_fecha(f.get("closed_at")) or date.min, int(f.get("pursuit_id") or 0)),
        reverse=True,
    )
    muestra = [
        _pendiente(fila, a_fecha(fila.get("closed_at")), hoy)
        for fila in sin_motivo[:MUESTRA_PENDIENTES]
        if fila.get("pursuit_id") is not None
    ]
    return len(perdidas), len(sin_motivo), muestra


def _radar_ordena_bien(calidad: RadarQuality | None) -> bool | None:
    """Si la precisión baja de banda en banda entre las que tienen base.

    Es la promesa del Radar —lo que pone arriba se gana más— dicha como
    escalera. Con menos de dos bandas con base no hay escalera.
    """
    if calidad is None:
        return None
    precisiones = [b.precision for b in calidad.bandas if b.suficiente and b.precision is not None]
    if len(precisiones) < 2:
        return None
    return all(arriba >= abajo for arriba, abajo in pairwise(precisiones))


def _ajustes(organization_id: int) -> OrganizationSettings:
    """Configuración de la organización, con los defaults de D34 si falla la lectura.

    Fail-open como en `get_metrics`: la cifra sigue siendo correcta y
    declarada (`probabilidades_etapa_usadas`), sólo que sin personalizar.
    """
    try:
        return OrganizationSettings.model_validate(
            OrganizationRepository().get_settings(organization_id)
        )
    except Exception as exc:
        log.warning("direccion_settings_error", error=str(exc)[:200])
        return OrganizationSettings()


def construir_cuadro(
    organization_id: int,
    filas: list[dict[str, Any]],
    ajustes: OrganizationSettings,
    *,
    ventana: Ventana | None = None,
    ahora: datetime | None = None,
) -> CuadroDireccion:
    """El cuadro entero a partir de las filas y la configuración."""
    momento = ahora or datetime.now(UTC)
    hoy = momento.date()
    actual = ventana or Ventana()
    anterior = ventana_anterior(actual, momento)

    valor, prevision, sin_importe, probabilidades = _valor_ponderado(filas, ajustes)
    tarjetas = tarjetas_de_direccion(
        filas,
        valor=valor,
        sin_importe=sin_importe,
        probabilidades=probabilidades,
        ventana=actual,
        anterior=anterior,
    )
    tasa = next(t for t in tarjetas if t.clave == "tasa_exito")

    cerradas = _cerradas(filas, actual)
    perdidas, sin_motivo, muestra_sin_motivo = _perdidas_sin_motivo(cerradas, hoy)
    pendientes, muestra_pendientes = _pendientes_de_resultado(filas, hoy)

    # El Radar mide una cohorte: lo que se abrió desde cada banda y cómo acabó.
    # Por eso su ventana es de altas, no de cierres —con cierres, la tasa de
    # cierre de cualquier banda saldría del 100 %—, y lo dice su panel.
    cohorte = [
        fila for fila in filas if actual.contiene(_parse_iso_datetime(fila.get("identified_at")))
    ]
    calidad = calcular_radar_quality(cohorte, period_from=actual.desde, period_to=actual.hasta)

    return CuadroDireccion(
        organization_id=organization_id,
        periodo_desde=actual.desde,
        periodo_hasta=actual.hasta,
        anterior_desde=anterior.desde if anterior else None,
        anterior_hasta=anterior.hasta if anterior else None,
        tarjetas=tarjetas,
        cierres=len(cerradas),
        cierres_historico=len(_cerradas(filas, Ventana())),
        cortes=cortes_de_direccion(cerradas, tasa.valor),
        win_rate_por_tecnologia=corte_con_minimo(cerradas, clave="tender_tecnologia"),
        win_rate_por_organo=corte_con_minimo(cerradas, clave="tender_organo"),
        perdidas_por_motivo=_perdidas_por_motivo([dict(f) for f in cerradas]),
        perdidas=perdidas,
        perdidas_sin_motivo=sin_motivo,
        perdidas_sin_motivo_muestra=muestra_sin_motivo,
        pendientes_resultado=pendientes,
        pendientes_resultado_muestra=muestra_pendientes,
        radar_quality=calidad,
        radar_ordena_bien=_radar_ordena_bien(calidad),
        probabilidades_etapa_usadas=probabilidades,
        prevision_trimestral=prevision,
        pipeline_sin_importe=sin_importe,
    )


def cuadro_de_direccion(
    user_id: int,
    organization_id: int | None,
    *,
    period_from: datetime | None = None,
    period_to: datetime | None = None,
) -> CuadroDireccion:
    """F4.2 — el cuadro de mando, con el rol comprobado y el ámbito abierto.

    El ``with`` envuelve las consultas, no sólo la resolución: el ámbito de
    tenencia (ADR-034) vive mientras el bloque está abierto.

    Las filas se leen **sin** recortar: la ventana actual, la del año anterior
    y la foto del pipeline salen de la misma lectura, así que no pueden hablar
    de universos distintos.
    """
    # A UTC antes de comparar: una fecha con zona y otra sin ella no se pueden
    # comparar, y la petición acabaría en 500 en vez de en 422.
    desde, hasta = _utc(period_from), _utc(period_to)
    if desde and hasta and hasta <= desde:
        raise PursuitValidationError("period_to debe ser posterior a period_from.")
    with direccion_resuelta(user_id, organization_id) as resuelta:
        filas = PursuitRepository().metric_rows(resuelta)
        return construir_cuadro(resuelta, filas, _ajustes(resuelta), ventana=Ventana(desde, hasta))


def _utc(momento: datetime | None) -> datetime | None:
    if momento is None:
        return None
    return momento.replace(tzinfo=UTC) if momento.tzinfo is None else momento.astimezone(UTC)


# ── F4.5: actividad de la organización ──────────────────────────────────────


#: Campos de ``pursuit.updated`` que el feed publica. Son enumerados: el feed
#: los traduce a etiquetas. Notas, motivos libres e importes se quedan fuera
#: —texto libre de una persona o cifras de oferta no son actividad que deba
#: verse en una lista que lee todo el equipo—.
CampoCambio = Literal["status", "decision", "outcome", "outcome_reason_code"]
_CAMPOS_CAMBIO: tuple[str, ...] = get_args(CampoCambio)


class CambioActividad(BaseModel):
    """Un campo que cambió en un evento: de qué valor a qué valor."""

    model_config = ConfigDict(extra="forbid")

    campo: CampoCambio
    desde: str | None = None
    hasta: str | None = None


class ItemActividad(BaseModel):
    """Una línea del feed del equipo."""

    model_config = ConfigDict(extra="forbid")

    id: int = Field(ge=1)
    pursuit_id: int = Field(ge=1)
    licitacion_id: str
    titulo: str | None = None
    evento: str
    #: Nombre de quien lo hizo. `None` si el usuario se dio de baja: el ledger
    #: es inmutable pero `pursuits.responsible_user_id` se desvincula, así que
    #: un evento puede quedarse sin actor con nombre. Se dice «alguien del
    #: equipo» en vez de inventar uno.
    actor: str | None = None
    cuando: str
    #: Qué cambió, en el orden de `CampoCambio`. Vacío en los eventos que no
    #: son una actualización o que sólo tocaron campos que no se publican.
    cambios: list[CambioActividad] = Field(default_factory=list)


def cambios_de_evento(payload_json: Any) -> list[CambioActividad]:
    """Los cambios publicables de un ``payload_json`` del ledger.

    Un payload ilegible no rompe el feed: el evento se pinta sin detalle.
    """
    if not payload_json:
        return []
    try:
        payload = json.loads(str(payload_json))
    except (TypeError, ValueError):
        return []
    cambios = payload.get("changes") if isinstance(payload, dict) else None
    if not isinstance(cambios, dict):
        return []
    salida: list[CambioActividad] = []
    for campo in _CAMPOS_CAMBIO:
        cambio = cambios.get(campo)
        if not isinstance(cambio, dict):
            continue
        desde, hasta = cambio.get("from"), cambio.get("to")
        if desde == hasta:
            continue
        salida.append(
            CambioActividad.model_validate(
                {
                    "campo": campo,
                    "desde": str(desde) if desde is not None else None,
                    "hasta": str(hasta) if hasta is not None else None,
                }
            )
        )
    return salida


class FeedActividad(BaseModel):
    """Página del feed, con su cursor."""

    model_config = ConfigDict(extra="forbid")

    organization_id: int = Field(ge=1)
    items: list[ItemActividad] = Field(default_factory=list)
    #: `id` desde el que pedir la página siguiente. `None` = no hay más.
    siguiente_cursor: int | None = None
    #: `True` cuando el feed viene **acotado** por el rol de quien pregunta.
    #: No afirma que se haya ocultado nada: `pursuit_events` todavía no guarda
    #: eventos de administración, así que hoy el recorte no quita ninguna fila.
    #: Decir «se ocultaron eventos» a un `member` era describir un filtro que
    #: no llegó a filtrar.
    filtrado_por_rol: bool = False


def actividad_de_organizacion(
    user_id: int,
    *,
    organization_id: int | None = None,
    antes_de_id: int | None = None,
    solo_usuario: int | None = None,
    limit: int = 50,
) -> FeedActividad:
    """F4.5 — qué hizo el equipo, paginado por cursor.

    Un `member` ve el feed **sin los eventos de administración** (invitaciones,
    cambios de rol): el feed de actividad no es el sitio donde enterarse de a
    quién han cambiado de rol. Owner y admin lo ven entero.

    Sin PII de terceros: sólo el nombre de quien actuó, que es miembro de la
    misma organización y por tanto ya visible en Equipo.
    """
    from db.repositories.cuentas import ActividadRepository

    with alcance_resuelto(user_id, organization_id) as (resuelta, rol):
        incluir_admin = str(rol) in ROLES_DIRECCION

        filas = ActividadRepository().feed(
            resuelta,
            antes_de_id=antes_de_id,
            actor_user_id=solo_usuario,
            incluir_admin=incluir_admin,
            limit=limit,
        )
        items = [
            ItemActividad(
                id=int(f["id"]),
                pursuit_id=int(f["pursuit_id"]),
                licitacion_id=str(f["licitacion_id"]),
                titulo=f.get("titulo"),
                evento=str(f["event_type"]),
                actor=f.get("actor"),
                cuando=str(f.get("created_at") or ""),
                cambios=cambios_de_evento(f.get("payload_json")),
            )
            for f in filas
        ]
        return FeedActividad(
            organization_id=resuelta,
            items=items,
            # El cursor sale de la última fila devuelta, no de `len(items)`: con
            # una página incompleta por el filtro de rol, un cursor calculado por
            # posición se saltaría eventos.
            siguiente_cursor=items[-1].id if len(items) == limit else None,
            filtrado_por_rol=not incluir_admin,
        )
