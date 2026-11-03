"""Condiciones oficiales de PLACSP de un expediente, agrupadas por ámbito (v148).

Lo que el anuncio CODICE publica en ``cac:TenderingTerms`` —criterios de
adjudicación, garantías y solvencia— lo guarda la ingesta en tres tablas
(``db/upsert.py``). Este módulo lo compone para servirlo: un ámbito por
expediente y por lote, con el título del lote y la procedencia declarada.

Es la **fuente primaria** de esos datos. La ficha LLM del pliego
(``services/rag/fact_sheet.py``) los complementa o los cubre cuando faltan,
pero no se mezclan: cada pantalla y cada regla dice de cuál de las dos sale lo
que enseña. Los indicios (:func:`indicios_de`) salen solo de aquí.
"""

from __future__ import annotations

import re
from collections.abc import Mapping
from typing import Any

from db.repositories.condiciones_oficiales import CondicionesOficialesRepository
from shared.dto import (
    CondicionesAmbito,
    CondicionesOficiales,
    CriterioOficial,
    GarantiaOficial,
    IndicioPliego,
    RequisitoSolvenciaOficial,
)

_repo = CondicionesOficialesRepository()


def _clave_lote(lote_numero: str | None) -> tuple[int, int, str]:
    """Expediente primero; los lotes numéricos por número ("2" antes que "10")."""
    if lote_numero is None:
        return (0, 0, "")
    if lote_numero.isdigit():
        return (1, int(lote_numero), "")
    return (2, 0, lote_numero)


#: `tipo_codigo` de CODICE para «volumen anual de negocios» en la solvencia
#: económica; los demás (seguro, ratios, patrimonio) no tienen el tope del 87.1.a.
_VOLUMEN_NEGOCIOS = "5"
_TOPE_VOLUMEN = 1.5
_NORMAS_CERTIFICADO = (
    (re.compile(r"\b9001\b"), "ISO 9001", "Art. 93.1 LCSP"),
    (re.compile(r"\b14001\b|\bEMAS\b"), "ISO 14001 o EMAS", "Art. 94.1 LCSP"),
)
#: «equivalente» en castellano y gallego, «equivalent» en catalán, «baliokide» en euskera.
_EQUIVALENTE = re.compile(r"equivalen|baliokide", re.IGNORECASE)
_CITA_MAX = 280


def _eur(valor: float) -> str:
    return f"{valor:,.0f} €".replace(",", ".")


def _veces(valor: float) -> str:
    return f"{valor:.1f}".replace(".", ",") + " veces"


def _pct(valor: float) -> str:
    return f"{valor:.0f} %"


def _cita(texto: str | None) -> str | None:
    if not texto:
        return None
    limpio = " ".join(texto.split()).lstrip("-• ").strip()
    return limpio if len(limpio) <= _CITA_MAX else limpio[: _CITA_MAX - 1].rstrip() + "…"


def _indicio_volumen(
    lote: str | None, requisito: RequisitoSolvenciaOficial, valor_estimado: float | None
) -> IndicioPliego | None:
    umbral = requisito.umbral_importe
    if requisito.clase != "economica" or requisito.tipo_codigo != _VOLUMEN_NEGOCIOS:
        return None
    if (
        not umbral
        or not valor_estimado
        or valor_estimado <= 0
        or requisito.moneda not in (None, "EUR")
    ):
        return None
    veces = umbral / valor_estimado
    if veces <= _TOPE_VOLUMEN:
        return None
    # Se compara con el valor estimado de todo el contrato aunque el requisito
    # sea de un lote: el del lote es menor, así que el indicio nunca sobra.
    return IndicioPliego(
        codigo="solvencia_economica_excesiva",
        lote_numero=lote,
        titulo="Volumen de negocios por encima del tope legal",
        detalle=(
            f"Pide {_eur(umbral)} de volumen anual de negocios, "
            f"{_veces(veces)} el valor estimado del contrato ({_eur(valor_estimado)})."
        ),
        base_legal=(
            "Art. 87.1.a) LCSP: el volumen exigido no excederá de una vez y media el valor "
            "estimado, salvo casos debidamente justificados en el expediente."
        ),
        cita=_cita(requisito.descripcion),
    )


def _indicio_juicio_de_valor(ambito: CondicionesAmbito) -> IndicioPliego | None:
    """Los criterios raíz suman ~100 y el juicio de valor pasa de la mitad.

    Solo con la escala deducible (`peso_pct`) y sobre los criterios raíz: los
    subcriterios ya están dentro del peso de su padre.
    """
    raiz = [c for c in ambito.criterios if c.padre_orden is None and c.peso_pct is not None]
    total = sum(c.peso_pct or 0.0 for c in raiz)
    subj = sum(c.peso_pct or 0.0 for c in raiz if c.tipo_codigo == "SUBJ")
    obj = sum(c.peso_pct or 0.0 for c in raiz if c.tipo_codigo == "OBJ")
    if not (95 <= total <= 105 and subj > 50):
        return None
    return IndicioPliego(
        codigo="juicio_de_valor_mayoritario",
        lote_numero=ambito.lote_numero,
        titulo="Más de la mitad de los puntos, por juicio de valor",
        detalle=(
            f"El {_pct(subj)} de la puntuación depende de un juicio de valor y el "
            f"{_pct(obj)} se calcula con fórmulas: la memoria técnica pesa más que el precio."
        ),
        base_legal=(
            "Art. 146.2.a) LCSP: cuando los criterios de juicio de valor pesan más que los "
            "automáticos, los valora un comité de expertos ajeno al órgano que propone el contrato."
        ),
    )


