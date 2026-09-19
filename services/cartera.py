"""F4.3 — la vida del contrato después de ganarlo.

``won`` era un estado terminal: la oportunidad se ganaba y desaparecía del
producto, justo cuando empieza lo que decide si se renueva. El incumbente que
quiere seguir siéndolo tenía que llevar la fecha de fin en un calendario
personal, y la relicitación se le pasaba o la veía tarde.

Lo que hace este módulo
-----------------------
Convierte cada oportunidad ganada en un contrato de cartera con su **fecha de
fin efectiva** —la publicada, la derivada de la duración, o la que dejaron las
prórrogas— y la ventana en la que se espera la relicitación. Y añade la acción
que faltaba: «preparar renovación», que crea la oportunidad del siguiente
ciclo ya enlazada al contrato que la origina.

De dónde sale la fecha de fin, y por qué se declara
---------------------------------------------------
Una fecha publicada por la fuente y una derivada de «doce meses desde la
adjudicación» no valen lo mismo, y en la pantalla donde alguien decide cuándo
empezar a preparar una renovación esa diferencia importa. ``fecha_fin_origen``
la lleva siempre: ``publicada``, ``duracion``, ``prorroga`` o ``manual``. Sin
fecha de ninguna clase, el contrato entra en la cartera **sin ventana de
aviso** y lo dice, en vez de inventarse un año por defecto.
"""

from __future__ import annotations

from datetime import UTC, date, datetime, timedelta
from typing import Any

from pydantic import BaseModel, ConfigDict, Field

from db.repositories.cartera import CarteraRepository
from observability.logging import get_logger
from shared.dates import a_fecha
from shared.duracion import meses_de

log = get_logger(__name__)

_repo = CarteraRepository()

__all__ = [
    "EVENTO_CARTERA_VENCE",
    "VENTANAS_AVISO_MESES",
    "CarteraNoEncontradaError",
    "ContratoCartera",
    "PrepararRenovacionIn",
    "RenovacionInvalidaError",
    "RenovacionPreparada",
    "ResumenSincronizacion",
    "accion_para",
    "contrato_de_fuente",
    "emitir_avisos_de_fin",
    "fin_efectivo",
    "listar_cartera",
    "preparar_renovacion",
    "registrar_ganada",
    "sincronizar_cartera",
    "ventana_cruzada",
    "ventana_relicitacion",
]

#: Meses de antelación con los que se avisa del fin de contrato. Seis, tres y
#: uno: el primero es cuando hay que decidir si se va a por la renovación, el
#: segundo cuando hay que estar preparando, y el tercero es el recordatorio de
#: que se acaba. Menos avisos dejan pasar el primero; más, se ignoran todos.
VENTANAS_AVISO_MESES: tuple[int, ...] = (6, 3, 1)

#: Cuánto antes del fin suele publicarse la relicitación. Es una regla del
#: dominio, no una medida: los órganos publican el nuevo contrato entre tres y
#: seis meses antes de que expire el vigente. Se declara como estimación y no
#: se presenta como fecha.
MESES_ANTES_RELICITACION = (6, 3)


class ContratoCartera(BaseModel):
    """Un contrato ganado que sigue vivo."""

    model_config = ConfigDict(extra="forbid")

    id: int = Field(ge=1)
    organization_id: int = Field(ge=1)
    pursuit_id: int = Field(ge=1)
    licitacion_id: str
    titulo: str | None = None
    organo_contratacion: str | None = None
    tecnologia: str | None = None
    cpv: str | None = None
    fecha_inicio: str | None = None
    fecha_fin_efectiva: str | None = None
    #: `publicada` | `duracion` | `prorroga` | `manual`. Nunca se omite cuando
    #: hay fecha: es lo que distingue un dato de una estimación.
    fecha_fin_origen: str | None = None
    importe_adjudicado: float | None = None
    prorrogas_aplicadas: int = Field(default=0, ge=0)
    #: Oportunidad creada por «preparar renovación», si ya se hizo.
    renovacion_pursuit_id: int | None = None
    #: Meses que faltan para el fin. `None` sin fecha de fin.
    meses_restantes: int | None = None
    #: Ventana en la que se espera la relicitación, como par de fechas ISO.
    #: `None` sin fecha de fin: **no se inventa**.
    relicitacion_desde: str | None = None
    relicitacion_hasta: str | None = None


