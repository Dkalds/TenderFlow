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

from config import CPV_PREFIXES_TI, CPV_PREFIXES_UNIVERSO
from config.keywords import KEYWORDS_AMBIGUAS as KEYWORDS_AMBIGUAS
from config.keywords import etiquetas_con_senal_firme
from scraper.filters import matches_technology

# ── Puerta tecnológica (C4.1 / D24, endurecida 2026-09-26) ──────────────────
#
# El conector solo persiste lo que casa con el diccionario de tecnologías. Con
# eso solo, en producción seguían entrando falsos positivos que un vistazo a la
# fila delata: medido el 2026-09-26, de 3.268 filas de PSCP con `tecnologia`,
# 1.318 no traían ningún CPV 48/72, y la mitad larga eran estas.
#
# Las keywords que casan fuera de TI son `config.keywords.KEYWORDS_AMBIGUAS`
# (re-exportada aquí): una fila cuya ÚNICA señal son keywords de esa lista
# necesita que el CPV lo corrobore (:func:`senal_tecnologica`), porque los
# contratos menores traen CPV absurdos a menudo (licencias de Office 365
# codificadas como obra de puentes, 45221119) y una keyword firme basta.


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
#: «CODI SAP». Concur es software como servicio: no lo corrobora un equipo.
_AMBIGUAS_ESTRICTAS: frozenset[str] = frozenset({"sap", "concur", "lightning"})

#: Motivos del veredicto. Los dos de descarte son también los contadores del
#: resumen del run (ver `PscpConnector.contadores_de_descarte`).
MOTIVO_ADMITIDA = "keyword"
#: Sin keyword, pero con CPV del universo de ingesta (`CPV_PREFIXES_UNIVERSO`:
#: software y servicios TI 48/72 y, desde 2026-10-30, telecomunicaciones 32). Es
#: la regla que PLACSP aplica desde 2026-09 (`cpv_ti_universe`): la LCSP limita
#: nombrar marcas en los pliegos, así que «Llicències Google Workspace» o
#: «Programari Factorial» no casan con el diccionario y son TI. Entran sin
#: `tecnologia`, es decir, fuera del universo que enseñan el Radar y la analítica.
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
    3. Si casó alguna keyword firme, las etiquetas sostenidas solo por
       ambiguas se caen (:func:`config.keywords.etiquetas_con_senal_firme`):
       «mantenimiento correctivo de SAP S/4HANA» es `SAP`, no `SAP,DESARROLLO`.
    4. Si no casa nada, entra **sin etiquetas** cuando algún CPV es del
       universo de ingesta, 48/72/32 (:data:`MOTIVO_CPV_TI`); si tampoco, se
       descarta.
    """
    texto = (titulo or "").translate(_APOSTROFOS)
    _, coincidencias = matches_technology(texto, None)
    if not coincidencias:
        if _algun_cpv_con(cpv, tuple(CPV_PREFIXES_UNIVERSO)):
            return SenalTecnologica(MOTIVO_CPV_TI)
        return SenalTecnologica(MOTIVO_SIN_SENAL)
    coincidencias = etiquetas_con_senal_firme(coincidencias)
    keywords = tuple(sorted({kw for kws in coincidencias.values() for kw in kws}))
    solo_ambiguas = all(kw.casefold() in KEYWORDS_AMBIGUAS for kw in keywords)
    if solo_ambiguas and _cpv_contradice(cpv, keywords):
        return SenalTecnologica(MOTIVO_AMBIGUA_SIN_CPV_TI, keywords=keywords)
    return SenalTecnologica(MOTIVO_ADMITIDA, tuple(sorted(coincidencias)), keywords)
