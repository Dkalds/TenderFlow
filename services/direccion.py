"""F4.2 (cuadro de mando) y F4.5 (actividad del equipo).

El Embudo son tres barras y cuatro cifras en 128 líneas. Con eso, un owner no
puede responder ninguna de las preguntas que se hace: dónde ganamos, dónde
perdemos y por qué, cuánto tarda el ciclo, y si el equipo está trabajando lo
que dijimos que íbamos a trabajar.

Cada tarjeta declara de qué está hecha
--------------------------------------
Universo, ventana y ``n``, siempre (ADR-014). Y **ninguna se pinta por debajo
del mínimo de su métrica**: la regla no es «avisar de que hay pocos casos»,
es no publicar el número. Un win rate del 100 % sobre dos cierres, en la
pantalla que mira dirección, es peor que un hueco — el hueco se pregunta, el
número se cree.

Permisos
--------
Solo owner y admin, y el control está **en el servicio**, no en el rail: un
`member` que teclee la URL recibe 403, no una pantalla sin enlace. Un rail sin
enlace es una sugerencia; esto es un permiso.
"""

from __future__ import annotations

from collections.abc import Iterator, Mapping, Sequence
from contextlib import contextmanager
from statistics import median
from typing import Any, Literal

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
    _perdidas_por_motivo,
    _valor_ponderado,
    calcular_radar_quality,
)
from shared.dates import a_fecha
from shared.dto import OrganizationSettings, PerdidaPorMotivo, RadarQuality

log = get_logger(__name__)

__all__ = [
    "MINIMO_CICLO",
    "MINIMO_POR_CORTE",
    "ROLES_DIRECCION",
    "CuadroDireccion",
    "TarjetaMetrica",
    "construir_cuadro",
    "corte_con_minimo",
    "cuadro_de_direccion",
    "tarjetas_de_direccion",
]

#: Roles que pueden abrir Dirección.
ROLES_DIRECCION: frozenset[str] = frozenset({"owner", "admin"})

#: Cierres mínimos por celda de un corte (win rate por tecnología, por órgano).
#: Cinco, el mismo que F3.1 usa para los motivos de pérdida: es la misma
#: pregunta —«¿cuántos casos hacen falta para que esto signifique algo?»— y
#: dos umbrales distintos en la misma pantalla serían dos productos.
MINIMO_POR_CORTE = 5

#: Cierres mínimos para publicar el tiempo de ciclo. El mismo cinco, por el
#: mismo motivo: con dos cierres, la mediana es la duración de uno de ellos.
MINIMO_CICLO = MINIMO_POR_CORTE

#: Banda del Radar cuya precisión va a la tarjeta. Es la promesa del producto
#: —«lo que marco como Caliente se gana más»— y la única de la que dirección
#: necesita una cifra; el reparto por banda completo viaja en ``radar_quality``.
BANDA_TARJETA_RADAR = "Caliente"

#: Unidad de la cifra de una tarjeta. Viaja en el contrato para que la
#: pantalla no tenga que deducir de la ``clave`` si formatea euros o días.
UnidadTarjeta = Literal["eur", "dias", "pct"]


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


class CorteMetrica(BaseModel):
    """Una fila de un corte (por tecnología, por órgano)."""

    model_config = ConfigDict(extra="forbid")

    clave: str
    valor: float | None = None
    n: int = Field(ge=0)


class CuadroDireccion(BaseModel):
    """Lo que ve owner o admin en Dirección."""

    model_config = ConfigDict(extra="forbid")

    organization_id: int = Field(ge=1)
    tarjetas: list[TarjetaMetrica] = Field(default_factory=list)
    win_rate_por_tecnologia: list[CorteMetrica] = Field(default_factory=list)
    win_rate_por_organo: list[CorteMetrica] = Field(default_factory=list)
    #: Mínimo aplicado, declarado en vez de repetido en la UI.
    n_minimo: int = MINIMO_POR_CORTE
    #: Reparto de las pérdidas por motivo codificado (D37). Vacío por debajo
    #: de `perdidas_n_minimo`: el mínimo lo aplica el servicio, no la pantalla.
    perdidas_por_motivo: list[PerdidaPorMotivo] = Field(default_factory=list)
    perdidas_n_minimo: int = MINIMO_PERDIDAS_POR_MOTIVO
    #: Precisión del Radar por banda de entrada. `None` cuando ninguna
    #: oportunidad lleva banda sellada: no se midió, no «acierta el 0 %».
    radar_quality: RadarQuality | None = None
    #: Probabilidad por etapa con la que se ponderó el pipeline: son supuestos,
    #: y sin ellos la cifra no es reproducible (ADR-014).
    probabilidades_etapa_usadas: dict[str, int] = Field(default_factory=dict)


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


