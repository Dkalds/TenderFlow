"""F2.6 — el esqueleto de la oferta técnica, criterio a criterio (D33).

D33 lo decidió y esta implementación lo respeta: **sólo esquema de puntos con
citas al pliego, nunca prosa**. Un producto que vende confianza en el dato no
puede ofrecer párrafos que parezcan escritos por el equipo y no lo estén, y
quien recibe una memoria técnica generada la copia sin leerla — que es la peor
forma de perder un contrato.

Lo que sí resuelve
------------------
La página en blanco. Delante de un pliego con nueve criterios, saber **qué hay
que cubrir en cada uno y dónde lo dice el pliego** es la mitad del trabajo, y
es exactamente lo que hoy se hace a mano subrayando el PDF.

La regla que hace esto publicable
---------------------------------
Cada punto lleva al menos una cita **verificable** —existe en
``documento_pages``— y un punto sin cita se marca ``sin base en el pliego``.
No se descarta: que el modelo proponga algo que el pliego no pide es
información útil (a veces es una buena idea), pero tiene que verse que es una
propuesta y no una exigencia.

El contrato de forma
--------------------
:func:`validar_esquema` rechaza los párrafos: ningún punto puede tener más de
dos frases. Es lo que convierte «solo esquema» de una instrucción al modelo
—que a veces se ignora— en una propiedad comprobable de la respuesta.
"""

from __future__ import annotations

import re
from typing import Any

from pydantic import BaseModel, ConfigDict, Field

from observability.logging import get_logger
from shared.tender_facts import EvidenceRef

log = get_logger(__name__)

__all__ = [
    "MAX_FRASES_POR_PUNTO",
    "GuionCriterio",
    "GuionOferta",
    "PuntoGuion",
    "contar_frases",
    "generar_guion",
    "marcar_sin_base",
    "validar_esquema",
]

#: Tope de frases por punto. Dos es un punto con matiz; tres ya es prosa, y
#: prosa es lo que D33 dice que no.
MAX_FRASES_POR_PUNTO = 2

#: Marca de un punto que el pliego no respalda. Es un valor y no un texto
#: suelto porque la UI lo pinta distinto y el test lo comprueba.
SIN_BASE = "sin base en el pliego"

_FIN_DE_FRASE = re.compile(r"[.!?]+(?:\s|$)")


def contar_frases(texto: str) -> int:
    """Frases de un texto, contando por puntuación terminal.

    Aproximado a propósito: un contador exacto necesitaría un tokenizador y la
    diferencia entre «dos frases» y «dos frases y una abreviatura» no cambia
    la decisión. Lo que importa es distinguir un punto de un párrafo, y para
    eso esto basta.
    """
    limpio = texto.strip()
    if not limpio:
        return 0
    frases = [f for f in _FIN_DE_FRASE.split(limpio) if f.strip()]
    return max(1, len(frases))


class PuntoGuion(BaseModel):
    """Un punto a cubrir dentro de un criterio."""

    model_config = ConfigDict(extra="forbid")

    texto: str = Field(min_length=1, max_length=400)
    #: Al menos una cita, salvo que el punto se marque `sin_base`.
    evidencia: list[EvidenceRef] = Field(default_factory=list, max_length=4)
    #: `True` cuando el punto no tiene respaldo en el pliego. No se descarta:
    #: puede ser una buena idea, pero tiene que verse que es una propuesta.
    sin_base: bool = False


class GuionCriterio(BaseModel):
    """Los puntos de un criterio de adjudicación."""

    model_config = ConfigDict(extra="forbid")

    criterio: str
    peso_pct: float | None = Field(default=None, ge=0, le=100)
    puntos: list[PuntoGuion] = Field(default_factory=list)