def _desplazar_meses(fecha: date, meses: int) -> date:
    """Desplaza ``meses`` (con signo) sin dependencias externas.

    Aritmética por meses y no por 30 días: «tres meses antes del 31 de marzo»
    es el 31 de diciembre, no el 31 de diciembre menos un día de deriva. El
    día se recorta al último del mes destino cuando no existe (31 → 28/29).

    Uno con signo y no un par sumar/restar: eran la misma función salvo por un
    ``+``, y la parte delicada —el recorte a fin de mes y los bisiestos— es
    justo la que había que arreglar en dos sitios a la vez para que la ventana
    de relicitación y la fecha de fin siguieran hablando del mismo día.
    """
    total = fecha.year * 12 + (fecha.month - 1) + meses
    ano, mes = divmod(total, 12)
    mes += 1
    # Último día del mes destino, sin `calendar`: el día 1 del siguiente menos
    # uno. Sirve para cualquier mes y para años bisiestos.
    siguiente = date(ano + 1, 1, 1) if mes == 12 else date(ano, mes + 1, 1)
    ultimo = (siguiente - timedelta(days=1)).day
    return date(ano, mes, min(fecha.day, ultimo))


def fin_efectivo(
    *,
    fecha_fin_publicada: Any = None,
    fecha_inicio: Any = None,
    duracion_valor: Any = None,
    duracion_unidad: str | None = None,
    prorrogas_meses: int = 0,
) -> tuple[str | None, str | None]:
    """``(fecha_fin_efectiva ISO, origen)``, o ``(None, None)``.

    Prioridad: la fecha publicada gana a la derivada de la duración, porque es
    un dato y la otra es una cuenta. Las prórrogas se suman a la que salga, y
    entonces el origen pasa a ser ``prorroga``: lo que el usuario tiene delante
    ya no es lo que publicó la fuente.

    Sin ninguna de las dos no se devuelve nada. Un contrato sin fecha de fin
    entra en la cartera igualmente —existe— pero sin ventana de aviso, y eso es
    preferible a asignarle un año por defecto que luego nadie recordará que se
    inventó aquí.
    """
    base = a_fecha(fecha_fin_publicada)
    origen = "publicada" if base is not None else None

    if base is None:
        inicio = a_fecha(fecha_inicio)
        meses = _meses_de_duracion(duracion_valor, duracion_unidad)
        if inicio is not None and meses:
            base = _desplazar_meses(inicio, meses)
            origen = "duracion"

    if base is None:
        return None, None

    if prorrogas_meses > 0:
        base = _desplazar_meses(base, prorrogas_meses)
        origen = "prorroga"

    return base.isoformat(), origen


def _meses_de_duracion(valor: Any, unidad: str | None) -> int:
    """Duración en meses enteros. ``0`` si no se puede convertir sin adivinar.

    El vocabulario lo pone ``shared/duracion.py``, que es el que habla la
    columna: ``duracion_unidad`` guarda el ``@unitCode`` de CODICE (``MON``,
    ``ANN``, ``DAY``…), no «meses» ni «años». Esta función los buscaba en
    castellano, así que devolvía 0 para toda fila real y la cartera se quedaba
    sin fecha de fin derivada — en silencio, porque 0 es también la respuesta
    legítima a «no se sabe».

    Se trunca hacia abajo a propósito: media docena de días no mueve una
    ventana de relicitación, y redondear hacia arriba adelantaría un aviso sin
    que nadie pudiera rastrear por qué.
    """
    meses = meses_de(valor, unidad)
    return 0 if meses is None else int(meses)


def ventana_relicitacion(fecha_fin: Any) -> tuple[str | None, str | None]:
    """Cuándo se espera que salga el contrato siguiente.

    Es una **estimación declarada**, no una fecha: los órganos publican la
    relicitación entre seis y tres meses antes de que expire el vigente. Se
    devuelve como intervalo justamente para que no se lea como un compromiso.
    """
    fin = a_fecha(fecha_fin)
    if fin is None:
        return None, None
    desde = _desplazar_meses(fin, -MESES_ANTES_RELICITACION[0])
    hasta = _desplazar_meses(fin, -MESES_ANTES_RELICITACION[1])
    return desde.isoformat(), hasta.isoformat()


