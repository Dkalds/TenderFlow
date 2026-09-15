"""Informe de pipeline semanal por organización (T6).

Qué es
------
Lo que el equipo vería si abriera Dirección un lunes por la mañana, en un
correo: cuántas oportunidades hay en cada estado, qué vence en los próximos
catorce días, qué se ganó y qué se perdió en la semana, y cuántas entraron
nuevas. Con el PDF adjunto, que es lo que se lleva a un comité.

De dónde salen las cifras
-------------------------
De las mismas consultas que la pantalla, y **no** de consultas nuevas:
``PursuitRepository.metric_rows`` para el embudo y los cierres,
``deadline_rows`` para los vencimientos. Es deliberado: dos caminos para la
misma cifra acaban dando dos cifras, y entonces el correo y la pantalla se
contradicen delante del cliente. El win rate por corte lo calcula
``services.direccion.corte_con_minimo``, que ya aplica el mínimo de cinco
cierres por celda — su propio docstring anticipaba este consumidor.

Universo, ventana y fecha del dato (ADR-014)
--------------------------------------------
:class:`InformeSemanal` los lleva como campos y el render los imprime. Un
informe con cifras y sin decir sobre qué se calcularon es un informe que
alguien leerá como si dijera otra cosa — y el destinatario de éste es
precisamente quien decide con él.

Lo que NO hace
--------------
- **No mide aperturas ni clics.** Misma regla que `web/src/lib/analytics.ts`:
  no hay píxel de seguimiento ni enlaces envueltos. Saber quién abrió un correo
  no cambia ninguna decisión del producto y sí cambia lo que hay que contarle a
  un cliente sobre qué se registra.
- **No envía.** Construye y renderiza; quien envía es
  ``scheduler/jobs/informes_programados.py``. Separarlo es lo que permite
  probar el render sin tocar el correo.
- **No inventa un informe vacío.** Una organización sin oportunidades devuelve
  un informe con ``vacio=True`` y el job no lo manda: un correo semanal que
  dice «nada» todas las semanas es la forma más rápida de que lo filtren.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, date, datetime, timedelta
from html import escape
from typing import Any

from observability.logging import get_logger

log = get_logger(__name__)

#: Ventana del informe. Siete días: es un informe **semanal**, y una ventana
#: más larga escondería que una semana fue mala detrás de la anterior.
DIAS_VENTANA = 7

#: Horizonte de vencimientos. Catorce días y no siete: con siete, un plazo que
#: cae el octavo día no aparece en ningún informe hasta que quedan seis, y
#: preparar una oferta lleva más de seis.
DIAS_VENCIMIENTO = 14

#: Estados que sacan una oportunidad del embudo abierto. Espejo de
#: `_ESTADOS_TERMINALES_SQL` en `db/repositories/pursuits.py`.
ESTADOS_CERRADOS: frozenset[str] = frozenset({"won", "lost", "withdrawn"})


@dataclass(frozen=True, slots=True)
class Vencimiento:
    """Un plazo que cae dentro del horizonte."""

    licitacion_id: str
    titulo: str
    fecha: str
    dias: int
    responsable: str | None = None


@dataclass(slots=True)
class InformeSemanal:
    """El informe de una organización, listo para renderizar.

    ``universo``, ``ventana`` y ``fecha_dato`` no son decoración: los exige
    ADR-014 y el render los imprime en la cabecera del correo y del PDF.
    """

    organization_id: int
    organizacion: str
    generado_en: datetime
    desde: date
    hasta: date

    abiertas_por_estado: dict[str, int] = field(default_factory=dict)
    nuevas: int = 0
    ganadas: int = 0
    perdidas: int = 0
    importe_ganado: float = 0.0
    vencimientos: list[Vencimiento] = field(default_factory=list)

    @property
    def abiertas(self) -> int:
        return sum(self.abiertas_por_estado.values())

    @property
    def vacio(self) -> bool:
        """Sin nada que contar. El job no envía estos y lo deja en `ops_events`."""
        return (
            self.abiertas == 0
            and self.nuevas == 0
            and self.ganadas == 0
            and self.perdidas == 0
            and not self.vencimientos
        )

    @property
    def universo(self) -> str:
        return f"Oportunidades de la organización {self.organization_id}, todas las fuentes."

    @property
    def ventana(self) -> str:
        return f"Del {self.desde.isoformat()} al {self.hasta.isoformat()} (UTC)."

    @property
    def fecha_dato(self) -> str:
        return self.generado_en.strftime("%Y-%m-%d %H:%M UTC")

    @property
    def asunto(self) -> str:
        return f"Informe semanal de pipeline · {self.organizacion} · {self.hasta.isoformat()}"


def _fecha(valor: Any) -> date | None:
    """Fecha de un valor que puede venir como `date`, `datetime` o texto ISO."""
    if isinstance(valor, datetime):
        return valor.date()
    if isinstance(valor, date):
        return valor
    texto = str(valor or "").strip()
    if len(texto) < 10:
        return None
    try:
        return date.fromisoformat(texto[:10])
    except ValueError:
        return None


def construir(
    organization_id: int,
    *,
    organizacion: str = "",
    ahora: datetime | None = None,
) -> InformeSemanal:
    """Arma el informe leyendo las mismas consultas que la pantalla."""
    from db.repositories.pursuits import PursuitRepository

    instante = (ahora or datetime.now(UTC)).astimezone(UTC)
    hasta = instante.date()
    # `- 1` porque los dos extremos son inclusivos: `desde <= fecha <= hasta`
    # sobre `hasta - 7` abarca **ocho** fechas distintas, y con el informe
    # saliendo cada lunes, lo cerrado el lunes anterior contaba en dos informes
    # seguidos. Ganadas, perdidas, nuevas e importe se duplicaban en la costura,
    # y la cabecera «Del X al Y» anunciaba una semana de ocho días.
    desde = hasta - timedelta(days=DIAS_VENTANA - 1)

    repo = PursuitRepository()
    # Sin ventana: el embudo abierto es un stock, no un flujo. Acotarlo por
    # `identified_at` contaría sólo las oportunidades nacidas esta semana y
    # daría un pipeline mucho menor del que el equipo tiene delante.
    filas = repo.metric_rows(organization_id)

    informe = InformeSemanal(
        organization_id=organization_id,
        organizacion=organizacion or f"organización {organization_id}",
        generado_en=instante,
        desde=desde,
        hasta=hasta,
    )

    for fila in filas:
        estado = str(fila.get("status") or "desconocido")
        if estado not in ESTADOS_CERRADOS:
            informe.abiertas_por_estado[estado] = informe.abiertas_por_estado.get(estado, 0) + 1

        identificada = _fecha(fila.get("identified_at"))
        if identificada is not None and desde <= identificada <= hasta:
            informe.nuevas += 1

        cerrada = _fecha(fila.get("closed_at"))
        if cerrada is None or not (desde <= cerrada <= hasta):
            continue
        resultado = str(fila.get("outcome") or "")
        if resultado == "won":
            informe.ganadas += 1
            informe.importe_ganado += float(fila.get("awarded_amount_eur") or 0.0)
        elif resultado == "lost":
            informe.perdidas += 1

    informe.vencimientos = _vencimientos(repo, organization_id, hasta)
    return informe


def _vencimientos(repo: Any, organization_id: int, hoy: date) -> list[Vencimiento]:
    """Plazos de la organización dentro del horizonte, del más próximo al último.

    Se reutiliza ``deadline_rows`` para mantener una sola definición de «plazo
    de una oportunidad abierta», pero **acotada en SQL**. Filtrarla en Python,
    que es como nació, dejaba la sección vacía para cualquier organización
    cuyos pursuits cayeran fuera de las primeras ``limit`` filas del corpus:
    el ``LIMIT`` ordena por ``p.id`` sobre todos los tenants, así que los
    equipos creados más tarde se quedaban sin la sección más accionable del
    informe, sin error en ninguna parte y con el agravante de leer las mismas
    5.000 filas una vez por organización en la misma pasada.
    """
    limite = hoy + timedelta(days=DIAS_VENCIMIENTO)
    salida: list[Vencimiento] = []
    for fila in repo.deadline_rows(organization_id=organization_id):
        # De las dos fechas gana la más próxima: las dos son compromisos, y el
        # informe avisa del primero que llega.
        candidatas = [
            f for f in (_fecha(fila.get("fecha_limite")), _fecha(fila.get("next_action_due"))) if f
        ]
        proximas = [f for f in candidatas if hoy <= f <= limite]
        if not proximas:
            continue
        fecha = min(proximas)
        salida.append(
            Vencimiento(
                licitacion_id=str(fila.get("licitacion_id") or ""),
                titulo=str(fila.get("titulo") or fila.get("licitacion_id") or "Sin título"),
                fecha=fecha.isoformat(),
                dias=(fecha - hoy).days,
                responsable=str(fila.get("responsible_email") or "") or None,
            )
        )
    salida.sort(key=lambda v: (v.fecha, v.licitacion_id))
    return salida


# ── Render ──────────────────────────────────────────────────────────────────


def _filas_estado(informe: InformeSemanal) -> list[dict[str, Any]]:
    return [
        {"Estado": estado, "Oportunidades": n}
        for estado, n in sorted(informe.abiertas_por_estado.items(), key=lambda kv: -kv[1])
    ]


def _filas_vencimiento(informe: InformeSemanal) -> list[dict[str, Any]]:
    return [
        {
            "Expediente": v.licitacion_id,
            "Título": v.titulo[:90],
            "Vence": v.fecha,
            "Días": v.dias,
            "Responsable": v.responsable or "sin asignar",
        }
        for v in informe.vencimientos
    ]


def _euros(valor: float) -> str:
    """Importe con separador de miles español: ``1.250.000 €``."""
    return f"{valor:,.0f} €".replace(",", ".")


def render_html(informe: InformeSemanal, *, url_baja: str | None = None) -> str:
    """El cuerpo del correo. HTML de tabla, sin CSS externo ni imágenes.

    Sin hoja de estilos remota y sin imágenes a propósito: los clientes de
    correo bloquean lo primero y piden permiso para lo segundo, así que un
    informe que dependa de ellas llega roto. Y sin píxel de seguimiento, que es
    la razón *de verdad* por la que aquí no hay ninguna imagen.
    """

    def _tabla(titulo: str, filas: list[dict[str, Any]]) -> str:
        if not filas:
            return f"<h3>{escape(titulo)}</h3><p>Nada que mostrar.</p>"
        columnas = list(filas[0].keys())
        cabecera = "".join(f"<th align='left'>{escape(c)}</th>" for c in columnas)
        cuerpo = "".join(
            "<tr>" + "".join(f"<td>{escape(str(f.get(c, '')))}</td>" for c in columnas) + "</tr>"
            for f in filas
        )
        return (
            f"<h3>{escape(titulo)}</h3>"
            "<table border='1' cellpadding='6' cellspacing='0' "
            "style='border-collapse:collapse;font-size:13px'>"
            f"<tr style='background:#1a5276;color:#fff'>{cabecera}</tr>{cuerpo}</table>"
        )

    pie_baja = (
        f"<p style='font-size:11px;color:#777'>"
        f"<a href='{escape(url_baja)}'>Dejar de recibir este informe</a></p>"
        if url_baja
        else ""
    )
    return (
        "<html><body style='font-family:Arial,sans-serif;max-width:760px'>"
        f"<h2>{escape(informe.asunto)}</h2>"
        "<p style='font-size:12px;color:#555'>"
        f"{escape(informe.universo)} {escape(informe.ventana)} "
        f"Dato a {escape(informe.fecha_dato)}.</p>"
        f"<p><b>{informe.abiertas}</b> oportunidades abiertas · "
        f"<b>{informe.nuevas}</b> nuevas esta semana · "
        f"<b>{informe.ganadas}</b> ganadas · <b>{informe.perdidas}</b> perdidas"
        + (
            # Separador de miles a la española: `1,250,000 €` se lee en
            # castellano como 1,25 € y este informe se reenvía a un comité. Es
            # la convención que ya usa `_importe` en `services/email_digest.py`.
            f" · <b>{_euros(informe.importe_ganado)}</b> adjudicados"
            if informe.importe_ganado
            else ""
        )
        + "</p>"
        + _tabla("Pipeline abierto por estado", _filas_estado(informe))
        + _tabla(
            f"Vence en los próximos {DIAS_VENCIMIENTO} días",
            _filas_vencimiento(informe),
        )
        + "<p style='font-size:11px;color:#777'>El PDF adjunto lleva lo mismo. "
        "TenderFlow no registra si abrís este correo ni en qué hacéis clic.</p>"
        + pie_baja
        + "</body></html>"
    )


def render_pdf(informe: InformeSemanal) -> bytes:
    """El adjunto: las mismas dos tablas, con el universo en la cabecera."""
    from services.pdf_tabular import construir_pdf_secciones

    return construir_pdf_secciones(
        informe.asunto,
        [
            ("Pipeline abierto por estado", _filas_estado(informe)),
            (f"Vence en los próximos {DIAS_VENCIMIENTO} días", _filas_vencimiento(informe)),
        ],
        subtitulo=f"{informe.universo} {informe.ventana} Dato a {informe.fecha_dato}.",
        pie=(
            f"Resumen: {informe.abiertas} abiertas · {informe.nuevas} nuevas · "
            f"{informe.ganadas} ganadas · {informe.perdidas} perdidas."
        ),
    )


def nombre_pdf(informe: InformeSemanal) -> str:
    return f"informe-pipeline-{informe.organization_id}-{informe.hasta.isoformat()}.pdf"


# ── Programación (T6): el día, la hora y a quién ────────────────────────────


def leer_programacion(user_id: int, organization_id: int | None) -> dict[str, Any]:
    """La programación de la organización, o los valores por defecto.

    Devuelve algo siempre, también cuando no hay fila: el formulario necesita
    enseñar «lunes a las 07:00, apagado» en vez de un hueco, y crear la fila al
    abrir la pantalla dejaría filas huérfanas de quien sólo pasó a mirar.

    Exige rol de Dirección (`exigir_direccion`): el informe habla del trabajo
    del equipo y quién lo recibe lo decide quien puede ver esa pantalla.
    """
    from db.repositories import report_schedules
    from services.direccion import exigir_direccion

    resuelta = exigir_direccion(user_id, organization_id)
    fila = report_schedules.get(resuelta)
    if fila is None:
        return {
            "organization_id": resuelta,
            "tipo": "pipeline_semanal",
            "activo": False,
            "dia_semana": 0,
            "hora_utc": 7,
            "destinatarios": None,
            "ultimo_envio_at": None,
            "ultimo_estado": None,
        }
    return fila


def guardar_programacion(
    user_id: int,
    organization_id: int | None,
    *,
    activo: bool,
    dia_semana: int,
    hora_utc: int,
    destinatarios: list[str] | None,
) -> dict[str, Any]:
    """Alta o edición. Exige rol de Dirección, igual que la lectura."""
    from db.repositories import report_schedules
    from services.direccion import exigir_direccion

    resuelta = exigir_direccion(user_id, organization_id)
    limpios = [c.strip() for c in (destinatarios or []) if c and c.strip()]
    return report_schedules.guardar(
        resuelta,
        activo=activo,
        dia_semana=dia_semana,
        hora_utc=hora_utc,
        destinatarios=limpios or None,
    )
