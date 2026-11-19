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
from collections.abc import Mapping, Sequence
from datetime import date, timedelta
from typing import Any

from db.repositories.condiciones_oficiales import CondicionesOficialesRepository
from shared.dto import (
    CondicionesAmbito,
    CondicionesOficiales,
    CriterioOficial,
    GarantiaOficial,
    IndicioPliego,
    PlazoRecursoEspecial,
    RequisitoSolvenciaOficial,
)
from shared.procedimientos import codigo_tipo_contrato

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
VOLUMEN_NEGOCIOS = "5"
_TOPE_VOLUMEN = 1.5
#: Margen sobre el tope. Medido en producción el 2026-11-03: 16 de los 24
#: umbrales TI por encima de 1,5 eran exactamente 1,5 redondeado al céntimo
#: hacia arriba, y otros 2 (1,52 y 1,53) erratas del órgano, cuyo texto dice
#: «una vez y media». Por encima del 5 % quedan los que lo superan de verdad.
_MARGEN_VOLUMEN = 1.05
_NORMAS_CERTIFICADO = (
    (re.compile(r"\b9001\b"), "ISO 9001", "Art. 93.1 LCSP"),
    (re.compile(r"\b14001\b|\bEMAS\b"), "ISO 14001 o EMAS", "Art. 94.1 LCSP"),
)
#: Lo que admite otros certificados: «equivalente» (castellano y gallego),
#: «equivalent» (catalán), «baliokide» (euskera) y «o similares» / «análogo»,
#: que los pliegos usan con el mismo sentido («antzeko» en euskera).
_EQUIVALENTE = re.compile(r"equivalen|baliokide|similar|an[aá]log|antzeko", re.IGNORECASE)
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
    if requisito.clase != "economica" or requisito.tipo_codigo != VOLUMEN_NEGOCIOS:
        return None
    if (
        not umbral
        or not valor_estimado
        or valor_estimado <= 0
        or requisito.moneda not in (None, "EUR")
    ):
        return None
    veces = umbral / valor_estimado
    if veces <= _TOPE_VOLUMEN * _MARGEN_VOLUMEN:
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
    subcriterios ya están dentro del peso de su padre. Exige además algún
    criterio automático: sin ninguno, ni siquiera el precio, lo publicado es un
    criterio de relleno («Según PPT y PCP», 100 % juicio de valor) y no el
    reparto real; eran 37 de los 160 ámbitos TI que saltaban (2026-11-03).
    """
    raiz = [c for c in ambito.criterios if c.padre_orden is None and c.peso_pct is not None]
    total = sum(c.peso_pct or 0.0 for c in raiz)
    subj = sum(c.peso_pct or 0.0 for c in raiz if c.tipo_codigo == "SUBJ")
    obj = sum(c.peso_pct or 0.0 for c in raiz if c.tipo_codigo == "OBJ")
    if not (95 <= total <= 105 and subj > 50 and obj > 0):
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


#: Umbral de valor estimado del recurso especial por tipo CODICE (art. 44.1.a
#: LCSP): suministros y servicios, más de 100.000 €; obras y concesiones, más de
#: 3 millones. Los demás tipos no se juzgan: su sujeción depende de quién
#: contrata, y eso la publicación no lo dice.
_UMBRAL_RECURSO = dict.fromkeys(("1", "2"), 100_000.0) | dict.fromkeys(("3", "22", "32"), 3e6)
_DIAS_RECURSO = 15
#: Navarra tiene su propia reclamación (Ley Foral 2/2018), con otro plazo.
#: shortcut: se mira el NUTS del lugar de ejecución, no quién contrata; subirlo
#: si un órgano foral contrata fuera de Navarra o la AGE dentro.
_NUTS_NAVARRA = "ES22"
#: `NoticeTypeCode` del anuncio de licitación, desde el que corre el plazo, y
#: prefijo del anuncio previo, cuya fecha sería la que guarda `fecha_publicacion`.
_ANUNCIO_LICITACION = "DOC_CN"
_ANUNCIO_PREVIO = "DOC_PIN"
#: (mes, día): Año Nuevo, Reyes, Trabajo, Asunción, Hispanidad, Todos los Santos,
#: Constitución, Inmaculada y Navidad.
_FESTIVOS_NACIONALES = frozenset(
    {(1, 1), (1, 6), (5, 1), (8, 15), (10, 12), (11, 1), (12, 6), (12, 8), (12, 25)}
)


def _pascua(anio: int) -> date:
    """Domingo de Pascua (algoritmo anónimo gregoriano)."""
    a, b, c = anio % 19, anio // 100, anio % 100
    d, e = divmod(b, 4)
    g = (8 * b + 13) // 25
    h = (19 * a + b - d - g + 15) % 30
    i, k = divmod(c, 4)
    l_ = (32 + 2 * e + 2 * i - h - k) % 7
    m = (a + 11 * h + 22 * l_) // 451
    mes, dia = divmod(h + l_ - 7 * m + 114, 31)
    return date(anio, mes, dia + 1)


def _es_habil(dia: date) -> bool:
    """Sin sábados, domingos, festivos nacionales ni Viernes Santo.

    shortcut: sin festivos autonómicos ni locales (ni los que una comunidad
    traslada), así que la fecha puede no ser la real; subirlo si alguien pide
    la fecha exacta por comunidad.
    """
    return (
        dia.weekday() < 5
        and (dia.month, dia.day) not in _FESTIVOS_NACIONALES
        and dia != _pascua(dia.year) - timedelta(days=2)
    )


def sumar_dias_habiles(desde: date, dias: int) -> date:
    """El día hábil número ``dias`` contando desde el siguiente a ``desde``."""
    dia = desde
    while dias > 0:
        dia += timedelta(days=1)
        if _es_habil(dia):
            dias -= 1
    return dia


def plazo_recurso_especial(
    tipo_contrato: str | None,
    valor_estimado: float | None,
    fecha_publicacion: str | None,
    nuts_code: str | None,
    tipos_anuncio: str | None,
) -> PlazoRecursoEspecial | None:
    """Hasta cuándo se pueden recurrir los pliegos, o ``None`` si no se sabe.

    Solo con un tipo cuyo umbral es seguro (:data:`_UMBRAL_RECURSO`), un valor
    estimado que lo supera y una fecha de publicación legible. Fuera de Navarra,
    que tiene su propio régimen. Y solo si los anuncios publicados
    (``tipos_anuncio``, CSV de v138) incluyen el de licitación y ningún anuncio
    previo: ``fecha_publicacion`` es el primero de todos, y con un previo sería
    su fecha, meses antes; sin ``ValidNoticeInfo`` sería la de la última
    actualización. En los dos casos el plazo saldría mal, así que no se da.
    Pura: ni lee ni escribe BD.
    """
    umbral = _UMBRAL_RECURSO.get(codigo_tipo_contrato(tipo_contrato) or "")
    if umbral is None or not valor_estimado or valor_estimado <= umbral:
        return None
    if (nuts_code or "").upper().startswith(_NUTS_NAVARRA):
        return None
    anuncios = [a.strip() for a in (tipos_anuncio or "").split(",")]
    if _ANUNCIO_LICITACION not in anuncios or any(a.startswith(_ANUNCIO_PREVIO) for a in anuncios):
        return None
    try:
        publicada = date.fromisoformat(str(fecha_publicacion or "")[:10])
    except ValueError:
        return None
    return PlazoRecursoEspecial(
        vence=sumar_dias_habiles(publicada, _DIAS_RECURSO).isoformat(),
        desde=publicada.isoformat(),
        dias_habiles=_DIAS_RECURSO,
        base_legal=(
            "Art. 50.1.b) LCSP: 15 días hábiles desde el día siguiente a la publicación del "
            "anuncio, si los pliegos estaban accesibles ese día; recurso especial del art. 44, "
            "para contratos por encima de su umbral."
        ),
    )


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
        plazo_recurso=plazo_recurso_especial(
            datos.get("tipo_contrato"),
            valor_estimado,
            datos.get("fecha_publicacion"),
            datos.get("nuts_code"),
            datos.get("tipos_anuncio"),
        ),
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


def condiciones_oficiales_de(licitacion_ids: Sequence[str]) -> dict[str, CondicionesOficiales]:
    """:func:`condiciones_oficiales` de varios expedientes, en lecturas por lote.

    Misma regla que la de uno: las de la canónica confirmada si existe, si no
    las propias. Los ids que no existen no aparecen. Lo usan los recordatorios
    del plazo de recurso, que leían expediente a expediente.
    """
    from services.dedupe import expedientes_del_pliego

    ids = list(dict.fromkeys(licitacion_ids))
    originales = expedientes_del_pliego(ids)
    datos = _repo.get_varios([*ids, *originales.values()])
    resultado: dict[str, CondicionesOficiales] = {}
    for lic in ids:
        original = originales[lic] if datos[originales[lic]]["existe"] else lic
        if datos[original]["existe"]:
            resultado[lic] = construir_condiciones(original, datos[original])
    return resultado