def _meses_hasta(fecha_fin: Any) -> int | None:
    fin = a_fecha(fecha_fin)
    if fin is None:
        return None
    hoy = datetime.now(UTC).date()
    return (fin.year - hoy.year) * 12 + (fin.month - hoy.month)


def listar_cartera(organization_id: int) -> list[ContratoCartera]:
    """La cartera de una organización, con ventana y meses restantes."""
    contratos: list[ContratoCartera] = []
    for fila in _repo.list_for_organization(organization_id):
        desde, hasta = ventana_relicitacion(fila.get("fecha_fin_efectiva"))
        contratos.append(
            ContratoCartera(
                **{k: v for k, v in fila.items() if k in ContratoCartera.model_fields},
                meses_restantes=_meses_hasta(fila.get("fecha_fin_efectiva")),
                relicitacion_desde=desde,
                relicitacion_hasta=hasta,
            )
        )
    return contratos


def cartera_de_usuario(
    user_id: int, *, organization_id: int | None = None
) -> list[ContratoCartera]:
    """La cartera de la organización activa del usuario.

    La resolución de organización vive **aquí** y no en la ruta: `api/` no
    importa `resolve_organization` directamente (lo audita
    `test_organization_sql_isolation`), porque cada ruta que lo hiciera sería
    otro sitio donde equivocarse con el ámbito.
    """
    from services.organizations import alcance_resuelto

    with alcance_resuelto(user_id, organization_id) as (resuelta, _rol):
        return listar_cartera(resuelta)


# ── Escritor: de oportunidad ganada a contrato en cartera ──────────────────
#
# La tabla existía desde v106 y nada la escribía en producción: la vista de
# Cartera salía vacía para todo el mundo. El escritor vive aquí y no en el
# repositorio porque derivar la fecha de fin es regla de dominio
# (`fin_efectivo`); el repositorio solo persiste lo que ya se decidió.

#: Orígenes que el escritor automático no pisa. `manual` es una fecha que una
#: persona corrigió a mano: la resincronización diaria no puede deshacerla.
_ORIGENES_INTOCABLES = frozenset({"manual"})


def _num(valor: Any) -> float | None:
    try:
        return None if valor is None else float(valor)
    except (TypeError, ValueError):
        return None


def contrato_de_fuente(fila: dict[str, Any]) -> dict[str, Any]:
    """Los campos de ``contratos_cartera`` que salen de una oportunidad ganada.

    Puro: recibe una fila de ``CarteraRepository.fuentes_ganadas`` y devuelve
    lo que hay que persistir, sin tocar la base. Así el backfill puede decir
    qué cambiaría antes de escribir, y los tests no necesitan Postgres.

    - **Inicio**: ``licitaciones.fecha_inicio``; si no se publicó, la primera
      adjudicación. Es la misma prioridad que el horizonte de renovaciones,
      para que un contrato no tenga una fecha en Cartera y otra en Renovaciones.
    - **Fin**: lo decide :func:`fin_efectivo`. Las prórrogas que registra
      ``contract_events`` ya movieron ``licitaciones.fecha_fin`` o la
      duración —eso es lo que las detecta—, así que aquí no se suman meses:
      sumar otra vez contaría la prórroga dos veces. Lo que sí cambia es el
      **origen**, que pasa a ``prorroga``: lo que el usuario tiene delante ya
      no es lo que se publicó al adjudicar.
    - **Importe**: el que el equipo anotó al cerrar la oportunidad; si no lo
      anotó y la oportunidad es del expediente completo, la suma adjudicada.
      Con lote, la suma del expediente mezclaría lotes que no se ganaron.
    """
    inicio = a_fecha(fila.get("fecha_inicio")) or a_fecha(fila.get("fecha_adjudicacion"))
    fin, origen = fin_efectivo(
        fecha_fin_publicada=fila.get("fecha_fin"),
        fecha_inicio=inicio,
        duracion_valor=fila.get("duracion_valor"),
        duracion_unidad=fila.get("duracion_unidad"),
    )
    prorrogas = int(fila.get("prorrogas") or 0)
    if fin is not None and prorrogas > 0:
        origen = "prorroga"
    importe = _num(fila.get("awarded_amount_eur"))
    if importe is None and fila.get("lote_numero") is None:
        importe = _num(fila.get("importe_adjudicaciones"))
    return {
        "organization_id": int(fila["organization_id"]),
        "pursuit_id": int(fila["pursuit_id"]),
        "licitacion_id": str(fila["licitacion_id"]),
        "fecha_inicio": inicio.isoformat() if inicio is not None else None,
        "fecha_fin_efectiva": fin,
        "fecha_fin_origen": origen,
        "importe_adjudicado": importe,
        "prorrogas_aplicadas": prorrogas,
    }