class GuionOferta(BaseModel):
    """El guion completo."""

    model_config = ConfigDict(extra="forbid")

    licitacion_id: str
    criterios: list[GuionCriterio] = Field(default_factory=list)
    #: Firma de la ficha y los documentos con la que se generó. Es la clave de
    #: caché: mientras no cambien, el guion es el mismo y no se vuelve a
    #: gastar presupuesto de LLM.
    firma: str | None = None
    #: Por qué no hay guion, cuando no lo hay.
    sin_guion: str | None = None


def validar_esquema(guion: GuionOferta) -> list[str]:
    """Los puntos que incumplen el contrato de forma. Vacío = correcto.

    Devuelve los textos infractores en vez de lanzar: el llamante decide si
    recorta, reintenta o rechaza, y el test de contrato afirma sobre la lista.
    Lanzar aquí obligaría a atrapar la excepción para poder examinarla.
    """
    return [
        punto.texto
        for criterio in guion.criterios
        for punto in criterio.puntos
        if contar_frases(punto.texto) > MAX_FRASES_POR_PUNTO
    ]


def marcar_sin_base(guion: GuionOferta, paginas_validas: set[tuple[int, int]]) -> GuionOferta:
    """Marca ``sin_base`` los puntos cuya cita no existe de verdad.

    ``paginas_validas`` son los pares ``(documento_id, page_number)`` que
    ``documento_pages`` tiene para este expediente. Una cita a una página que
    no existe **no** es una cita: es una alucinación con formato de cita, que
    es peor que no citar porque parece verificada.

    Devuelve un guion nuevo en vez de mutar el recibido: el original es lo que
    devolvió el modelo, y conservarlo intacto es lo que permite comparar
    después qué se marcó y por qué.
    """
    criterios: list[GuionCriterio] = []
    for criterio in guion.criterios:
        puntos: list[PuntoGuion] = []
        for punto in criterio.puntos:
            validas = [
                cita
                for cita in punto.evidencia
                if (cita.documento_id, cita.page_number) in paginas_validas
            ]
            puntos.append(
                PuntoGuion(
                    texto=punto.texto,
                    evidencia=validas,
                    sin_base=not validas,
                )
            )
        criterios.append(
            GuionCriterio(criterio=criterio.criterio, peso_pct=criterio.peso_pct, puntos=puntos)
        )
    return GuionOferta(
        licitacion_id=guion.licitacion_id,
        criterios=criterios,
        firma=guion.firma,
        sin_guion=guion.sin_guion,
    )


def a_markdown(guion: GuionOferta) -> str:
    """El guion en Markdown, para exportar.

    La cita se imprime como referencia al documento y la página, no como el
    texto citado: el texto ya está en el pliego, y repetirlo aquí convertiría
    un esquema de una página en un documento de veinte.
    """
    lineas: list[str] = [f"# Guion de la oferta técnica — {guion.licitacion_id}", ""]
    if guion.sin_guion:
        lineas.append(f"_{guion.sin_guion}_")
        return "\n".join(lineas)

    for criterio in guion.criterios:
        peso = f" ({criterio.peso_pct:g} puntos)" if criterio.peso_pct is not None else ""
        lineas.append(f"## {criterio.criterio}{peso}")
        lineas.append("")
        for punto in criterio.puntos:
            refs = ", ".join(f"doc {c.documento_id} p. {c.page_number}" for c in punto.evidencia)
            marca = f" _[{SIN_BASE}]_" if punto.sin_base else (f" _({refs})_" if refs else "")
            lineas.append(f"- {punto.texto}{marca}")
        lineas.append("")
    return "\n".join(lineas)


def firma_de(ficha: Any, documentos: list[Any]) -> str:
    """Firma de caché: cambia si cambia la ficha o los documentos.

    Se usa el hash de la representación estable de las dos cosas. Con la misma
    firma, el guion no se regenera — que es lo que impide que abrir la pestaña
    tres veces cueste tres llamadas al LLM.
    """
    import hashlib

    partes = [
        str(getattr(ficha, "model_dump_json", lambda: "")()),
        *sorted(str(getattr(d, "id", d)) for d in documentos),
    ]
    return hashlib.sha256("|".join(partes).encode("utf-8")).hexdigest()[:32]


