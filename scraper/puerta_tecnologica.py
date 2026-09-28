"""La puerta tecnológica: si un aviso es tecnología y con qué etiquetas.

Nació en el conector de PSCP (C4.1 / D24, endurecida el 2026-09-26) y desde el
2026-09-27 decide también en PLACSP (`scraper.codice_parser.parse_entry`): la
corroboración por CPV de las keywords ambiguas no depende de la fuente, y con la
regla solo en PSCP, «mantenimiento correctivo de ascensores» entraba en PLACSP
como `DESARROLLO`. Es la misma función en el conector de PSCP, en la purga del
censo (`scripts/purgar_pscp_sin_tecnologia.py`) y en PLACSP, a propósito: lo
que queda en la base de datos es lo que cualquiera de las tres admitiría hoy.

`scraper.connectors.pscp` re-exporta estos nombres, que la purga y los tests
importan de allí.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

from config import CPV_PREFIXES_TI
from scraper.filters import matches_technology

# ── Puerta tecnológica (C4.1 / D24, endurecida 2026-09-26) ──────────────────
#
# El conector solo persiste lo que casa con el diccionario de tecnologías. Con
# eso solo, en producción seguían entrando falsos positivos que un vistazo a la
# fila delata: medido el 2026-09-26, de 3.268 filas de PSCP con `tecnologia`,
# 1.318 no traían ningún CPV 48/72, y la mitad larga eran estas.

#: Keywords que en la contratación catalana casan **fuera** de TI. Cada una con
#: el falso positivo que la mete aquí, observado en filas reales de producción:
#: una keyword entra en esta lista por un ejemplo, no por sospecha.
#:
#: Una fila cuya ÚNICA señal son keywords de esta lista necesita que el CPV lo
#: corrobore (:func:`senal_tecnologica`). Una sola keyword fuera de la lista
#: basta, como siempre: «Llicències SAP S/4HANA» entra por `s/4hana` tenga el
#: CPV que tenga, porque los contratos menores traen CPV absurdos a menudo
#: (licencias de Office 365 codificadas como obra de puentes, 45221119).
#:
#: Se comparan con `casefold()` contra lo que devuelve `matches_technology`,
#: que es el texto casado en minúsculas; `tests/test_connectors_pscp.py` exige
#: que cada una siga existiendo en la semilla del diccionario, para que un
#: renombrado no deje aquí una entrada muerta.
KEYWORDS_AMBIGUAS: frozenset[str] = frozenset(
    {
        # 609 filas con CPV ajeno a TI: códigos de material del ICS en compras
        # menores («CODI SAP 7107067», «SAP 30053588 MAQUINETA RASURAT»), el
        # Servei d'Atenció Primària («SAP CENTRE»), un «servei d'assessorament
        # psicològic (SAP)».
        "sap",
        # Cables y adaptadores Apple Lightning, AirPods; kits de anticuerpos
        # «Lightning-Link». Casa incluso con CPV de material informático (302),
        # por eso la corroboración es 48/72 y no «cualquier cosa informática».
        "lightning",
        # Galerías API de bioMérieux para identificar bacterias («API 20
        # enterobacterias», CPV 33696500 de reactivos).
        "api",
        "apis",
        # Centre de Recerca Matemàtica (inscripciones «barccsyn (CRM)»),
        # estaciones «LMT i CRM» de mantenimiento de puertas.
        "crm",
        # Obras, climatización, SAI y extintores de la sala del CPD.
        "cpd",
        # Policloruro de aluminio para potabilizar agua (CPV 24312123).
        "pacs",
        # Electrodiálisis reversible de las potabilizadoras (ETAP Llobregat).
        "edr",
        # Reglamento de productos sanitarios (Medical Device Regulation).
        "mdr",
        # Planes de alquiler de impresoras, líneas 5G de respaldo.
        "backup",
        # Nombres de hotel (CPV 55).
        "sopra",
        # Telones cortafuegos textiles; franjas cortafuegos forestales.
        "tallafocs",
        "cortafuegos",
        # Ascensores, alumbrado, grupos electrógenos, carpintería, pintura...
        "manteniment correctiu",
        "mantenimiento correctivo",
        "mantemento correctivo",
        "mantentze zuzentzailea",
        # Carpetas portafirmas físicas (CPV 30197000, material de oficina).
        "portasignatures",
        "portafirmas",
        "portasinaturas",
        # Sistemas de gestión ISO (calidad y medio ambiente): auditorías y
        # consultoría de certificación, no software.
        "sistema integrat de gestió",
        "sistema de gestió integrat",
        "sistema integrado de gestión",
        "sistema de gestión integrado",
        "sistema integrado de xestión",
        "sistema de xestión integrado",
        "kudeaketa sistema integratua",
        # Seguridad física del perímetro: vallas, CCTV, vigilancia.
        "seguretat perimetral",
        "seguridad perimetral",
        "seguridade perimetral",
        "segurtasun perimetrala",
        # Cuadros eléctricos de mando y protección del alumbrado público.
        "quadre de comandament",
        "quadres de comandament",
        "cuadro de mando",
        "cuadros de mando",
        "cadro de mando",
        "cadros de mando",
    }
)

#: Un CPV de 8 cifras, con o sin dígito de control y con cualquier separador:
#: PSCP publica `codi_cpv` como `72267000-4||72262000-9`.
_CPV_CODIGO = re.compile(r"(?<!\d)\d{8}(?!\d)")

#: Apóstrofos tipográficos que la PSCP usa tanto como el recto. El diccionario
#: escribe `d'aplicacions` con el recto, así que «desenvolupament d'aplicacions»
#: con la comilla curva (U+2019) —la forma más habitual en los títulos de la
#: PSCP— no casaba nunca. Van como escapes porque son justo los
#: caracteres que un editor confunde con el recto.
_APOSTROFOS = str.maketrans({"\u2019": "'", "\u2018": "'", "\u02bc": "'", "\u00b4": "'", "`": "'"})

#: Corroboración de una keyword ambigua: software y servicios TI
#: (`CPV_PREFIXES_TI`, 48/72), equipo informático (302) y su mantenimiento
#: (50312, 5032). Sin los tres últimos, el dry-run de la purga del 2026-09-26
#: descartaba «Ampliació Cabina Backup del CPD» (302) o «Manteniment
#: equipament hardware del CPD» (50312610).
_CPV_CORROBORA_AMBIGUA: tuple[str, ...] = (*CPV_PREFIXES_TI, "302", "50312", "5032")

#: Ambiguas que solo corrobora un CPV 48/72: casan con compras de material
#: informático que no son la tecnología que nombran. Con 302 volverían los
#: cables Lightning (Salesforce) y los ordenadores que el ICS compra con su
#: «CODI SAP».
_AMBIGUAS_ESTRICTAS: frozenset[str] = frozenset({"sap", "lightning"})

#: Motivos del veredicto. Los dos de descarte son también los contadores del
#: resumen del run (ver `PscpConnector.contadores_de_descarte`).
MOTIVO_ADMITIDA = "keyword"
#: Sin keyword, pero con CPV de software o servicios TI (48/72). Es la regla que
#: PLACSP aplica desde 2026-09 (`cpv_ti_universe`): la LCSP limita nombrar
#: marcas en los pliegos, así que «Llicències Google Workspace» o «Programari
#: Factorial» no casan con el diccionario y son TI. Entran sin `tecnologia`, es
#: decir, fuera del universo que enseñan el Radar y la analítica.
MOTIVO_CPV_TI = "cpv_ti"
MOTIVO_SIN_SENAL = "sin_senal_tecnologica"
MOTIVO_AMBIGUA_SIN_CPV_TI = "keyword_ambigua_sin_cpv_ti"


@dataclass(frozen=True, slots=True)
class SenalTecnologica:
    """Veredicto de la puerta sobre un aviso: si entra y con qué etiquetas."""

    motivo: str
    tecnologias: tuple[str, ...] = ()
    keywords: tuple[str, ...] = ()

    @property
    def admitida(self) -> bool:
        return self.motivo in (MOTIVO_ADMITIDA, MOTIVO_CPV_TI)


def codigos_cpv(cpv: str | None) -> list[str]:
    """Los códigos CPV de 8 cifras de un campo, sin dígito de control."""
    return _CPV_CODIGO.findall(cpv or "")


def _algun_cpv_con(cpv: str | None, prefijos: tuple[str, ...]) -> bool:
    return any(c.startswith(prefijos) for c in codigos_cpv(cpv))


def _cpv_contradice(cpv: str | None, keywords: tuple[str, ...]) -> bool:
    """El CPV existe y ninguno de sus códigos corrobora estas keywords ambiguas.

    Sin CPV no hay contradicción: la fila conserva el beneficio de la duda,
    como antes de esta regla. Qué corrobora depende de la keyword: ver
    :data:`_CPV_CORROBORA_AMBIGUA` y :data:`_AMBIGUAS_ESTRICTAS`.
    """
    if not codigos_cpv(cpv):
        return False
    estricta = any(kw.casefold() in _AMBIGUAS_ESTRICTAS for kw in keywords)
    prefijos = tuple(CPV_PREFIXES_TI) if estricta else _CPV_CORROBORA_AMBIGUA
    return not _algun_cpv_con(cpv, prefijos)


def senal_tecnologica(titulo: str | None, cpv: str | None) -> SenalTecnologica:
    """Decide si un aviso es tecnología. La usan PSCP, PLACSP y la purga.

    Es **la misma función** en los dos sitios a propósito: la purga del censo
    histórico (`scripts/purgar_pscp_sin_tecnologia.py`) deja en la base de datos
    exactamente lo que el conector admitiría hoy, ni una fila más ni una menos.

    Reglas, en orden:

    1. Si el título casa con el diccionario vigente (`matches_technology`, con
       los apóstrofos tipográficos normalizados), entra con sus etiquetas…
    2. …salvo que todo lo que casó esté en :data:`KEYWORDS_AMBIGUAS` y el CPV
       la contradiga (:func:`_cpv_contradice`).
    3. Si no casa nada, entra **sin etiquetas** cuando algún CPV es 48/72
       (:data:`MOTIVO_CPV_TI`); si tampoco, se descarta.
    """
    texto = (titulo or "").translate(_APOSTROFOS)
    _, coincidencias = matches_technology(texto, None)
    if not coincidencias:
        if _algun_cpv_con(cpv, tuple(CPV_PREFIXES_TI)):
            return SenalTecnologica(MOTIVO_CPV_TI)
        return SenalTecnologica(MOTIVO_SIN_SENAL)
    keywords = tuple(sorted({kw for kws in coincidencias.values() for kw in kws}))
    solo_ambiguas = all(kw.casefold() in KEYWORDS_AMBIGUAS for kw in keywords)
    if solo_ambiguas and _cpv_contradice(cpv, keywords):
        return SenalTecnologica(MOTIVO_AMBIGUA_SIN_CPV_TI, keywords=keywords)
    return SenalTecnologica(MOTIVO_ADMITIDA, tuple(sorted(coincidencias)), keywords)
