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

import csv
import io
from typing import Any, Final

from pydantic import BaseModel, ConfigDict

from shared.export_safety import sanitize_spreadsheet_value

__all__ = [
    "CABECERAS_CSV",
    "ETAPAS_CRM",
    "PayloadCRM",
    "a_csv_fila",
    "csv_crm",
    "payload_de_pursuit",
    "render_crm_export",
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
    # Mismo saneado que `services/exports.py` y que el CSV del listado: el
    # nombre del órgano y el título vienen de la fuente, y un título que
    # empieza por `=` o `@` es una fórmula que Excel ejecuta al abrir el
    # fichero. Dos exports de las mismas filas con propiedades de seguridad
    # distintas es una diferencia que no se ve hasta que alguien abre el malo.
    return [sanitize_spreadsheet_value(datos[clave]) for clave in CABECERAS_CSV]


def csv_crm(filas: list[dict[str, Any]]) -> bytes:
    """El CSV del mapeo a partir de las filas del tablero. Puro.

    ``filas`` son las de ``PursuitRepository.export_rows`` (las mismas del
    export del tablero, C6.7). UTF-8 **con BOM**, como declara
    ``docs/integraciones/crm.md``: sin él, Excel abre el fichero en la página
    de códigos local y rompe los acentos de los órganos.
    """
    salida = io.StringIO()
    escritor = csv.writer(salida, lineterminator="\r\n")
    escritor.writerow(CABECERAS_CSV)
    for fila in filas:
        importe = fila.get("tender_importe")
        escritor.writerow(
            a_csv_fila(
                payload_de_pursuit(
                    licitacion_id=str(fila.get("licitacion_id") or ""),
                    titulo=fila.get("tender_title"),
                    organo=fila.get("organo_contratacion"),
                    importe=float(importe) if importe is not None else None,
                    status=str(fila.get("status") or ""),
                    fecha_limite=fila.get("tender_deadline"),
                    responsable=fila.get("responsable"),
                    url=fila.get("tender_url"),
                )
            )
        )
    return ("﻿" + salida.getvalue()).encode("utf-8")


def render_crm_export(
    user_id: int,
    *,
    organization_id: int | None = None,
    status: str | None = None,
    responsible_user_id: int | None = None,
    limit: int = 10_000,
) -> tuple[bytes, int]:
    """``(bytes, n_filas)`` del CSV para el CRM, con el ámbito ya resuelto.

    La organización se resuelve aquí y no en la ruta por la misma razón que
    ``services.exports.render_pursuits_export``: un solo sitio decide con qué
    organización se lee el pipeline (``tests/test_organization_sql_isolation.py``).
    Mismos filtros que el tablero, para que el CRM reciba lo que se está viendo.
    """
    from db.repositories.pursuits import PursuitRepository
    from services.organizations import alcance_resuelto

    with alcance_resuelto(user_id, organization_id) as (organizacion, _rol):
        filas = PursuitRepository().export_rows(
            organizacion,
            status=status,
            responsible_user_id=responsible_user_id,
            limit=limit,
        )
    return csv_crm(filas), len(filas)