def _existente(fila: dict[str, Any]) -> dict[str, Any] | None:
    if fila.get("cartera_id") is None:
        return None
    return {
        "fecha_inicio": fila.get("cartera_fecha_inicio"),
        "fecha_fin_efectiva": fila.get("cartera_fecha_fin_efectiva"),
        "fecha_fin_origen": fila.get("cartera_fecha_fin_origen"),
        "importe_adjudicado": _num(fila.get("cartera_importe_adjudicado")),
        "prorrogas_aplicadas": int(fila.get("cartera_prorrogas_aplicadas") or 0),
    }


_CAMPOS_COMPARABLES = (
    "fecha_inicio",
    "fecha_fin_efectiva",
    "fecha_fin_origen",
    "importe_adjudicado",
    "prorrogas_aplicadas",
)


def accion_para(fila: dict[str, Any]) -> tuple[str, dict[str, Any]]:
    """``(accion, contrato)`` para una oportunidad ganada.

    ``accion`` ∈ ``nuevo`` | ``actualizado`` | ``sin_cambios`` | ``manual``.
    Puro, como :func:`contrato_de_fuente`: es lo que imprime el dry-run.
    """
    contrato = contrato_de_fuente(fila)
    previo = _existente(fila)
    if previo is None:
        return "nuevo", contrato
    if previo.get("fecha_fin_origen") in _ORIGENES_INTOCABLES:
        return "manual", contrato
    if all(str(previo.get(c)) == str(contrato.get(c)) for c in _CAMPOS_COMPARABLES):
        return "sin_cambios", contrato
    return "actualizado", contrato


def registrar_ganada(organization_id: int, pursuit_id: int) -> bool:
    """Crea o actualiza el contrato de cartera de una oportunidad ganada.

    Lo llama ``services.pursuits.update_pursuit`` al cerrar como ``won``.
    ``True`` si escribió. Una oportunidad que no está ganada (o que no existe)
    no escribe nada: la cartera es la proyección de ``won``, no una lista que
    se pueda rellenar por otro camino.
    """
    filas = _repo.fuentes_ganadas(organization_id=organization_id, pursuit_id=pursuit_id)
    if not filas:
        return False
    accion, contrato = accion_para(filas[0])
    if accion in ("sin_cambios", "manual"):
        return False
    _repo.upsert(**contrato)
    log.info(
        "cartera_contrato_registrado",
        pursuit_id=pursuit_id,
        organization_id=organization_id,
        accion=accion,
        origen=contrato["fecha_fin_origen"],
    )
    return True


class ResumenSincronizacion(BaseModel):
    """Qué hizo (o haría, en dry-run) una pasada de sincronización."""

    model_config = ConfigDict(extra="forbid")

    ganadas: int = 0
    nuevos: int = 0
    actualizados: int = 0
    sin_cambios: int = 0
    manuales: int = 0
    #: Contratos sin fecha de fin de ninguna clase. Entran igual, sin aviso.
    sin_fecha: int = 0
    dry_run: bool = True


def sincronizar_cartera(*, dry_run: bool = True) -> ResumenSincronizacion:
    """Lleva a la cartera todas las oportunidades ganadas. Idempotente.

    Sirve de backfill (las ganadas antes de que existiera el escritor) y de
    resincronización: una prórroga que ``contract_events`` registra después
    de ganar mueve ``licitaciones.fecha_fin``, y esta pasada la lleva a la
    cartera. Una segunda ejecución seguida no escribe nada.
    """
    resumen = ResumenSincronizacion(dry_run=dry_run)
    for fila in _repo.fuentes_ganadas():
        resumen.ganadas += 1
        accion, contrato = accion_para(fila)
        if contrato["fecha_fin_efectiva"] is None:
            resumen.sin_fecha += 1
        if accion == "sin_cambios":
            resumen.sin_cambios += 1
            continue
        if accion == "manual":
            resumen.manuales += 1
            continue
        if accion == "nuevo":
            resumen.nuevos += 1
        else:
            resumen.actualizados += 1
        if not dry_run:
            _repo.upsert(**contrato)
    return resumen