def corte_con_minimo(
    filas: list[dict[str, Any]],
    *,
    clave: str,
    ganadas: str = "won",
    perdidas: str = "lost",
    minimo: int = MINIMO_POR_CORTE,
) -> list[CorteMetrica]:
    """Win rate por ``clave``, con el mínimo aplicado **dentro**.

    El corte se devuelve con ``valor=None`` en las celdas por debajo del
    mínimo, en vez de omitirlas. Omitirlas escondería que existe un órgano con
    tres cierres, que es información: dice dónde el equipo está empezando.

    Se aplica aquí y no en la pantalla porque el mismo corte lo consumen el
    cuadro de mando, el informe semanal y el PDF, y un mínimo repartido entre
    tres consumidores es un mínimo que uno de los tres se salta.
    """
    agregados: dict[str, dict[str, int]] = {}
    for fila in filas:
        etiqueta = str(fila.get(clave) or "").strip() or "sin clasificar"
        resultado = str(fila.get("outcome") or "")
        if resultado not in (ganadas, perdidas):
            continue
        celda = agregados.setdefault(etiqueta, {"won": 0, "total": 0})
        celda["total"] += 1
        if resultado == ganadas:
            celda["won"] += 1

    cortes = [
        CorteMetrica(
            clave=etiqueta,
            n=datos["total"],
            valor=(datos["won"] / datos["total"]) if datos["total"] >= minimo else None,
        )
        for etiqueta, datos in agregados.items()
    ]
    # Por volumen y, a igualdad, alfabético: dos lecturas seguidas no pueden
    # devolver el corte en distinto orden.
    cortes.sort(key=lambda c: (-c.n, c.clave))
    return cortes


# ── F4.2: tarjetas ──────────────────────────────────────────────────────────


