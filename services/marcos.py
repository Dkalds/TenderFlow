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
from typing import Literal, TypedDict, cast

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


def _clave(fila: FilaAdmitido, nif_de_empresa: dict[int, str]) -> str:
    """Qué hace de dos filas la misma empresa: el NIF, la empresa del maestro o el nombre.

    ``nif_de_empresa`` une las filas de una empresa del maestro que la fuente
    publicó unas veces con NIF y otras sin él: sin eso saldría dos veces.
    """
    empresa_id = fila["empresa_id"]
    nif = normalize_nif(fila["nif"]) or (
        nif_de_empresa.get(empresa_id) if empresa_id is not None else None
    )
    if nif:
        return f"nif:{nif}"
    if empresa_id is not None:
        return f"empresa:{empresa_id}"
    return f"nombre:{fold_text(fila['nombre'])}"


def agrupar_admitidos(
    filas: Sequence[FilaAdmitido], identidad: IdentidadFiscal
) -> tuple[list[AdmitidoMarco], bool | None]:
    """Las empresas admitidas y si la organización está entre ellas.

    El segundo valor es ``None`` cuando no se puede afirmar: la organización no
    ha declarado NIF, no hay admitidos publicados, o no coincide con ninguno
    pero alguno llegó sin NIF ni empresa resuelta —podría ser ella—.
    """
    nif_de_empresa = {
        f["empresa_id"]: nif
        for f in filas
        if f["empresa_id"] is not None and (nif := normalize_nif(f["nif"]))
    }
    grupos: dict[str, list[FilaAdmitido]] = {}
    for fila in filas:
        grupos.setdefault(_clave(fila, nif_de_empresa), []).append(fila)

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


class _Duracion(TypedDict):
    duracion_valor: float | None
    duracion_unidad: Literal["ANN", "MON", "DAY"] | None


def _duracion(marco: FilaExpedienteMarco) -> _Duracion:
    """La duración publicada, solo si es positiva y en una unidad de CODICE."""
    valor, unidad = marco["duracion_valor"], marco["duracion_unidad"]
    if valor is None or valor <= 0 or unidad not in ("ANN", "MON", "DAY"):
        return {"duracion_valor": None, "duracion_unidad": None}
    # cast: la comprobación de arriba deja solo los tres valores del Literal.
    return {
        "duracion_valor": valor,
        "duracion_unidad": cast("Literal['ANN', 'MON', 'DAY']", unidad),
    }


class _DelMarco(TypedDict):
    """Los campos de la respuesta que salen del marco, sea el expediente o el de un basado."""

    admitidos_total: int
    admitidos: list[AdmitidoMarco]
    organizacion_admitida: bool | None
    vigencia: VigenciaMarco


def _admitidos_y_vigencia(marco: FilaExpedienteMarco, identidad: IdentidadFiscal) -> _DelMarco:
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
            **_duracion(marco),
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
    enlazado = MarcoEnlazado(
        licitacion_id=marco["id_externo"],
        titulo=marco["titulo"],
        organo_contratacion=marco["organo_contratacion"],
        sistema=_sistema(marco),
    )
    if enlazado.sistema not in MARCOS:
        # La fila citada no consta como marco: se recogió antes de v178, cuando
        # de un aviso de TED solo se guardaba el primer adjudicatario. Contar
        # los suyos sería dar por admitidos a los que haya; se enlaza y nada más.
        return base.model_copy(update={"marco": enlazado})
    return base.model_copy(update={"marco": enlazado, **_admitidos_y_vigencia(marco, identidad)})
