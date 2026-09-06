"""F6.3 — llevar el pipeline al CRM donde vive el comercial (D35).

D35 decidió: **plantilla genérica de webhook y CSV con mapeo documentado**, no
un conector nativo. El conector llega cuando una organización lo pida por
escrito y diga cuál — hasta entonces, un conector a Salesforce que nadie use
es superficie que hay que mantener.

El mapeo, y por qué es así
--------------------------
La correspondencia natural en cualquier CRM es: la **cuenta** es el órgano
—quien compra—, no la licitación; la **oportunidad** es el expediente; y la
**etapa** hay que traducirla, porque los ocho estados de este producto no son
los de nadie más. La traducción va aquí y no en el CRM del cliente para que el
payload sea usable sin configurar nada, y se declara en
``docs/integraciones/crm.md``.

Lo que no viaja
---------------
Nada que no sea del pipeline: ni el score, ni la explicación, ni las
predicciones. Un CRM es un sistema de terceros y esto es una exportación, no
una sincronización — cuanto menos salga, menos hay que explicar el día que
alguien pregunte qué se comparte.
"""

from __future__ import annotations

from typing import Any, Final

from pydantic import BaseModel, ConfigDict

__all__ = [
    "CABECERAS_CSV",
    "ETAPAS_CRM",
    "PayloadCRM",
    "a_csv_fila",
    "payload_de_pursuit",
]

#: Traducción de las etapas del producto a las de un CRM genérico. Los nombres
#: de destino son los del embudo estándar (el vocabulario de Salesforce y
#: Dynamics coincide en estos cinco), para que el payload entre sin mapear.
ETAPAS_CRM: Final[dict[str, str]] = {
    "identified": "Prospecting",
    "qualifying": "Qualification",
    "go_no_go": "Needs Analysis",
    "preparing": "Proposal",
    "submitted": "Negotiation",
    "won": "Closed Won",
    "lost": "Closed Lost",
    "withdrawn": "Closed Lost",
}

#: Cabeceras del CSV, en el orden del fichero. Coinciden una a una con los
#: campos del webhook: dos formatos, un solo mapeo que documentar.
CABECERAS_CSV: Final[tuple[str, ...]] = (
    "external_id",
    "account_name",
    "opportunity_name",
    "amount",
    "currency",
    "stage",
    "close_date",
    "owner",
    "source_url",
)


class PayloadCRM(BaseModel):
    """Una oportunidad en el vocabulario de un CRM genérico."""

    model_config = ConfigDict(extra="forbid")

    #: El `id_externo` del expediente. Es la clave con la que el CRM
    #: deduplica: si se mandara el id del pursuit, dos organizaciones que
    #: trabajan el mismo expediente crearían dos oportunidades sin relación.
    external_id: str
    #: La cuenta es el **órgano**, no la licitación: quien compra.
    account_name: str | None = None
    opportunity_name: str
    amount: float | None = None
    currency: str = "EUR"
    stage: str
    #: Fecha de cierre esperada. Se usa la fecha límite de presentación, que es
    #: la única que el CRM puede entender sin explicaciones; la fecha prevista
    #: de adjudicación (F4.4) es una estimación nuestra y no se exporta como si
    #: fuera un compromiso.
    close_date: str | None = None
    owner: str | None = None
    source_url: str | None = None


def payload_de_pursuit(
    *,
    licitacion_id: str,
    titulo: str | None,
    organo: str | None,
    importe: float | None,
    status: str,
    fecha_limite: str | None,
    responsable: str | None,
    url: str | None,
) -> PayloadCRM:
    """Construye el payload. Puro: no consulta nada.

    Una etapa que no esté en el mapa se manda como ``Prospecting`` y no en
    crudo: un CRM con una lista de valores cerrada rechazaría el registro
    entero, y perder la exportación por una etapa nueva sería peor que
    colocarla en la primera del embudo, donde alguien la verá y la moverá.
    """
    return PayloadCRM(
        external_id=licitacion_id,
        account_name=(organo or "").strip() or None,
        opportunity_name=(titulo or licitacion_id)[:255],
        amount=importe,
        stage=ETAPAS_CRM.get(status, "Prospecting"),
        close_date=str(fecha_limite)[:10] if fecha_limite else None,
        owner=responsable,
        source_url=url,
    )


def a_csv_fila(payload: PayloadCRM) -> list[Any]:
    """La fila del CSV, en el orden de ``CABECERAS_CSV``.

    Se deriva del payload y no se construye aparte: un CSV y un webhook que
    puedan divergir son dos mapeos que documentar y sólo uno que alguien
    revise.
    """
    datos = payload.model_dump()
    return [datos[clave] for clave in CABECERAS_CSV]