def _tarjeta_valor_ponderado(
    filas: Sequence[Mapping[str, Any]],
    valor: float,
    sin_importe: int,
    probabilidades: Mapping[str, int],
) -> TarjetaMetrica:
    """El pipeline abierto en euros, ponderado por etapa.

    Es la misma cifra que Mi Pipeline → Embudo (`pipeline_value_eur`), sacada
    de la misma función: dos pantallas con dos valores del pipeline serían dos
    pipelines. `probabilidades` son las etapas con probabilidad > 0 que
    aparecieron, o sea, las abiertas.
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
            "Foto del pipeline actual, sin ventana."
        ),
        nota=nota,
    )


def _tarjeta_ciclo(filas: Sequence[Mapping[str, Any]], minimo: int) -> TarjetaMetrica:
    """Mediana de días entre identificar la oportunidad y cerrarla.

    Solo ganadas y perdidas: una retirada se cierra cuando alguien se acuerda
    de archivarla, y su fecha mediría la limpieza del tablero, no el ciclo.
    Mediana y no media: una oportunidad que se quedó un año olvidada movería
    la media semanas enteras.
    """
    duraciones: list[int] = []
    for fila in filas:
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
            "Ventana: todo el histórico de la organización."
        ),
        nota=None if suficiente else f"Sin base: {n} cierre(s) con fechas; hacen falta {minimo}.",
    )


def _tarjeta_perdidas(filas: Sequence[Mapping[str, Any]], minimo: int) -> TarjetaMetrica:
    """Qué parte de las pérdidas tiene un motivo de D37.

    Es la cifra que dice cuánto se puede creer el reparto por motivo que va
    debajo: un reparto con la mitad de las pérdidas `sin_codificar` habla de
    la otra mitad, no del equipo.
    """
    perdidas = [fila for fila in filas if fila.get("outcome") == "lost"]
    n = len(perdidas)
    codificadas = sum(
        1
        for fila in perdidas
        if (str(fila.get("outcome_reason_code") or "").strip() or SIN_CODIFICAR) != SIN_CODIFICAR
    )
    suficiente = n >= minimo
    return TarjetaMetrica(
        clave="perdidas_codificadas",
        etiqueta="Pérdidas con motivo codificado",
        valor=(codificadas / n) if suficiente else None,
        unidad="pct",
        n=n,
        n_minimo=minimo,
        universo=(
            "Oportunidades perdidas con un motivo de la lista cerrada (precio, "
            "solvencia, técnica…). Ventana: todo el histórico de la organización."
        ),
        nota=None if suficiente else f"Sin base: {n} pérdida(s); hacen falta {minimo}.",
    )


def _tarjeta_radar(calidad: RadarQuality | None) -> TarjetaMetrica:
    """Precisión de la banda Caliente: de lo que el Radar puso arriba, cuánto se ganó."""
    etiqueta = f"Precisión del Radar (banda {BANDA_TARJETA_RADAR})"
    universo = (
        f"Oportunidades abiertas desde la banda {BANDA_TARJETA_RADAR} del Radar y ya "
        "resueltas (ganada o perdida): qué parte se ganó."
    )
    if calidad is None:
        return TarjetaMetrica(
            clave="precision_radar",
            etiqueta=etiqueta,
            unidad="pct",
            universo=universo,
            nota=(
                "Sin base: ninguna oportunidad lleva sellada la banda del Radar con la "
                "que se abrió."
            ),
        )
    banda = next((b for b in calidad.bandas if b.banda == BANDA_TARJETA_RADAR), None)
    minimo = calidad.minimo_por_banda
    resueltas = banda.resueltas if banda is not None else 0
    precision = banda.precision if banda is not None and banda.suficiente else None
    ventana = (
        "el periodo pedido"
        if calidad.ventana_origen == "periodo_solicitado"
        else "todo el histórico"
    )
    return TarjetaMetrica(
        clave="precision_radar",
        etiqueta=etiqueta,
        valor=precision,
        unidad="pct",
        n=resueltas,
        n_minimo=minimo,
        universo=f"{universo} Ventana: {ventana} de oportunidades con banda sellada.",
        nota=(
            None
            if precision is not None
            else f"Sin base: {resueltas} cierre(s) en la banda; hacen falta {minimo}."
        ),
    )


def tarjetas_de_direccion(
    filas: Sequence[Mapping[str, Any]],
    *,
    valor: float,
    sin_importe: int,
    probabilidades: Mapping[str, int],
    radar_quality: RadarQuality | None,
) -> list[TarjetaMetrica]:
    """Las cuatro tarjetas, en el orden en que se leen: dinero, tiempo, por qué, Radar.

    Función pura sobre las filas de ``metric_rows``: las tarjetas y los cortes
    de la misma respuesta hablan de exactamente el mismo universo.
    """
    return [
        _tarjeta_valor_ponderado(filas, valor, sin_importe, probabilidades),
        _tarjeta_ciclo(filas, MINIMO_CICLO),
        _tarjeta_perdidas(filas, MINIMO_PERDIDAS_POR_MOTIVO),
        _tarjeta_radar(radar_quality),
    ]


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
) -> CuadroDireccion:
    """El cuadro entero a partir de las filas y la configuración."""
    valor, _prevision, sin_importe, probabilidades = _valor_ponderado(filas, ajustes)
    calidad = calcular_radar_quality(filas)
    return CuadroDireccion(
        organization_id=organization_id,
        tarjetas=tarjetas_de_direccion(
            filas,
            valor=valor,
            sin_importe=sin_importe,
            probabilidades=probabilidades,
            radar_quality=calidad,
        ),
        win_rate_por_tecnologia=corte_con_minimo(filas, clave="tender_tecnologia"),
        win_rate_por_organo=corte_con_minimo(filas, clave="tender_organo"),
        perdidas_por_motivo=_perdidas_por_motivo(filas),
        radar_quality=calidad,
        probabilidades_etapa_usadas=probabilidades,
    )


def cuadro_de_direccion(user_id: int, organization_id: int | None) -> CuadroDireccion:
    """F4.2 — el cuadro de mando, con el rol comprobado y el ámbito abierto.

    El ``with`` envuelve las consultas, no sólo la resolución: el ámbito de
    tenencia (ADR-034) vive mientras el bloque está abierto.
    """
    with direccion_resuelta(user_id, organization_id) as resuelta:
        filas = PursuitRepository().metric_rows(resuelta)
        return construir_cuadro(resuelta, filas, _ajustes(resuelta))


# ── F4.5: actividad de la organización ──────────────────────────────────────


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
