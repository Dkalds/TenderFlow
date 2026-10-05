"""Competencia esperada de un expediente: cuántos, quién lo tiene y contra quién.

El bloque «Competencia esperada» de la ficha pintaba los tres adjudicatarios
más frecuentes del **órgano entero** —de cualquier CPV y de cualquier año—, con
un porcentaje que dividía lo adjudicado a cada uno entre el presupuesto de
todas las licitaciones del órgano (abiertas y desiertas incluidas): ni era una
cuota ni respondía a la licitación abierta. Este módulo responde, sobre el
segmento del propio expediente, las tres preguntas que se vienen a hacer:

1. **¿Cuántos se presentarán?** (:class:`OfertasEsperadas`). La media de
   ofertas recibidas del CPV-4 es **la misma** que usa la dimensión
   ``competencia`` del score (mismo universo, misma ventana de
   :data:`VENTANA_COMPETENCIA_MESES`, misma definición por expediente): la
   barra del Radar y este bloque no pueden contradecirse. Si el órgano tiene
   muestra propia en ese CPV, se afina con ella.
2. **¿Quién lo tiene hoy?** (:class:`Incumbente`). El predecesor de C1.3
   —mismo órgano, mismo CPV-4, anterior y con objeto parecido—, que la API
   servía desde `/similares` sin que ninguna pantalla lo pidiera. Si no hay
   ninguno que pase el umbral, no se rellena con «el más parecido».
3. **¿Contra quién?** (:class:`RivalesEsperados`). Quién gana en el segmento
   más estrecho que tenga muestra (órgano y CPV-4; si no, CPV-4 y CCAA; si
   no, CPV-4), con su cuota **sobre lo adjudicado en ese mismo segmento**.

Y una cuarta, que alimenta el precio (:class:`PujaSegmento`): la baja mediana
del ganador y la de la oferta más baja en ese segmento. Es la referencia con la
que el Simulador mide al rival y la competencia con la que los Escenarios de
precio pueden acotar su cohorte.

Reglas
------
- **Cada sección declara su universo, su ventana y su ``n``** (ADR-014). Una
  cifra sin denominador no se publica, y una sección sin muestra dice por qué
  (``sin_datos``) en vez de llenarse.
- **La propia organización no es un rival.** Con su identidad fiscal (S2.1) se
  la saca de la lista y su parte se declara aparte (``propia``); la cuota de
  los demás no se recalcula sin ella: el mercado la incluye.
- **Sin P(ganar).** Igual que los escenarios de precio
  (``WinProbabilityGate``): nada de esto es una probabilidad de adjudicación.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field

from db.repositories import competencia_esperada as repo
from db.repositories.competencia_esperada import NivelSegmento, Segmento
from db.sql_fragments import BASE_MIXTA, plegar_organo
from observability.logging import get_logger
from services.analytics.scoring_signals import (
    VENTANA_COMPETENCIA_MESES,
    corte_ventana_competencia_iso,
    load_competencia_stats,
)
from services.ficha_pdf import BloqueFicha
from services.pursuit_awards import IdentidadFiscal, identidad_fiscal
from services.renovaciones_prorroga import sumar_meses
from services.similares import Candidato, Metodo, predecesor_de

log = get_logger(__name__)

__all__ = [
    "BandaOfertas",
    "CompetenciaEsperada",
    "CuotaPropia",
    "Incumbente",
    "OfertasEsperadas",
    "OfertasSegmento",
    "PujaSegmento",
    "Rival",
    "RivalesEsperados",
    "bloque_ficha",
    "competencia_esperada",
    "describir_nivel",
]

#: Ventana de rivales y puja. Más larga que la de ofertas a propósito: un
#: contrato de servicios dura dos o cuatro años, y con 24 meses el incumbente
#: de un contrato largo puede no aparecer entre quienes ganan en el segmento.
VENTANA_RIVALES_MESES = 36

#: Expedientes con el dato que hacen falta para dar la media de ofertas del
#: CPV-4. Es el ``HAVING COUNT(*) >= 3`` de la señal del score: por debajo, el
#: score tampoco usa la media del CPV.
MIN_EXPEDIENTES_CPV = 3

#: Para afinar con el órgano se pide más que para el CPV: es una afirmación más
#: concreta («en este órgano se presentan dos») sobre una muestra más pequeña.
MIN_EXPEDIENTES_ORGANO = 5

#: Expedientes adjudicados para que un nivel de segmento cuente como muestra
#: suficiente para rankear rivales. Con menos, el «líder» es quien ganó dos
#: contratos, y eso es una anécdota.
MIN_EXPEDIENTES_RIVALES = 5

#: Rivales que se devuelven: los que se leen en una columna lateral.
MAX_RIVALES = 5

#: Observaciones mínimas para publicar una mediana de bajas del segmento.
MIN_BAJAS = 3

NivelOfertas = Literal["organo_cpv4", "cpv4"]
NivelEstimacion = Literal["organo_cpv4", "cpv4", "global"]
NombreBanda = Literal["1", "2-4", "5+"]


class BandaOfertas(BaseModel):
    """Cuántos expedientes del segmento cayeron en cada banda de ofertas."""

    model_config = ConfigDict(extra="forbid")

    #: Las bandas de ``escenarios-precio?competencia_esperada``: 1, 2-4 y 5+.
    banda: NombreBanda
    expedientes: int = Field(ge=0)
    #: Sobre los expedientes con el dato, 0-100.
    pct: float = Field(ge=0, le=100)


class OfertasSegmento(BaseModel):
    """Ofertas recibidas en un nivel de segmento, con su ``n``."""

    model_config = ConfigDict(extra="forbid")

    nivel: NivelOfertas
    #: Media de ofertas por expediente (el máximo de sus lotes).
    media: float = Field(ge=0)
    #: Expedientes con el número de ofertas publicado: el ``n`` de la media.
    expedientes: int = Field(ge=1)
    #: Expedientes adjudicados en la ventana, publiquen o no el dato. Con
    #: ``expedientes`` da la cobertura: TED, por ejemplo, nunca lo publica.
    adjudicados: int = Field(ge=1)
    #: Expedientes con una sola oferta, 0-100.
    pct_oferta_unica: float = Field(ge=0, le=100)
    bandas: list[BandaOfertas] = Field(default_factory=list)


class OfertasEsperadas(BaseModel):
    """¿Cuántos se presentarán?"""

    model_config = ConfigDict(extra="forbid")

    ventana_meses: int = Field(ge=1)
    #: Ofertas esperadas, redondeadas, del nivel más concreto con muestra. Es la
    #: competencia que se puede pasar a ``escenarios-precio``. ``None`` sin dato.
    estimacion: int | None = Field(default=None, ge=1)
    estimacion_nivel: NivelEstimacion | None = None
    #: El órgano dentro del CPV-4, sólo con muestra suficiente.
    organo_cpv4: OfertasSegmento | None = None
    #: El CPV-4: la misma media que usa el score.
    cpv4: OfertasSegmento | None = None
    #: La media de todo el universo, que es lo que usa el score cuando el CPV-4
    #: no tiene muestra. Solo viene cuando hace falta como respaldo.
    media_global: float | None = Field(default=None, ge=0)
    #: Por qué no hay estimación, cuando no la hay.
    sin_datos: str | None = None


class Incumbente(BaseModel):
    """¿Quién lo tiene hoy? El adjudicatario del contrato anterior del mismo objeto."""

    model_config = ConfigDict(extra="forbid")

    licitacion_id: str
    titulo: str
    adjudicatario: str | None = None
    #: Para enlazar su dossier; ``None`` si el maestro no lo resolvió.
    empresa_id: int | None = None
    importe_adjudicado: float | None = None
    #: Baja del predecesor sobre su presupuesto, en %.
    baja_pct: float | None = None
    fecha_adjudicacion: str | None = None
    #: El contrato anterior lo ganó la propia organización.
    es_propia: bool = False
    #: Cómo se identificó: por parecido semántico o por términos comunes.
    metodo: Metodo


class Rival(BaseModel):
    """Una empresa que gana en el segmento."""

    model_config = ConfigDict(extra="forbid")

    nombre: str
    #: Para enlazar su dossier; ``None`` si el maestro no la resolvió. La clave
    #: de competidor con la que se agrupa (``db.sql_fragments.empresa_key_sql``)
    #: no se publica: sin ``empresa_id`` es el NIF, y el de un autónomo es un
    #: dato personal.
    empresa_id: int | None = None
    expedientes: int = Field(ge=1)
    importe_adjudicado: float = Field(ge=0)
    #: Sobre el importe adjudicado del segmento, 0-100.
    cuota_pct: float = Field(ge=0, le=100)
    #: Mediana de sus bajas en el segmento, en %, y sobre cuántas.
    baja_mediana_pct: float | None = None
    bajas_n: int = Field(default=0, ge=0)
    ultima_adjudicacion: str | None = None
    #: Es quien ganó el contrato anterior de este mismo objeto.
    es_incumbente: bool = False


class CuotaPropia(BaseModel):
    """La parte de la propia organización en el segmento."""

    model_config = ConfigDict(extra="forbid")

    expedientes: int = Field(ge=1)
    importe_adjudicado: float = Field(ge=0)
    cuota_pct: float = Field(ge=0, le=100)


class RivalesEsperados(BaseModel):
    """¿Contra quién? Quién gana en el segmento, con su cuota."""

    model_config = ConfigDict(extra="forbid")

    ventana_meses: int = Field(ge=1)
    #: Segmento sobre el que se rankeó; ``None`` si no hubo ninguno con datos.
    nivel: NivelSegmento | None = None
    #: Expedientes adjudicados del segmento: el universo de las cuotas.
    expedientes: int = Field(default=0, ge=0)
    #: Importe adjudicado del segmento: el denominador de las cuotas.
    importe_total: float = Field(default=0.0, ge=0)
    #: ``False`` cuando ningún nivel llegó a :data:`MIN_EXPEDIENTES_RIVALES` y
    #: se rankeó con lo que había.
    muestra_suficiente: bool = False
    items: list[Rival] = Field(default_factory=list)
    propia: CuotaPropia | None = None
    #: La organización ha declarado su NIF: sin él no se la puede reconocer y
    #: podría aparecer entre los rivales.
    identidad_conocida: bool = False
    sin_datos: str | None = None


class PujaSegmento(BaseModel):
    """Cómo se puja en el segmento: las bajas de referencia para el precio."""

    model_config = ConfigDict(extra="forbid")

    nivel: NivelSegmento
    ventana_meses: int = Field(ge=1)
    #: Base de los presupuestos (C1.1, ADR-032): se excluye lo que se sabe que
    #: lleva IVA, y el histórico sin base declarada sigue dentro.
    base: str = BASE_MIXTA
    #: Mediana de la baja del ganador, en %, con muestra suficiente.
    baja_ganadora_mediana_pct: float | None = None
    bajas_n: int = Field(default=0, ge=0)
    #: Mediana de la baja de la oferta más baja recibida, en %.
    baja_oferta_minima_mediana_pct: float | None = None
    ofertas_minimas_n: int = Field(default=0, ge=0)


class CompetenciaEsperada(BaseModel):
    """Respuesta de ``GET /licitaciones/{id}/competencia-esperada``."""

    model_config = ConfigDict(extra="forbid")

    licitacion_id: str
    organo: str | None = None
    cpv4: str | None = None
    ccaa: str | None = None
    ofertas: OfertasEsperadas
    incumbente: Incumbente | None = None
    rivales: RivalesEsperados
    puja: PujaSegmento | None = None
    #: Cuándo se calculó (ISO UTC): «¿esto de cuándo es?».
    calculado_en: str


# ── Piezas puras (sin BD) ───────────────────────────────────────────────────


def _cpv4_de(cpv: str | None) -> str | None:
    """CPV-4 del expediente, con la expresión de la señal del score.

    El score agrupa por ``substr(l.cpv, 1, 4)`` sin más; aquí se exigen además
    cuatro dígitos, porque un CPV ilegible no es un segmento al que comparar.
    """
    texto = (cpv or "").strip()[:4]
    return texto if len(texto) == 4 and texto.isdigit() else None


def _redondeo(valor: float) -> int:
    """Redondeo comercial (2,5 → 3), no el de banquero de ``round``."""
    return int(valor + 0.5)


def _numero(valor: Any) -> float | None:
    return None if valor is None else float(valor)


def _texto(valor: Any) -> str | None:
    texto = str(valor).strip() if valor is not None else ""
    return texto or None


#: Banda y sufijo de su columna en :func:`repo.ofertas_del_segmento`.
_BANDAS: tuple[tuple[NombreBanda, str], ...] = (("1", "1"), ("2-4", "2_4"), ("5+", "5"))


def _ofertas_nivel(
    fila: dict[str, Any], prefijo: str, nivel: NivelOfertas
) -> OfertasSegmento | None:
    """El nivel ``prefijo`` de la fila de :func:`repo.ofertas_del_segmento`, o ``None``."""
    expedientes = int(fila.get(f"{prefijo}_expedientes") or 0)
    media = fila.get(f"{prefijo}_media")
    if expedientes <= 0 or media is None:
        return None
    bandas = [
        BandaOfertas(
            banda=banda,
            expedientes=int(fila.get(f"{prefijo}_banda_{sufijo}") or 0),
            pct=round(int(fila.get(f"{prefijo}_banda_{sufijo}") or 0) / expedientes * 100, 1),
        )
        for banda, sufijo in _BANDAS
    ]
    return OfertasSegmento(
        nivel=nivel,
        media=round(float(media), 2),
        expedientes=expedientes,
        adjudicados=max(expedientes, int(fila.get(f"{prefijo}_adjudicados") or 0)),
        pct_oferta_unica=bandas[0].pct,
        bandas=bandas,
    )


def construir_ofertas(
    fila: dict[str, Any] | None,
    *,
    media_global: float | None,
    tiene_cpv: bool,
) -> OfertasEsperadas:
    """Elige la estimación: órgano si tiene muestra, si no el CPV-4, si no el global."""
    organo = _ofertas_nivel(fila or {}, "organo", "organo_cpv4")
    cpv4 = _ofertas_nivel(fila or {}, "cpv4", "cpv4")
    if organo is not None and organo.expedientes < MIN_EXPEDIENTES_ORGANO:
        organo = None
    if cpv4 is not None and cpv4.expedientes < MIN_EXPEDIENTES_CPV:
        cpv4 = None

    nivel: NivelEstimacion
    if organo is not None:
        estimacion, nivel = organo.media, "organo_cpv4"
    elif cpv4 is not None:
        estimacion, nivel = cpv4.media, "cpv4"
    elif media_global is not None:
        estimacion, nivel = media_global, "global"
    else:
        return OfertasEsperadas(
            ventana_meses=VENTANA_COMPETENCIA_MESES,
            sin_datos=(
                "Ningún expediente adjudicado de este CPV publica cuántas ofertas recibió."
                if tiene_cpv
                else "El expediente no publica CPV y no hay media global con la que estimar."
            ),
        )
    return OfertasEsperadas(
        ventana_meses=VENTANA_COMPETENCIA_MESES,
        estimacion=max(1, _redondeo(estimacion)),
        estimacion_nivel=nivel,
        organo_cpv4=organo,
        cpv4=cpv4,
        media_global=round(estimacion, 2) if nivel == "global" else None,
    )


def elegir_nivel(
    expedientes: dict[NivelSegmento, int], *, con_organo: bool, con_ccaa: bool
) -> tuple[NivelSegmento | None, bool]:
    """El nivel más estrecho con muestra suficiente, y si la tenía.

    Si ninguno llega al mínimo se usa el más estrecho que tenga algo (como la
    cohorte de los escenarios de precio), con ``suficiente=False`` para que la
    pantalla lo diga.
    """
    candidatos: list[NivelSegmento] = []
    if con_organo:
        candidatos.append("organo_cpv4")
    if con_ccaa:
        candidatos.append("cpv4_ccaa")
    candidatos.append("cpv4")
    for nivel in candidatos:
        if expedientes.get(nivel, 0) >= MIN_EXPEDIENTES_RIVALES:
            return nivel, True
    for nivel in candidatos:
        if expedientes.get(nivel, 0) > 0:
            return nivel, False
    return None, False


def _cuota(importe: float, total: float) -> float:
    if total <= 0:
        return 0.0
    # Acotada: un importe negativo por un dato malo no puede tumbar la
    # respuesta entera saliéndose del rango que admite el DTO.
    return round(max(0.0, min(100.0, importe / total * 100)), 1)


def construir_rivales(
    datos: dict[str, Any],
    *,
    nivel: NivelSegmento,
    suficiente: bool,
    identidad: IdentidadFiscal,
    incumbente_clave: str | None,
) -> RivalesEsperados:
    """Rivales a partir de :func:`repo.rivales_del_segmento`, sin la propia organización."""
    total = datos.get("total") or {}
    importe_total = float(total.get("importe_total") or 0.0)
    filas = datos.get("rivales") or []
    items: list[Rival] = []
    for fila in filas:
        empresa_id = fila.get("empresa_id")
        if identidad.reconoce(nifs=fila.get("nifs") or [], empresa_ids=[empresa_id]):
            continue
        expedientes = int(fila.get("expedientes") or 0)
        if expedientes <= 0:
            continue
        importe = max(0.0, float(fila.get("importe") or 0.0))
        baja = _numero(fila.get("baja_mediana_pct"))
        ultima = fila.get("ultima_adjudicacion")
        items.append(
            Rival(
                nombre=str(fila.get("nombre") or fila["clave"]),
                empresa_id=int(empresa_id) if empresa_id is not None else None,
                expedientes=expedientes,
                importe_adjudicado=importe,
                cuota_pct=_cuota(importe, importe_total),
                baja_mediana_pct=round(baja, 2) if baja is not None else None,
                bajas_n=int(fila.get("bajas_n") or 0),
                ultima_adjudicacion=str(ultima)[:10] if ultima else None,
                es_incumbente=incumbente_clave is not None and fila["clave"] == incumbente_clave,
            )
        )
        if len(items) >= MAX_RIVALES:
            break

    propia_expedientes = int(total.get("propia_expedientes") or 0)
    propia_importe = max(0.0, float(total.get("propia_importe") or 0.0))
    return RivalesEsperados(
        ventana_meses=VENTANA_RIVALES_MESES,
        nivel=nivel,
        expedientes=int(total.get("expedientes") or 0),
        importe_total=max(0.0, importe_total),
        muestra_suficiente=suficiente,
        items=items,
        propia=(
            CuotaPropia(
                expedientes=propia_expedientes,
                importe_adjudicado=propia_importe,
                cuota_pct=_cuota(propia_importe, importe_total),
            )
            if propia_expedientes > 0
            else None
        ),
        identidad_conocida=identidad.conocida,
        sin_datos=(
            None
            if items
            else "Solo la propia organización gana en este segmento."
            if filas
            else "Ninguna adjudicación del segmento identifica a su adjudicatario."
        ),
    )


def construir_puja(datos: dict[str, Any], *, nivel: NivelSegmento) -> PujaSegmento:
    """Las bajas de referencia del segmento, con su ``n`` y sin publicar medianas de dos casos."""
    total = datos.get("total") or {}
    bajas_n = int(total.get("bajas_n") or 0)
    minimas_n = int(total.get("ofertas_minimas_n") or 0)
    baja = _numero(total.get("baja_mediana_pct"))
    minima = _numero(total.get("baja_oferta_minima_mediana_pct"))
    return PujaSegmento(
        nivel=nivel,
        ventana_meses=VENTANA_RIVALES_MESES,
        baja_ganadora_mediana_pct=round(baja, 2)
        if baja is not None and bajas_n >= MIN_BAJAS
        else None,
        bajas_n=bajas_n,
        baja_oferta_minima_mediana_pct=(
            round(minima, 2) if minima is not None and minimas_n >= MIN_BAJAS else None
        ),
        ofertas_minimas_n=minimas_n,
    )


def construir_incumbente(
    candidato: Candidato | None, *, metodo: Metodo, identidad: IdentidadFiscal
) -> Incumbente | None:
    """El :class:`~services.similares.Candidato` predecesor, como incumbente."""
    if candidato is None:
        return None
    fecha = candidato.fecha_adjudicacion
    return Incumbente(
        licitacion_id=candidato.id_externo,
        titulo=candidato.titulo,
        adjudicatario=candidato.adjudicatario,
        empresa_id=candidato.adjudicatario_empresa_id,
        importe_adjudicado=candidato.importe_adjudicado,
        baja_pct=candidato.baja_pct,
        fecha_adjudicacion=str(fecha)[:10] if fecha else None,
        es_propia=identidad.reconoce(
            nifs=[candidato.adjudicatario_nif], empresa_ids=[candidato.adjudicatario_empresa_id]
        ),
        metodo=metodo,
    )


# ── Punto de entrada ────────────────────────────────────────────────────────


def _identidad(organization_id: int | None) -> IdentidadFiscal:
    """La identidad fiscal de la organización que mira, o una vacía.

    Un fallo de lectura no tumba el bloque: sin identidad la lista de rivales
    sigue siendo útil, solo que no puede quitar a la propia organización, y
    ``identidad_conocida=False`` lo dice. Deja traza: una exclusión que se salta
    en silencio es la que nadie ve hasta encontrarse entre sus rivales.
    """
    if organization_id is None:
        return IdentidadFiscal()
    try:
        return identidad_fiscal(organization_id)
    except Exception as exc:
        log.warning("competencia_esperada_identidad_error", error=str(exc)[:200])
        return IdentidadFiscal()


def _media_global() -> float | None:
    """La media de ofertas de todo el universo, la de la señal del score (cacheada)."""
    stats = load_competencia_stats()
    return stats.media_global


def competencia_esperada(
    id_externo: str,
    *,
    organization_id: int | None = None,
    ahora: datetime | None = None,
) -> CompetenciaEsperada | None:
    """Las tres respuestas sobre el segmento del expediente; ``None`` si no existe.

    ``organization_id`` es la organización ya resuelta por quien llama (la ruta
    lo hace con ``require_organization``; la ficha en PDF, con
    ``get_pursuit``): aquí solo se lee su identidad fiscal. ``ahora`` solo se
    inyecta en los tests: las dos ventanas se cuentan desde ese instante.
    """
    objetivo = repo.objetivo(id_externo)
    if objetivo is None:
        return None
    identidad = _identidad(organization_id)
    ahora = ahora or datetime.now(UTC)

    cpv4 = _cpv4_de(objetivo.get("cpv"))
    organo_id = objetivo.get("organo_id")
    segmento = (
        Segmento(
            cpv4=cpv4,
            organo_id=int(organo_id) if organo_id is not None else None,
            organo_norm=plegar_organo(objetivo.get("organo_contratacion")),
            ccaa=_texto(objetivo.get("ccaa")),
        )
        if cpv4
        else None
    )

    # ── ¿Cuántos? ──
    fila_ofertas = (
        repo.ofertas_del_segmento(
            segmento, excluir=id_externo, desde_iso=corte_ventana_competencia_iso(ahora=ahora)
        )
        if segmento
        else None
    )
    cpv_con_muestra = int((fila_ofertas or {}).get("cpv4_expedientes") or 0) >= MIN_EXPEDIENTES_CPV
    ofertas = construir_ofertas(
        fila_ofertas,
        # El global solo se pide cuando hace falta: es la carga cara de la
        # señal del score, aunque normalmente ya esté en su caché.
        media_global=None if cpv_con_muestra else _media_global(),
        tiene_cpv=segmento is not None,
    )

    # ── ¿Quién lo tiene hoy? ──
    predecesor = predecesor_de(objetivo)
    incumbente = construir_incumbente(
        predecesor.candidato, metodo=predecesor.metodo, identidad=identidad
    )
    incumbente_clave = (
        predecesor.candidato.adjudicatario_clave if predecesor.candidato is not None else None
    )

    # ── ¿Contra quién? y ¿cómo se puja? ──
    rivales: RivalesEsperados
    puja: PujaSegmento | None = None
    if segmento is None:
        rivales = RivalesEsperados(
            ventana_meses=VENTANA_RIVALES_MESES,
            identidad_conocida=identidad.conocida,
            sin_datos="El expediente no publica CPV: sin segmento no hay rivales comparables.",
        )
    else:
        hoy = ahora.date().isoformat()
        desde_rivales = sumar_meses(hoy, -VENTANA_RIVALES_MESES) or hoy
        por_nivel = repo.expedientes_por_nivel(
            segmento, excluir=id_externo, desde_iso=desde_rivales
        )
        nivel, suficiente = elegir_nivel(
            por_nivel, con_organo=segmento.tiene_organo, con_ccaa=segmento.ccaa is not None
        )
        if nivel is None:
            rivales = RivalesEsperados(
                ventana_meses=VENTANA_RIVALES_MESES,
                identidad_conocida=identidad.conocida,
                sin_datos=(
                    f"Ninguna adjudicación del CPV {segmento.cpv4} en los últimos "
                    f"{VENTANA_RIVALES_MESES} meses."
                ),
            )
        else:
            datos = repo.rivales_del_segmento(
                segmento,
                nivel,
                excluir=id_externo,
                desde_iso=desde_rivales,
                # Holgura para descartar a la propia organización sin quedarse
                # corto: puede ocupar más de una clave (NIF y maestro).
                limite=MAX_RIVALES + 3,
                propias_empresa_ids=sorted(identidad.empresa_ids),
                propios_nifs=sorted(identidad.nifs),
            )
            rivales = construir_rivales(
                datos,
                nivel=nivel,
                suficiente=suficiente,
                identidad=identidad,
                incumbente_clave=incumbente_clave,
            )
            puja = construir_puja(datos, nivel=nivel)

    return CompetenciaEsperada(
        licitacion_id=str(objetivo["id_externo"]),
        organo=objetivo.get("organo_contratacion"),
        cpv4=cpv4,
        ccaa=objetivo.get("ccaa"),
        ofertas=ofertas,
        incumbente=incumbente,
        rivales=rivales,
        puja=puja,
        calculado_en=ahora.isoformat(timespec="seconds"),
    )


# ── La ficha en PDF (F2.7) ──────────────────────────────────────────────────


def describir_nivel(nivel: str, *, cpv4: str | None, ccaa: str | None) -> str:
    """El segmento dicho como se diría en una reunión."""
    if nivel == "organo_cpv4":
        return f"este órgano en el CPV {cpv4}"
    if nivel == "cpv4_ccaa":
        return f"el CPV {cpv4} en {ccaa}"
    if nivel == "cpv4":
        return f"el CPV {cpv4}, todos los órganos"
    return "todo el universo analítico"


def _texto_ofertas(competencia: CompetenciaEsperada) -> str | None:
    ofertas = competencia.ofertas
    if ofertas.estimacion is None:
        return None
    segmento = ofertas.organo_cpv4 if ofertas.estimacion_nivel == "organo_cpv4" else ofertas.cpv4
    if segmento is None:
        return f"~{ofertas.estimacion} (media de todo el universo: el CPV no tiene muestra propia)"
    donde = describir_nivel(segmento.nivel, cpv4=competencia.cpv4, ccaa=competencia.ccaa)
    return (
        f"~{ofertas.estimacion} (media {segmento.media:.1f} en {donde}; "
        f"{segmento.pct_oferta_unica:.0f} % con oferta única)"
    )


def _texto_incumbente(incumbente: Incumbente) -> str:
    partes = [incumbente.adjudicatario or "Adjudicatario sin nombre publicado"]
    detalle = f"ganó {incumbente.licitacion_id}"
    if incumbente.fecha_adjudicacion:
        detalle += f" el {incumbente.fecha_adjudicacion}"
    if incumbente.importe_adjudicado is not None:
        detalle += f" por {incumbente.importe_adjudicado:,.2f} €"
    if incumbente.baja_pct is not None:
        detalle += f" (baja {incumbente.baja_pct:.1f} %)"
    partes.append(detalle)
    if incumbente.es_propia:
        partes.append("es la propia organización")
    return " — ".join(partes)


def bloque_ficha(competencia: CompetenciaEsperada) -> BloqueFicha:
    """El bloque «Competencia esperada» del one-pager, con su procedencia.

    Sigue las dos reglas del papel (``services/ficha_pdf.py``): sin nada que
    decir se omite con nota, no con guiones, y lo que se dice declara de qué
    universo y de cuándo es. No lleva NIF de nadie: solo nombres de
    adjudicatarios, como el bloque «Adjudicación observada».
    """
    filas: list[tuple[str, str]] = []
    if (texto := _texto_ofertas(competencia)) is not None:
        filas.append(("Ofertas esperadas", texto))
    rivales = competencia.rivales
    if rivales.items:
        filas.append(
            (
                "Rivales principales",
                ", ".join(f"{r.nombre} ({r.cuota_pct:.0f} %)" for r in rivales.items[:3]),
            )
        )
    if rivales.propia is not None:
        filas.append(
            (
                "La organización",
                f"{rivales.propia.cuota_pct:.1f} % del importe adjudicado del segmento "
                f"({rivales.propia.expedientes} expedientes)",
            )
        )
    puja = competencia.puja
    if puja is not None and puja.baja_ganadora_mediana_pct is not None:
        filas.append(
            (
                "Baja típica del ganador",
                f"{puja.baja_ganadora_mediana_pct:.1f} % ({puja.bajas_n} adjudicaciones)",
            )
        )

    if not filas and competencia.incumbente is None:
        return BloqueFicha(
            titulo="Competencia esperada",
            nota_vacio=(
                "Sin histórico comparable: ni el órgano ni el CPV del expediente tienen "
                "adjudicaciones con las que estimar cuántos se presentarán ni contra quién."
            ),
        )
    filas.insert(
        1 if filas and filas[0][0] == "Ofertas esperadas" else 0,
        (
            "Incumbente",
            _texto_incumbente(competencia.incumbente)
            if competencia.incumbente is not None
            else "Sin contrato anterior identificable del mismo órgano y objeto.",
        ),
    )

    procedencia: list[str] = []
    ofertas = competencia.ofertas
    segmento = ofertas.organo_cpv4 if ofertas.estimacion_nivel == "organo_cpv4" else ofertas.cpv4
    if segmento is not None:
        donde = describir_nivel(segmento.nivel, cpv4=competencia.cpv4, ccaa=competencia.ccaa)
        procedencia.append(
            f"Ofertas: {donde}, últimos {ofertas.ventana_meses} meses, "
            f"{segmento.expedientes} expedientes con el dato de {segmento.adjudicados} adjudicados."
        )
    elif ofertas.estimacion is not None:
        procedencia.append(
            f"Ofertas: todo el universo analítico, últimos {ofertas.ventana_meses} meses."
        )
    if rivales.nivel is not None:
        donde = describir_nivel(rivales.nivel, cpv4=competencia.cpv4, ccaa=competencia.ccaa)
        corta = "" if rivales.muestra_suficiente else " (muestra corta)"
        base = f"; bajas sobre base {puja.base}" if puja is not None else ""
        procedencia.append(
            f"Rivales: {donde}, últimos {rivales.ventana_meses} meses, "
            f"{rivales.expedientes} expedientes adjudicados{corta}{base}."
        )
    procedencia.append(f"Calculado el {competencia.calculado_en[:10]}.")
    return BloqueFicha(
        titulo="Competencia esperada", filas=filas, procedencia=" ".join(procedencia)
    )
