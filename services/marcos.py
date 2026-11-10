"""Un acuerdo marco o un SDA leído como entidad: admitidos, vigencia y basados.

Los admitidos de un marco son sus adjudicatarios, agrupados por empresa: la
fuente publica una fila por adjudicatario y lote, y «compiten doce» cuenta
empresas, no filas. La identidad de la organización que mira es la de
:func:`services.pursuit_awards.identidad_fiscal`, la misma del historial propio
y de la competencia esperada.

Un contrato basado hereda los admitidos y la vigencia de su marco solo si la
fuente publica cuál es (``licitaciones.marco_ref``) y ese marco está en el
producto. Medido el 2026-11-10: TED lo publica; PLACSP no, y PSCP lo publica
donde el conector aún no lee. Ahí el basado dice que lo es y deja lo demás sin
dato: no se deduce del título.
"""

from __future__ import annotations

from collections.abc import Sequence
from typing import Any, cast

from db.repositories import marcos as repo
from db.repositories.marcos import FilaAdmitido, FilaExpedienteMarco
from services.normalization import fold_text, normalize_nif
from services.pursuit_awards import IdentidadFiscal, identidad_fiscal
from shared.dto.marcos import (
    AdmitidoMarco,
    ContratoBasado,
    MarcoDeLicitacion,
    MarcoEnlazado,
    OrigenFechaFin,
    VigenciaMarco,
)
from shared.sistema_contratacion import BASADOS, MARCOS, SISTEMAS, SistemaContratacion

#: Tope de admitidos en la respuesta. Un SDA puede admitir a cientos; el total
#: viaja aparte y la organización que mira va siempre la primera.
MAX_ADMITIDOS = 100
#: Tope de contratos basados en la respuesta; el total viaja aparte.
MAX_BASADOS = 20


def _clave(fila: FilaAdmitido) -> str:
    """Qué hace de dos filas la misma empresa: el NIF, la empresa del maestro o el nombre."""
    nif = normalize_nif(fila["nif"])
    if nif:
        return f"nif:{nif}"
    if fila["empresa_id"] is not None:
        return f"empresa:{fila['empresa_id']}"
    return f"nombre:{fold_text(fila['nombre'])}"


def agrupar_admitidos(
    filas: Sequence[FilaAdmitido], identidad: IdentidadFiscal
) -> tuple[list[AdmitidoMarco], bool | None]:
    """Las empresas admitidas y si la organización está entre ellas.

    El segundo valor es ``None`` cuando no se puede afirmar: la organización no
    ha declarado NIF, no hay admitidos publicados, o no coincide con ninguno
    pero alguno llegó sin NIF ni empresa resuelta —podría ser ella—.
    """
    grupos: dict[str, list[FilaAdmitido]] = {}
    for fila in filas:
        grupos.setdefault(_clave(fila), []).append(fila)

    admitidos: list[AdmitidoMarco] = []
    sin_identificar = False
    for grupo in grupos.values():
        nifs = [f["nif"] for f in grupo]
        empresa_ids = [f["empresa_id"] for f in grupo]
        sin_identificar = sin_identificar or not (
            any(nifs) or any(e is not None for e in empresa_ids)
        )
        admitidos.append(
            AdmitidoMarco(
                nombre=grupo[0]["nombre"],
                nif=next((n for n in nifs if n), None),
                lotes=sorted({f["lote_numero"] for f in grupo if f["lote_numero"]}),
                es_tu_organizacion=identidad.reconoce(nifs=nifs, empresa_ids=empresa_ids),
            )
        )
    admitidos.sort(key=lambda a: (not a.es_tu_organizacion, fold_text(a.nombre)))

    if not identidad.conocida or not admitidos:
        return admitidos, None
    if admitidos[0].es_tu_organizacion:
        return admitidos, True
    return admitidos, None if sin_identificar else False


def _sistema(fila: FilaExpedienteMarco) -> SistemaContratacion | None:
    valor = fila["sistema_contratacion"]
    # cast: el CHECK de v178 solo admite los valores del Literal.
    return cast("SistemaContratacion", valor) if valor in SISTEMAS else None


def _admitidos_y_vigencia(marco: FilaExpedienteMarco, identidad: IdentidadFiscal) -> dict[str, Any]:
    """Los campos de la respuesta que salen del marco, sea el expediente o el de un basado."""
    admitidos, organizacion_admitida = agrupar_admitidos(
        repo.admitidos(marco["id_externo"]), identidad
    )
    return {
        "admitidos_total": len(admitidos),
        "admitidos": admitidos[:MAX_ADMITIDOS],
        "organizacion_admitida": organizacion_admitida,
        "vigencia": VigenciaMarco(
            fecha_fin=marco["fecha_fin"],
            # cast: las cuatro ramas de `FECHA_FIN_ORIGEN_SQL`.
            origen=cast("OrigenFechaFin", marco["fecha_fin_origen"]),
            dias_restantes=marco["dias_restantes"],
        ),
    }


def referencia_legible(marco_ref: str) -> str:
    """``ted:649072-2024`` → «TED 649072-2024»: lo que se puede buscar en la fuente."""
    fuente, _, numero = marco_ref.partition(":")
    return f"{fuente.upper()} {numero}" if numero else marco_ref


def marco_de_licitacion(id_externo: str, *, organization_id: int) -> MarcoDeLicitacion | None:
    """El marco de un expediente para ``organization_id``; ``None`` si el expediente no existe.

    ``organization_id`` llega ya resuelto por la ruta (``require_organization``).
    """
    fila = repo.expediente(id_externo)
    if fila is None:
        return None
    sistema = _sistema(fila)
    identidad = identidad_fiscal(organization_id)
    base = MarcoDeLicitacion(
        licitacion_id=id_externo, sistema=sistema, identidad_conocida=identidad.conocida
    )

    if sistema in MARCOS:
        basados = repo.basados(id_externo, limite=MAX_BASADOS)
        return base.model_copy(
            update={
                **_admitidos_y_vigencia(fila, identidad),
                # Ninguno no es cero: no se distingue de «su fuente no enlaza».
                "basados_total": int(basados[0]["total"]) if basados else None,
                "basados": [
                    ContratoBasado(
                        licitacion_id=b["id_externo"],
                        titulo=b["titulo"],
                        organo_contratacion=b["organo_contratacion"],
                        estado=b["estado"],
                        importe=b["importe"],
                        fecha_publicacion=b["fecha_publicacion"],
                    )
                    for b in basados
                ],
            }
        )

    marco_ref = fila["marco_ref"] if sistema in BASADOS else None
    if not marco_ref:
        return base
    marco = repo.expediente(marco_ref)
    if marco is None:
        return base.model_copy(update={"marco_referencia": referencia_legible(marco_ref)})
    return base.model_copy(
        update={
            "marco": MarcoEnlazado(
                licitacion_id=marco["id_externo"],
                titulo=marco["titulo"],
                organo_contratacion=marco["organo_contratacion"],
                sistema=_sistema(marco),
            ),
            **_admitidos_y_vigencia(marco, identidad),
        }
    )