# ── Avisos de fin de contrato (6, 3 y 1 meses) ─────────────────────────────

#: Tipo del evento en el outbox (`shared/events.py`) y agregado con el que se
#: escribe. El agregado es la fila de cartera: es lo que deja preguntar «¿ya
#: avisé de este contrato en esta ventana?» por el índice de `domain_events`.
EVENTO_CARTERA_VENCE = "pursuit.cartera_vence"
_AGREGADO_CARTERA = "contrato_cartera"


def ventana_cruzada(fecha_fin: Any, hoy: date) -> int | None:
    """La ventana de aviso **más urgente** que el contrato ya cruzó, o ``None``.

    Un contrato que vence dentro de 2 meses cruzó la de 6 y la de 3; se avisa
    de la de 3. Avisar de las dos a la vez —lo que pasaría la primera vez que
    corre el job sobre una cartera recién rellenada— serían dos correos que
    dicen lo mismo con distinto número. Un contrato ya vencido no avisa: el
    aviso sirve para preparar la renovación, no para contar que se pasó.
    """
    fin = a_fecha(fecha_fin)
    if fin is None or fin <= hoy:
        return None
    cruzadas = [m for m in VENTANAS_AVISO_MESES if _desplazar_meses(fin, -m) <= hoy]
    return min(cruzadas) if cruzadas else None


def emitir_avisos_de_fin(hoy: date | None = None) -> int:
    """Escribe un ``pursuit.cartera_vence`` por contrato y ventana cruzada.

    Devuelve cuántos eventos escribió. Idempotente por ``(contrato, ventana,
    fecha de fin)``: el job corre a diario y cada pasada vería los mismos
    contratos. Si una prórroga mueve la fecha de fin, el contrato vuelve a
    avisar con la fecha nueva, que es lo que se espera.

    El destinatario es el responsable de la oportunidad ganada. El opt-out es
    la preferencia ``pursuit.cartera_vence`` de Ajustes, que el despachador
    consulta antes de entregar (``clave_ajustes`` del catálogo).
    """
    from db.events import append_domain_event, get_events

    dia = hoy or datetime.now(UTC).date()
    horizonte = _desplazar_meses(dia, max(VENTANAS_AVISO_MESES))
    emitidos = 0
    for contrato in _repo.vencen_entre(
        desde_iso=(dia + timedelta(days=1)).isoformat(),
        hasta_iso=(horizonte + timedelta(days=1)).isoformat(),
    ):
        fin = str(contrato.get("fecha_fin_efectiva") or "")[:10]
        meses = ventana_cruzada(fin, dia)
        if meses is None:
            continue
        cartera_id = int(contrato["id"])
        previos = get_events(_AGREGADO_CARTERA, cartera_id, event_type=EVENTO_CARTERA_VENCE)
        if any(
            (ev.get("payload") or {}).get("meses") == meses
            and (ev.get("payload") or {}).get("fecha_fin") == fin
            for ev in previos
        ):
            continue
        responsable = contrato.get("responsible_user_id")
        titulo = contrato.get("titulo") or contrato.get("licitacion_id")
        plazo = "un mes" if meses == 1 else f"{meses} meses"
        append_domain_event(
            EVENTO_CARTERA_VENCE,
            cartera_id,
            _AGREGADO_CARTERA,
            {
                "pursuit_id": int(contrato["pursuit_id"]),
                "licitacion_id": contrato.get("licitacion_id"),
                "cartera_id": cartera_id,
                "meses": meses,
                "fecha_fin": fin,
                "titulo": titulo,
                "organo_contratacion": contrato.get("organo_contratacion"),
                "renovacion_pursuit_id": contrato.get("renovacion_pursuit_id"),
                "detalle": f"El contrato termina el {fin} (quedan menos de {plazo}).",
                "destinatarios": [int(responsable)] if responsable is not None else [],
                "organization_id": int(contrato["organization_id"]),
            },
            organization_id=int(contrato["organization_id"]),
        )
        emitidos += 1
    return emitidos


