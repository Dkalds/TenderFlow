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

log = get_logger(__name__)

_repo = CarteraRepository()

__all__ = [
    "VENTANAS_AVISO_MESES",
    "ContratoCartera",
    "fin_efectivo",
    "listar_cartera",
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


def _a_fecha(valor: Any) -> date | None:
    texto = str(valor or "")[:10]
    try:
        return date.fromisoformat(texto)
    except ValueError:
        return None


def _menos_meses(fecha: date, meses: int) -> date:
    """Resta meses sin dependencias externas.

    Aritmética por meses y no por 30 días: «tres meses antes del 31 de marzo»
    es el 31 de diciembre, no el 31 de diciembre menos un día de deriva. El
    día se recorta al último del mes destino cuando no existe (31 → 28/29).
    """
    total = fecha.year * 12 + (fecha.month - 1) - meses
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
    base = _a_fecha(fecha_fin_publicada)
    origen = "publicada" if base is not None else None

    if base is None:
        inicio = _a_fecha(fecha_inicio)
        meses = _meses_de_duracion(duracion_valor, duracion_unidad)
        if inicio is not None and meses:
            base = _mas_meses(inicio, meses)
            origen = "duracion"

    if base is None:
        return None, None

    if prorrogas_meses > 0:
        base = _mas_meses(base, prorrogas_meses)
        origen = "prorroga"

    return base.isoformat(), origen


def _meses_de_duracion(valor: Any, unidad: str | None) -> int:
    """Duración en meses. Devuelve 0 si no se puede convertir sin adivinar."""
    try:
        cantidad = int(float(valor))
    except (TypeError, ValueError):
        return 0
    if cantidad <= 0:
        return 0
    normalizada = (unidad or "").strip().lower()
    if normalizada.startswith("mes"):
        return cantidad
    if normalizada.startswith(("ano", "año", "year")):
        return cantidad * 12
    if normalizada.startswith("dia"):
        # Sólo si son múltiplos razonables; 45 días no son «un mes y medio»
        # para una ventana de aviso, y redondearlo introduciría un error que
        # nadie podría rastrear.
        return cantidad // 30 if cantidad >= 30 else 0
    return 0


def _mas_meses(fecha: date, meses: int) -> date:
    total = fecha.year * 12 + (fecha.month - 1) + meses
    ano, mes = divmod(total, 12)
    mes += 1
    siguiente = date(ano + 1, 1, 1) if mes == 12 else date(ano, mes + 1, 1)
    ultimo = (siguiente - timedelta(days=1)).day
    return date(ano, mes, min(fecha.day, ultimo))


def ventana_relicitacion(fecha_fin: Any) -> tuple[str | None, str | None]:
    """Cuándo se espera que salga el contrato siguiente.

    Es una **estimación declarada**, no una fecha: los órganos publican la
    relicitación entre seis y tres meses antes de que expire el vigente. Se
    devuelve como intervalo justamente para que no se lea como un compromiso.
    """
    fin = _a_fecha(fecha_fin)
    if fin is None:
        return None, None
    desde = _menos_meses(fin, MESES_ANTES_RELICITACION[0])
    hasta = _menos_meses(fin, MESES_ANTES_RELICITACION[1])
    return desde.isoformat(), hasta.isoformat()


def _meses_hasta(fecha_fin: Any) -> int | None:
    fin = _a_fecha(fecha_fin)
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
    from services.organizations import resolve_organization

    resuelta, _rol = resolve_organization(user_id, organization_id)
    return listar_cartera(resuelta)