# ── Generación ──────────────────────────────────────────────────────────────
#
# La forma de la respuesta la impone el prompt **y** la comprueba
# `validar_esquema` después. Las dos cosas: pedirle al modelo que no escriba
# prosa funciona casi siempre, y «casi siempre» no es un contrato.

_PREGUNTA = (
    "Para cada criterio de adjudicación del pliego, enumera los PUNTOS que la "
    "oferta técnica debe cubrir. Devuelve SOLO un objeto JSON con esta forma: "
    "{criterios: [{criterio, peso_pct, puntos: [{texto, evidencia: "
    "[{documento_id, page_number, quote}]}]}]}.\n\n"
    "REGLAS ESTRICTAS:\n"
    "1. Cada `texto` es un PUNTO, no un párrafo: como mucho DOS frases. No "
    "redactes la oferta, enumera qué hay que cubrir.\n"
    "2. Cada punto lleva al menos una cita con el documento y la página donde "
    "el pliego lo exige. Si propones algo que el pliego no pide, deja la "
    "evidencia vacía — no inventes una página.\n"
    "3. No repitas el criterio dentro de sus propios puntos.\n"
    "4. Si el pliego no publica criterios de adjudicación, devuelve una lista "
    "de criterios vacía."
)


def generar_guion(
    licitacion_id: str,
    *,
    model: str | None = None,
    max_criterios: int = 12,
) -> GuionOferta:
    """Genera el guion y lo devuelve **ya validado**.

    Tres capas, y ninguna sobra:

    1. El prompt pide puntos, no prosa.
    2. :func:`marcar_sin_base` cruza cada cita con las páginas reales.
    3. :func:`validar_esquema` recorta los puntos que aun así salieron largos.

    La tercera no es paranoia: un modelo que devuelve un párrafo cuando se le
    piden puntos es el caso normal, no el excepcional, y D33 no dice «pídele
    que no lo haga» sino «no ofrezcas prosa».

    El presupuesto lo aplica el ``BudgetGuard`` del proceso, que la ruta ata al
    sujeto con ``bind_budget_subject`` como hace la ficha. El tope por guion
    sale de ``LLM_GUION_MAX_TOKENS``.
    """
    from config import settings
    from db.repositories.documentos import DocumentosRepository
    from llm.client import DEFAULT_MODEL, stream_llm_response
    from llm.json_utils import extract_json_object
    from services.rag.fact_sheet import get_fact_sheet

    record = get_fact_sheet(licitacion_id)
    criterios_ficha = list(record.facts.award_criteria) if record and record.facts else []
    if not criterios_ficha:
        # Sin criterios extraídos no hay guion que estructurar. Se dice, en vez
        # de pedirle al modelo que se los invente — que es exactamente el tipo
        # de contenido que D33 descarta.
        return GuionOferta(
            licitacion_id=licitacion_id,
            sin_guion=(
                "El pliego no publica criterios de adjudicación ponderados, o todavía no "
                "se han extraído. Sin ellos no hay guion que estructurar."
            ),
        )

    paginas = DocumentosRepository().list_pages_by_licitacion(licitacion_id)
    validas = {(int(p["documento_id"]), int(p["page_number"])) for p in paginas}
    if not validas:
        return GuionOferta(
            licitacion_id=licitacion_id,
            sin_guion="Todavía no hay texto extraído de los pliegos de este expediente.",
        )

    docs = [
        {
            "id_externo": licitacion_id,
            "titulo": "Guion de la oferta técnica",
            "descripcion": "",
            "chunks": [
                {
                    "documento_id": int(p["documento_id"]),
                    "page_number": int(p["page_number"]),
                    "tipo": p.get("tipo"),
                    "filename": p.get("filename"),
                    "texto": p.get("texto") or "",
                }
                for p in paginas
            ],
        }
    ]

    try:
        crudo = "".join(
            stream_llm_response(
                question=_PREGUNTA,
                docs=docs,
                model=model or DEFAULT_MODEL,
                # Sin keywords: el guion se estructura sobre los criterios que
                # la ficha ya extrajo, no sobre términos que haya que buscar.
                keywords=[],
                mode="extraction",
                max_tokens=int(getattr(settings, "LLM_GUION_MAX_TOKENS", 2500)),
                # Sin fallback de proveedor, como la ficha: un cambio silencioso
                # de modelo haría mentir a la firma de caché sobre quién generó
                # este guion.
                fallback=False,
            )
        )
        datos = extract_json_object(crudo)
    except Exception as exc:
        log.warning("guion_generacion_fallida", licitacion_id=licitacion_id, error=str(exc)[:200])
        return GuionOferta(
            licitacion_id=licitacion_id,
            sin_guion="No se pudo generar el guion. Vuelve a intentarlo en unos minutos.",
        )

    criterios: list[GuionCriterio] = []
    for bruto in (datos.get("criterios") or [])[:max_criterios]:
        if not isinstance(bruto, dict):
            continue
        puntos: list[PuntoGuion] = []
        for punto in (bruto.get("puntos") or [])[:20]:
            if not isinstance(punto, dict):
                continue
            texto = str(punto.get("texto") or "").strip()
            if not texto:
                continue
            citas: list[EvidenceRef] = []
            for cita in (punto.get("evidencia") or [])[:4]:
                try:
                    citas.append(EvidenceRef(**cita))
                except Exception as exc:
                    # Una cita malformada se descarta; el punto sobrevive y
                    # `marcar_sin_base` lo etiquetará si se queda sin ninguna.
                    # Se registra porque una racha de citas malformadas es una
                    # señal sobre el modelo, no sobre el pliego.
                    log.debug("guion_cita_invalida", error=str(exc)[:120])
            puntos.append(PuntoGuion(texto=texto[:400], evidencia=citas))
        if puntos:
            peso = bruto.get("peso_pct")
            criterios.append(
                GuionCriterio(
                    criterio=str(bruto.get("criterio") or "Criterio")[:300],
                    peso_pct=float(peso) if isinstance(peso, (int, float)) else None,
                    puntos=puntos,
                )
            )

    guion = marcar_sin_base(
        GuionOferta(
            licitacion_id=licitacion_id,
            criterios=criterios,
            firma=firma_de(record.facts if record else None, paginas),
        ),
        validas,
    )

    infractores = validar_esquema(guion)
    if infractores:
        # Se recorta a las dos primeras frases en vez de rechazar el guion
        # entero: el resto de los puntos son útiles, y un guion que falla
        # porque uno de doce salió largo no lo usaría nadie.
        log.info("guion_puntos_recortados", licitacion_id=licitacion_id, n=len(infractores))
        guion = _recortar(guion)
    return guion


def _recortar(guion: GuionOferta) -> GuionOferta:
    """Deja cada punto en sus dos primeras frases."""
    criterios = [
        GuionCriterio(
            criterio=c.criterio,
            peso_pct=c.peso_pct,
            puntos=[
                PuntoGuion(texto=_dos_frases(p.texto), evidencia=p.evidencia, sin_base=p.sin_base)
                for p in c.puntos
            ],
        )
        for c in guion.criterios
    ]
    return GuionOferta(
        licitacion_id=guion.licitacion_id,
        criterios=criterios,
        firma=guion.firma,
        sin_guion=guion.sin_guion,
    )


def _dos_frases(texto: str) -> str:
    """Las dos primeras frases del texto, con su puntuación."""
    partes = _FIN_DE_FRASE.split(texto.strip())
    utiles = [p.strip() for p in partes if p.strip()][:MAX_FRASES_POR_PUNTO]
    if not utiles:
        return texto.strip()[:400]
    return ". ".join(utiles).rstrip(".") + "."