# ── «Preparar renovación» ──────────────────────────────────────────────────


class CarteraNoEncontradaError(LookupError):
    """El contrato no existe en la cartera de esa organización."""


class RenovacionInvalidaError(ValueError):
    """El expediente indicado no sirve como renovación del contrato."""


class PrepararRenovacionIn(BaseModel):
    """Cuerpo de «preparar renovación»: el expediente de la relicitación."""

    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    #: `id_externo` de la relicitación. El del contrato vigente no sirve: ya
    #: tiene su oportunidad (la ganada).
    licitacion_id: str = Field(min_length=1, max_length=500)


class RenovacionPreparada(BaseModel):
    """Resultado de «preparar renovación»."""

    model_config = ConfigDict(extra="forbid")

    cartera_id: int = Field(ge=1)
    renovacion_pursuit_id: int = Field(ge=1)
    #: `False` cuando el contrato ya tenía oportunidad de renovación: dos
    #: clics no crean dos oportunidades.
    creada: bool


def _nota_de_renovacion(contrato: dict[str, Any]) -> str:
    fin = contrato.get("fecha_fin_efectiva")
    origen = contrato.get("fecha_fin_origen")
    fin_txt = f" que termina el {str(fin)[:10]} (fecha {origen})" if fin else ""
    return (
        f"Renovación del contrato {contrato['licitacion_id']}{fin_txt}. "
        f"Oportunidad ganada de origen: #{contrato['pursuit_id']}."
    )


def preparar_renovacion(
    user_id: int,
    cartera_id: int,
    licitacion_id: str,
    *,
    organization_id: int | None = None,
) -> RenovacionPreparada:
    """Crea la oportunidad de la relicitación, enlazada al contrato. Idempotente.

    La oportunidad nace en ``identified`` sobre el expediente de la
    **relicitación** —no sobre el del contrato vigente, que ya tiene su
    oportunidad ganada y la unicidad por expediente lo impediría— con una nota
    que enlaza el contrato de origen. Si el contrato ya tenía renovación se
    devuelve esa y no se crea nada.
    """
    from services.organizations import alcance_resuelto
    from services.pursuit_comments import add_comment
    from services.pursuits import create_pursuit
    from shared.dto import PursuitCommentCreate, PursuitCreate

    with alcance_resuelto(user_id, organization_id, write=True) as (resuelta, _rol):
        contrato = _repo.get(resuelta, cartera_id)
        if contrato is None:
            raise CarteraNoEncontradaError("Contrato no encontrado en la cartera.")
        if contrato.get("renovacion_pursuit_id") is not None:
            return RenovacionPreparada(
                cartera_id=cartera_id,
                renovacion_pursuit_id=int(contrato["renovacion_pursuit_id"]),
                creada=False,
            )
        destino = licitacion_id.strip()
        if destino == str(contrato["licitacion_id"]):
            raise RenovacionInvalidaError(
                "La renovación es el expediente de la relicitación, no el del contrato vigente."
            )
        pursuit, _creada = create_pursuit(
            user_id, PursuitCreate(licitacion_id=destino, organization_id=resuelta)
        )
        if not _repo.marcar_renovacion(
            organization_id=resuelta,
            cartera_id=cartera_id,
            renovacion_pursuit_id=int(pursuit.id),
        ):
            # Otro clic llegó antes: gana el enlace que ya está escrito.
            actual = _repo.get(resuelta, cartera_id) or {}
            enlazada = actual.get("renovacion_pursuit_id")
            return RenovacionPreparada(
                cartera_id=cartera_id,
                renovacion_pursuit_id=int(enlazada or pursuit.id),
                creada=False,
            )
        try:
            add_comment(
                user_id,
                int(pursuit.id),
                PursuitCommentCreate(body=_nota_de_renovacion(contrato)),
                organization_id=resuelta,
                idempotency_key=f"renovacion-cartera-{cartera_id}",
            )
        except Exception as exc:
            # La oportunidad ya está creada y enlazada; la nota es contexto.
            log.warning("cartera_nota_renovacion_fallida", cartera_id=cartera_id, error=str(exc))
        return RenovacionPreparada(
            cartera_id=cartera_id, renovacion_pursuit_id=int(pursuit.id), creada=True
        )