def _indicios_certificado(ambito: CondicionesAmbito) -> list[IndicioPliego]:
    """Uno por norma cuando la publicación no menciona equivalentes."""
    vistas: set[str] = set()
    indicios: list[IndicioPliego] = []
    for requisito in ambito.solvencia:
        texto = requisito.descripcion or ""
        if requisito.clase != "tecnica" or _EQUIVALENTE.search(texto):
            continue
        for patron, norma, articulo in _NORMAS_CERTIFICADO:
            if norma in vistas or not patron.search(texto):
                continue
            vistas.add(norma)
            indicios.append(
                IndicioPliego(
                    codigo="certificado_sin_equivalente",
                    lote_numero=ambito.lote_numero,
                    titulo=f"{norma} sin mencionar equivalentes",
                    detalle=(
                        f"Pide {norma} y la publicación no dice que acepte certificados "
                        "equivalentes. Compruébalo en el pliego antes de dar el requisito por perdido."
                    ),
                    base_legal=(
                        f"{articulo}: el órgano debe reconocer los certificados equivalentes "
                        "y otras pruebas de medidas equivalentes."
                    ),
                    cita=_cita(texto),
                )
            )
    return indicios


def indicios_de(
    ambitos: list[CondicionesAmbito], valor_estimado: float | None
) -> list[IndicioPliego]:
    """Las condiciones publicadas que conviene revisar. Pura: ni lee ni escribe BD.

    Tres reglas, todas sobre la publicación oficial y con su artículo: el
    volumen de negocios por encima de 1,5 veces el valor estimado, el juicio de
    valor por encima de la mitad de los puntos y un certificado de calidad o
    ambiental sin mención de equivalentes. Un plazo corto no entra: restar
    ``fecha_publicacion`` de ``fecha_limite`` da plazos negativos en más del
    10 % de los abiertos TI (medido el 2026-11-03), así que la cifra no sostiene
    un aviso.
    """
    volumen = [
        indicio
        for ambito in ambitos
        for requisito in ambito.solvencia
        if (indicio := _indicio_volumen(ambito.lote_numero, requisito, valor_estimado)) is not None
    ]
    juicio = [i for ambito in ambitos if (i := _indicio_juicio_de_valor(ambito)) is not None]
    certificados = [i for ambito in ambitos for i in _indicios_certificado(ambito)]
    return [*volumen, *juicio, *certificados]


def construir_condiciones(licitacion_id: str, datos: Mapping[str, Any]) -> CondicionesOficiales:
    """Agrupa las filas del repositorio por ámbito. Pura: ni lee ni escribe BD.

    ``datos`` es lo que devuelve ``CondicionesOficialesRepository.get``. Solo
    aparecen los ámbitos con alguna fila: un lote sin condiciones publicadas no
    sale vacío, porque «sin condiciones» ya lo dice su ausencia.
    """
    titulos: Mapping[str, str | None] = datos.get("lotes") or {}
    ambitos: dict[str | None, CondicionesAmbito] = {}

    def ambito(lote_numero: str | None) -> CondicionesAmbito:
        if lote_numero not in ambitos:
            ambitos[lote_numero] = CondicionesAmbito(
                lote_numero=lote_numero,
                lote_titulo=titulos.get(lote_numero) if lote_numero is not None else None,
            )
        return ambitos[lote_numero]

    def campos(fila: Mapping[str, Any], modelo: type[Any]) -> dict[str, Any]:
        return {k: v for k, v in fila.items() if k in modelo.model_fields}

    for fila in datos.get("criterios") or []:
        ambito(fila.get("lote_numero")).criterios.append(
            CriterioOficial.model_validate(campos(fila, CriterioOficial))
        )
    for fila in datos.get("garantias") or []:
        ambito(fila.get("lote_numero")).garantias.append(
            GarantiaOficial.model_validate(campos(fila, GarantiaOficial))
        )
    for fila in datos.get("solvencia") or []:
        ambito(fila.get("lote_numero")).solvencia.append(
            RequisitoSolvenciaOficial.model_validate(campos(fila, RequisitoSolvenciaOficial))
        )

    ordenados = [ambitos[clave] for clave in sorted(ambitos, key=_clave_lote)]
    valor_estimado = datos.get("valor_estimado")
    return CondicionesOficiales(
        licitacion_id=licitacion_id,
        url_publicacion=datos.get("url"),
        actualizado=datos.get("actualizado"),
        ambitos=ordenados,
        valor_estimado=valor_estimado,
        indicios=indicios_de(ordenados, valor_estimado),
    )


def condiciones_oficiales(licitacion_id: str) -> CondicionesOficiales | None:
    """Las condiciones oficiales de un expediente, o ``None`` si no existe.

    Una republicación confirmada no tiene anuncio CODICE propio —TED reenvía un
    expediente que el órgano publicó en PLACSP—, así que se leen las del
    original (``services.dedupe.expediente_del_pliego``, la misma regla que la
    ficha del pliego) y el ``licitacion_id`` de la respuesta lo dice.
    """
    from services.dedupe import expediente_del_pliego

    original = expediente_del_pliego(licitacion_id)
    datos = _repo.get(original)
    if not datos["existe"] and original != licitacion_id:
        original = licitacion_id
        datos = _repo.get(licitacion_id)
    if not datos["existe"]:
        return None
    return construir_condiciones(original, datos)
