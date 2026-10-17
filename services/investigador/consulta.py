"""Interpretación de la consulta del Investigador.

Quien busca escribe los filtros dentro de la frase —«mantenimiento SAP en
Andalucía de más de 500K»— y el motor de texto los trataba como palabras. No
lo son: «Andalucía» vive en la columna ``ccaa``, no en el título ni en la
descripción, y «500K» no aparece en ningún anuncio. Medido el 2026-10-09
contra producción, el ejemplo del propio placeholder casaba con 3 expedientes
y tres de las cinco preguntas de ejemplo de la pantalla, con ninguno.

Aquí se separan las dos cosas, sin modelo y sin red:

- **filtros** que la frase dice sin ambigüedad (comunidad autónoma, importe,
  fechas de publicación —también un mes con nombre—, fin del plazo de
  presentación «que cierran esta semana», procedimiento «contratos menores»,
  «abiertas», «más recientes»), y
- **términos** con los que sí se busca por texto: lo que queda, sin las
  palabras vacías ni las de petición («puedes mirar…», «dame…»).

Reglas conservadoras a propósito. Un filtro mal entendido esconde resultados
sin que se note, así que cada patrón exige una marca inequívoca: la comunidad
va detrás de «en» («en Madrid», no «Ayuntamiento de Madrid»); un importe lleva
unidad, moneda o la palabra «importe»/«presupuesto» («más de 500 usuarios» no
es un importe); «abierto» en masculino no cuenta, porque «procedimiento
abierto» es un tipo de procedimiento y «datos abiertos» un tema. Lo que la
función entiende viaja en la respuesta y la pantalla lo enseña, con un botón
para buscar el texto tal cual.

Función pura: ``hoy`` entra como argumento para que las fechas relativas se
puedan probar.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import date, timedelta
from typing import Literal

from db.sql_fragments import FOLD_TABLE
from services.investigador.search_engine import FTS5_STOPWORDS
from shared.geo import NUTS3_TO_CCAA

Orden = Literal["relevancia", "recientes"]

#: Términos que viajan al motor como mucho. El mismo techo que
#: ``extract_keywords``: una pregunta más larga no gana precisión con más
#: términos, gana ruido.
MAX_TERMINOS = 12

# ── Palabras que no se buscan ────────────────────────────────────────────────

#: Palabras de petición y de relleno de una pregunta hablada. Postgres no las
#: quita («puedes», «mirar» no son *stopwords* del diccionario español) y, con
#: una consulta en la que basta casar alguno de los términos, «puede» —que está
#: en la descripción de medio corpus— arrastraba expedientes sin relación.
_RELLENO: frozenset[str] = frozenset(
    {
        "puedes",
        "puede",
        "podrías",
        "podría",
        "mirar",
        "mira",
        "mírame",
        "ver",
        "veo",
        "enseña",
        "enséñame",
        "enseñar",
        "saca",
        "sácame",
        "sacar",
        "trae",
        "tráeme",
        "traer",
        "decir",
        "cuéntame",
        "explica",
        "explícame",
        "explicar",
        "resumen",
        "resume",
        "resúmeme",
        "resumir",
        "listado",
        # Verbos con los que se pregunta por lo que dice un documento («¿qué
        # pliegos hablan de…?», «…que exijan…»). Dentro de un pasaje de pliego
        # se exigen todos los términos: con «hablan» entre ellos, ninguno casa.
        "habla",
        "hablan",
        "hablen",
        "menciona",
        "mencionan",
        "mencionen",
        "trata",
        "tratan",
        "traten",
        "dice",
        "dicen",
        "digan",
        "aparece",
        "aparecen",
        "aparezca",
        "contiene",
        "contienen",
        "contengan",
        "incluye",
        "incluyen",
        "incluyan",
        "pide",
        "piden",
        "pidan",
        "exige",
        "exigen",
        "exijan",
        "requiere",
        "requieren",
        "requieran",
        # Como «licitaciones»: nombran el corpus, no lo que se busca en él.
        "pliego",
        "pliegos",
        "existe",
        "existen",
        "han",
        "has",
        "haya",
        "hayan",
        "tenido",
        "tengan",
        "tenga",
        "salido",
        "salen",
        "sale",
        "publicado",
        "publicados",
        "publicada",
        "publicadas",
        "favor",
        "gracias",
        "hola",
        "buenas",
        "alguna",
        "algunas",
        "alguno",
        "algunos",
        "algún",
        "quién",
        "quiénes",
        "cuándo",
        "que",
        "cual",
        "cuales",
        "me",
        "te",
        "nos",
        "les",
        "ya",
        "ni",
        "mas",
        "va",
        "van",
    }
)


def _plegar(texto: str) -> str:
    """Minúsculas y sin tildes, con la tabla del listado (``fold_expr``)."""
    return texto.translate(FOLD_TABLE).lower()


#: Todo lo que no es un término, ya plegado: se compara contra el token plegado
#: para que «cuántas» y «cuantas» caigan igual.
_NO_TERMINOS: frozenset[str] = frozenset(_plegar(p) for p in FTS5_STOPWORDS | _RELLENO)

#: Signos que rodean una palabra y no forman parte de ella. Los de dentro
#: («S/4HANA», «ISO-27001») se conservan: el analizador de Postgres guarda
#: «s/4hana» como un solo lexema, y partirlo en «4hana» no casa con nada.
#: Las comillas tipográficas van a propósito: son las que pega un procesador
#: de textos alrededor de una palabra.
# ruff: noqa: RUF001
_BORDES = " \t\r\n¿?¡!,.;:()[]{}«»\"'“”‘’`*"

# ── Comunidades autónomas ────────────────────────────────────────────────────

_CCAA_CANONICAS: frozenset[str] = frozenset(NUTS3_TO_CCAA.values())

#: Formas en que se escribe cada comunidad, plegadas → nombre tal como lo
#: guarda ``licitaciones.ccaa`` (el de ``shared.geo``). «Valencia» y «Murcia»
#: nombran también una ciudad; la comunidad la contiene, así que leerlas como
#: comunidad no deja fuera lo que se buscaba.
ALIAS_CCAA: dict[str, str] = {
    **{_plegar(nombre): nombre for nombre in _CCAA_CANONICAS},
    "principado de asturias": "Asturias",
    "euskadi": "País Vasco",
    "comunidad foral de navarra": "Navarra",
    "comunidad de madrid": "Madrid",
    "castilla la mancha": "Castilla-La Mancha",
    "catalunya": "Cataluña",
    "comunitat valenciana": "Comunidad Valenciana",
    "valencia": "Comunidad Valenciana",
    "islas baleares": "Baleares",
    "illes balears": "Baleares",
    "region de murcia": "Murcia",
    "islas canarias": "Canarias",
}

_CCAA_ALT = "|".join(re.escape(a) for a in sorted(ALIAS_CCAA, key=len, reverse=True))
_CCAA_UNA_RE = re.compile(rf"(?<![a-z0-9])(?:{_CCAA_ALT})(?![a-z0-9])")
_CCAA_RE = re.compile(
    r"(?<![a-z0-9])en\s+(?:la\s+|el\s+|las\s+)?"
    r"(?:comunidad\s+autonoma\s+(?:de\s+|del\s+)?(?:la\s+)?)?"
    rf"(?:{_CCAA_ALT})"
    rf"(?:\s*(?:,|\by\b|\bo\b|\be\b)\s*(?:en\s+)?(?:la\s+|el\s+|las\s+)?(?:{_CCAA_ALT}))*"
    r"(?![a-z0-9])"
)

# ── Importes ─────────────────────────────────────────────────────────────────


def _cifra(p: str) -> str:
    """Una cifra con su unidad y su moneda opcionales; ``p`` prefija los grupos."""
    return (
        rf"(?P<{p}num>\d{{1,3}}(?:\.\d{{3}})+|\d+)(?:[.,](?P<{p}dec>\d{{1,2}}))?"
        rf"\s*(?P<{p}mult>k|mil|millones|millon|mm|m)?(?![a-z0-9])"
        rf"\s*(?P<{p}mon>€|euros?(?![a-z0-9])|eur(?![a-z0-9]))?"
    )


_CLAVE_IMPORTE = (
    r"(?:(?:con|de|por)\s+)?"
    r"(?:(?:un\s+)?(?P<clave>importe|presupuesto|valor(?:\s+estimado)?)\s+)?"
    r"(?:(?:de|por)\s+)?"
)
_MIN_RE = re.compile(
    r"(?<![a-z0-9])" + _CLAVE_IMPORTE + r"(?:mas\s+de|mayor(?:es)?\s+(?:a|de|que)|"
    r"superior(?:es)?\s+a|por\s+encima\s+de|a\s+partir\s+de|como\s+minimo(?:\s+de)?|"
    r"minimo(?:\s+de)?|>=?|desde)\s*" + _cifra("a")
)
_MAX_RE = re.compile(
    r"(?<![a-z0-9])" + _CLAVE_IMPORTE + r"(?:menos\s+de|menor(?:es)?\s+(?:a|de|que)|"
    r"inferior(?:es)?\s+a|por\s+debajo\s+de|como\s+maximo(?:\s+de)?|maximo(?:\s+de)?|"
    r"<=?|hasta)\s*" + _cifra("a")
)
_ENTRE_RE = re.compile(
    r"(?<![a-z0-9])" + _CLAVE_IMPORTE + r"entre\s+" + _cifra("a") + r"\s+y\s+" + _cifra("b")
)

_MULTIPLICADOR = {
    "k": 1_000.0,
    "mil": 1_000.0,
    "m": 1_000_000.0,
    "mm": 1_000_000.0,
    "millon": 1_000_000.0,
    "millones": 1_000_000.0,
}

# ── Fechas de publicación ────────────────────────────────────────────────────

_ANIO = r"(?P<anio>20\d{2})(?![\d/\-.]?\d)(?!\s*(?:€|euros?|eur|k|mil|millon)(?![a-z]))"
_DESDE_ANIO_RE = re.compile(r"(?<![a-z0-9])desde\s+(?:el\s+)?(?:ano\s+)?" + _ANIO)
_HASTA_ANIO_RE = re.compile(r"(?<![a-z0-9])hasta\s+(?:el\s+)?(?:ano\s+)?" + _ANIO)
_EN_ANIO_RE = re.compile(
    r"(?<![a-z0-9])(?:(?:en|de|del|durante)\s+(?:el\s+)?(?:ano\s+)?|ano\s+)" + _ANIO
)
_ESTE_ANIO_RE = re.compile(r"(?<![a-z0-9])(?:de\s+|en\s+)?este\s+ano(?![a-z0-9])")
_ESTE_MES_RE = re.compile(r"(?<![a-z0-9])(?:de\s+|en\s+)?este\s+mes(?![a-z0-9])")
_ESTA_SEMANA_RE = re.compile(r"(?<![a-z0-9])(?:de\s+|en\s+)?esta\s+semana(?![a-z0-9])")
_ULTIMOS_N_RE = re.compile(
    r"(?<![a-z0-9])(?:(?:de|en|durante)\s+)?(?:los\s+|las\s+)?ultim[oa]s\s+"
    r"(?P<n>\d{1,3})\s+(?P<unidad>dias|semanas|meses)(?![a-z0-9])"
)
_ULTIMO_RE = re.compile(
    r"(?<![a-z0-9])(?:(?:de|en|durante)\s+)?(?:el\s+|la\s+)?ultim[oa]\s+"
    r"(?P<unidad>mes|semana|ano)(?![a-z0-9])"
)
_DIAS_POR_UNIDAD = {"dias": 1, "semanas": 7, "meses": 30, "semana": 7, "mes": 30, "ano": 365}

_MESES: dict[str, int] = {
    "enero": 1,
    "febrero": 2,
    "marzo": 3,
    "abril": 4,
    "mayo": 5,
    "junio": 6,
    "julio": 7,
    "agosto": 8,
    "septiembre": 9,
    "setiembre": 9,
    "octubre": 10,
    "noviembre": 11,
    "diciembre": 12,
}
_MES_ALT = "|".join(_MESES)

#: «en marzo», «durante el mes de mayo de 2025». Solo detrás de «en» o
#: «durante»: «Dos de Mayo» es una plaza y «de marzo» suelto, media fecha.
_EN_MES_RE = re.compile(
    r"(?<![a-z0-9])(?:en|durante)\s+(?:el\s+mes\s+de\s+)?"
    rf"(?P<mes>{_MES_ALT})(?:\s+(?:de\s+|del\s+)?(?P<anio>20\d{{2}}))?(?![a-z0-9])"
)

# ── Fin del plazo de presentación ────────────────────────────────────────────

#: El verbo que hace de la fecha un **cierre** y no una publicación: «que
#: cierran esta semana», «con plazo hasta…», «vencen mañana». Sin él, «esta
#: semana» sigue siendo de publicación, como siempre.
_CIERRE = (
    r"(?<![a-z0-9])(?:(?:que|cuyo\s+plazo|con\s+(?:el\s+)?plazo\s+que)\s+)?"
    r"(?:cierra|cierran|cierre|cierren|vence|vencen|venza|venzan|termina|terminan|"
    r"termine|terminen|acaba|acaban|acabe|acaben|finaliza|finalizan|finalice|finalicen)"
    r"(?:\s+(?:el|su)\s+plazo)?"
    r"|(?<![a-z0-9])(?P<hasta>con\s+(?:el\s+)?plazo\s+(?:de\s+presentacion\s+)?hasta)"
)
_CIERRE_HORIZONTE = (
    r"(?P<hoy>hoy)|(?P<manana>manana)"
    r"|(?P<semana>esta\s+semana)|(?P<mes_actual>este\s+mes)"
    r"|(?P<semana_que_viene>(?:la\s+)?(?:semana\s+que\s+viene|proxima\s+semana))"
    r"|(?P<mes_que_viene>(?:el\s+)?(?:mes\s+que\s+viene|proximo\s+mes))"
    r"|(?:en\s+)?(?:los\s+|las\s+)?(?:proxim[oa]s\s+)?(?P<n>\d{1,3})\s+(?P<unidad>dias|semanas)"
    r"|antes\s+del?\s+(?P<antes_dia>\d{1,2})\s+de\s+(?P<antes_mes>" + _MES_ALT + r")"
    r"(?:\s+(?:de\s+|del\s+)?(?P<antes_anio>20\d{2}))?"
    r"|(?:el\s+)?(?P<dia>\d{1,2})\s+de\s+(?P<dia_mes>" + _MES_ALT + r")"
    r"(?:\s+(?:de\s+|del\s+)?(?P<dia_anio>20\d{2}))?"
    r"|en\s+(?P<mes>" + _MES_ALT + r")(?:\s+(?:de\s+|del\s+)?(?P<mes_anio>20\d{2}))?"
)
_CIERRE_RE = re.compile(rf"(?:{_CIERRE})\s+(?:{_CIERRE_HORIZONTE})(?![a-z0-9])")

# ── Procedimiento ────────────────────────────────────────────────────────────

#: Frases que nombran un procedimiento → códigos CODICE (``shared.procedimientos``).
#: Cada una exige la palabra que la hace inequívoca: «abierto» suelto es un
#: adjetivo («datos abiertos»), «procedimiento abierto» no.
_PROCEDIMIENTOS: tuple[tuple[re.Pattern[str], tuple[str, ...]], ...] = tuple(
    (re.compile(rf"(?<![a-z0-9])(?:por\s+|de\s+|mediante\s+)?{patron}(?![a-z0-9])"), codigos)
    for patron, codigos in (
        (r"contratos?\s+menor(?:es)?", ("6",)),
        (r"(?:procedimientos?\s+)?abiertos?\s+simplificados?", ("9",)),
        (r"procedimientos?\s+abiertos?", ("1",)),
        (r"procedimientos?\s+restringidos?", ("2",)),
        (r"(?:procedimientos?\s+)?negociados?\s+sin\s+publicidad", ("3",)),
        (r"(?:procedimientos?\s+)?negociados?\s+con\s+publicidad", ("4",)),
        (r"procedimientos?\s+negociados?", ("3", "4")),
        (r"dialogos?\s+competitivos?", ("5",)),
        (r"(?:derivados?|basados?)\s+(?:de|en)\s+(?:un\s+)?acuerdos?\s+marco", ("7",)),
        (r"concursos?\s+de\s+proyectos", ("8",)),
        (r"asociacion(?:es)?\s+para\s+la\s+innovacion", ("10",)),
    )
)

# ── Estado y orden ───────────────────────────────────────────────────────────

_ABIERTAS_RE = re.compile(
    r"(?<![a-z0-9])(?:(?:que\s+)?(?:siguen?|sigan|estan|esten|todavia|aun)\s+)?abiertas(?![a-z0-9])"
    r"|(?<![a-z0-9])(?:todavia|aun)\s+abierta(?![a-z0-9])"
    r"|(?<![a-z0-9])en\s+plazo(?![a-z0-9])"
    r"|(?<![a-z0-9])sin\s+adjudicar(?![a-z0-9])"
)
_RECIENTES_RE = re.compile(
    r"(?<![a-z0-9])(?:(?:las|los|lo)\s+)?(?:mas\s+recientes|mas\s+nuevas|recientes|"
    r"ultim[oa]s|ultimo)(?![a-z0-9])"
)

_OPERADORES_RE = re.compile(r'"|(?:^|\s)-\w')


@dataclass(frozen=True)
class ConsultaInterpretada:
    """Lo que se entendió de una consulta: filtros, términos y orden."""

    #: La consulta tal como llegó.
    original: str
    #: El texto con el que de verdad se busca. Con operadores (comillas o
    #: ``-exclusión``) es lo que queda de la frase, para ``websearch_to_tsquery``;
    #: sin ellos, los ``terminos`` unidos por espacios.
    texto: str
    #: Palabras significativas, en el orden en que se escribieron y sin
    #: repetir. Vacío con operadores: ahí manda la expresión entera.
    terminos: tuple[str, ...] = ()
    #: La consulta trae comillas o ``-palabra``: se respeta como expresión.
    con_operadores: bool = False
    ccaa: tuple[str, ...] = ()
    importe_min: float | None = None
    importe_max: float | None = None
    solo_abiertas: bool = False
    fecha_desde: str | None = None
    fecha_hasta: str | None = None
    #: Ventana del fin del plazo de presentación («que cierran esta semana»).
    cierre_desde: str | None = None
    cierre_hasta: str | None = None
    #: Códigos CODICE de procedimiento («contratos menores» → ``6``).
    procedimiento: tuple[str, ...] = ()
    orden: Orden = "relevancia"

    @property
    def tiene_filtros(self) -> bool:
        """Algún filtro salió de la frase (el orden no es un filtro)."""
        return bool(
            self.ccaa
            or self.importe_min is not None
            or self.importe_max is not None
            or self.solo_abiertas
            or self.fecha_desde
            or self.fecha_hasta
            or self.cierre_desde
            or self.cierre_hasta
            or self.procedimiento
        )

    @property
    def tiene_texto(self) -> bool:
        """Queda algo con lo que buscar por texto."""
        return bool(self.terminos) or (self.con_operadores and bool(self.texto.strip()))


class _Frase:
    """La consulta y su copia plegada, alineadas carácter a carácter.

    Los patrones se buscan sobre la copia plegada (sin tildes, en minúsculas)
    y lo que casan se tacha en las dos: lo que sobrevive en ``original`` es el
    texto que se busca, con su grafía.
    """

    def __init__(self, original: str) -> None:
        self.original = original
        self.plegada = _plegar(original)

    @property
    def alineada(self) -> bool:
        """El plegado conserva la longitud; con algún carácter exótico no."""
        return len(self.original) == len(self.plegada)

    def tachar(self, inicio: int, fin: int) -> None:
        hueco = " " * (fin - inicio)
        self.original = self.original[:inicio] + hueco + self.original[fin:]
        self.plegada = self.plegada[:inicio] + hueco + self.plegada[fin:]


def _valor(m: re.Match[str], p: str, frase: _Frase) -> tuple[float, bool]:
    """``(importe, lleva_unidad)`` de la cifra ``p`` de un match.

    Una «m» minúscula suelta no cuenta como millones si no la sigue la moneda:
    «más de 2 m» son metros. La mayúscula se mira en la frase original, que
    está alineada con la plegada.
    """
    entero = m.group(f"{p}num").replace(".", "")
    decimales = m.group(f"{p}dec")
    valor = float(f"{entero}.{decimales}" if decimales else entero)
    mult = m.group(f"{p}mult")
    moneda = m.group(f"{p}mon")
    if mult == "m" and not moneda and frase.original[m.start(f"{p}mult")] != "M":
        mult = None
    if mult:
        valor *= _MULTIPLICADOR[mult]
    return valor, bool(mult or moneda)


def _primer_importe(
    patron: re.Pattern[str], frase: _Frase, cifras: tuple[str, ...]
) -> tuple[re.Match[str], list[float]] | None:
    """El primer match de ``patron`` que es de verdad un importe.

    Lo es si alguna de sus cifras lleva unidad o moneda, o si la frase nombra
    «importe»/«presupuesto»/«valor». Sin eso, «desde 2024» es una fecha y «más
    de 500 usuarios», una cantidad de otra cosa.
    """
    for m in patron.finditer(frase.plegada):
        valores: list[float] = []
        con_unidad = bool(m.group("clave"))
        for p in cifras:
            valor, unidad = _valor(m, p, frase)
            valores.append(valor)
            con_unidad = con_unidad or unidad
        if con_unidad:
            return m, valores
    return None


def _terminos(texto: str) -> tuple[str, ...]:
    """Palabras significativas de ``texto``, sin repetir y en su orden."""
    vistos: dict[str, None] = {}
    for bruto in texto.split():
        token = bruto.strip(_BORDES).lower()
        if len(token) < 2 or (len(token) == 2 and not token.isalnum()):
            continue
        if _plegar(token) in _NO_TERMINOS:
            continue
        vistos.setdefault(token, None)
        if len(vistos) == MAX_TERMINOS:
            break
    return tuple(vistos)


def _texto_y_terminos(restante: str) -> tuple[str, tuple[str, ...], bool]:
    """``(texto, terminos, con_operadores)`` de lo que queda de la frase."""
    limpio = " ".join(restante.split())
    if _OPERADORES_RE.search(limpio):
        return limpio, (), True
    terminos = _terminos(limpio)
    return " ".join(terminos), terminos, False


def _anio_del_mes(mes: int, anio: str | None, referencia: date, *, futuro: bool) -> int:
    """El año de un mes dicho sin año: el último que ya empezó, o el próximo.

    «Publicadas en marzo» en octubre es el marzo pasado; «que cierran en
    marzo», el que viene. El mes en curso es el de este año en los dos casos.
    """
    if anio:
        return int(anio)
    if futuro:
        return referencia.year + (1 if mes < referencia.month else 0)
    return referencia.year - (1 if mes > referencia.month else 0)


def _ultimo_dia(anio: int, mes: int) -> date:
    siguiente = date(anio + 1, 1, 1) if mes == 12 else date(anio, mes + 1, 1)
    return siguiente - timedelta(days=1)


def _ventana_de_cierre(m: re.Match[str], hoy: date) -> tuple[date, date] | None:
    """``(desde, hasta)`` del horizonte de un match de :data:`_CIERRE_RE`.

    Un cierre que ya pasó no es lo que se busca: el suelo es siempre ``hoy``,
    salvo que se nombre un día concreto («que cierran el 30 de noviembre»). Con
    «con plazo hasta…» la fecha es el techo y el suelo vuelve a ser ``hoy``.
    Una fecha que no existe («31 de febrero») no se entiende y la frase se
    busca como texto.
    """
    ventana = _horizonte(m.groupdict(), hoy)
    if ventana is None or ventana[1] < hoy:
        return None
    desde, hasta = ventana
    return (hoy if m.group("hasta") else max(desde, hoy)), hasta


def _horizonte(g: dict[str, str | None], hoy: date) -> tuple[date, date] | None:
    """La ventana que nombra el horizonte, antes de aplicarle el suelo."""
    if g["hoy"]:
        return hoy, hoy
    if g["manana"]:
        return hoy + timedelta(days=1), hoy + timedelta(days=1)
    if g["semana"]:
        return hoy, hoy + timedelta(days=6 - hoy.weekday())
    if g["mes_actual"]:
        return hoy, _ultimo_dia(hoy.year, hoy.month)
    if g["semana_que_viene"]:
        lunes = hoy + timedelta(days=7 - hoy.weekday())
        return lunes, lunes + timedelta(days=6)
    if g["mes_que_viene"]:
        anio, mes = (hoy.year + 1, 1) if hoy.month == 12 else (hoy.year, hoy.month + 1)
        return date(anio, mes, 1), _ultimo_dia(anio, mes)
    if g["n"]:
        dias = int(g["n"] or 0) * _DIAS_POR_UNIDAD[g["unidad"] or "dias"]
        return hoy, hoy + timedelta(days=dias)
    try:
        if g["antes_dia"] and g["antes_mes"]:
            mes = _MESES[g["antes_mes"]]
            anio = _anio_del_mes(mes, g["antes_anio"], hoy, futuro=True)
            return hoy, date(anio, mes, int(g["antes_dia"])) - timedelta(days=1)
        if g["dia"] and g["dia_mes"]:
            mes = _MESES[g["dia_mes"]]
            anio = _anio_del_mes(mes, g["dia_anio"], hoy, futuro=True)
            dia = date(anio, mes, int(g["dia"]))
            return dia, dia
    except ValueError:
        return None
    if g["mes"]:
        mes = _MESES[g["mes"]]
        anio = _anio_del_mes(mes, g["mes_anio"], hoy, futuro=True)
        return date(anio, mes, 1), _ultimo_dia(anio, mes)
    return None


def interpretar(
    consulta: str, *, hoy: date | None = None, filtros: bool = True
) -> ConsultaInterpretada:
    """Separa los filtros que dice la frase de los términos con que se busca.

    Con ``filtros=False`` solo se limpian los términos: es «buscar el texto tal
    cual», para cuando lo entendido no era lo que se quería decir.
    """
    frase = _Frase(consulta)
    if not filtros or not frase.alineada:
        texto, terminos, con_operadores = _texto_y_terminos(consulta)
        return ConsultaInterpretada(
            original=consulta, texto=texto, terminos=terminos, con_operadores=con_operadores
        )

    referencia = hoy or date.today()
    importe_min: float | None = None
    importe_max: float | None = None
    fecha_desde: str | None = None
    fecha_hasta: str | None = None

    # Importes antes que fechas: «desde» y «hasta» valen para los dos, y lo que
    # los distingue es la unidad de la cifra.
    if hallado := _primer_importe(_ENTRE_RE, frase, ("a", "b")):
        cifra, (uno, otro) = hallado
        importe_min, importe_max = min(uno, otro), max(uno, otro)
        frase.tachar(*cifra.span())
    if importe_min is None and (hallado := _primer_importe(_MIN_RE, frase, ("a",))):
        cifra, (importe_min,) = hallado
        frase.tachar(*cifra.span())
    if importe_max is None and (hallado := _primer_importe(_MAX_RE, frase, ("a",))):
        cifra, (importe_max,) = hallado
        frase.tachar(*cifra.span())

    # El plazo antes que la publicación: en «que cierran esta semana» la
    # semana es del cierre, y la leería como publicación el patrón de abajo.
    cierre_desde: str | None = None
    cierre_hasta: str | None = None
    for cierre in _CIERRE_RE.finditer(frase.plegada):
        if ventana := _ventana_de_cierre(cierre, referencia):
            cierre_desde, cierre_hasta = (d.isoformat() for d in ventana)
            frase.tachar(*cierre.span())
            break

    if m := _ULTIMOS_N_RE.search(frase.plegada):
        dias = int(m.group("n")) * _DIAS_POR_UNIDAD[m.group("unidad")]
        fecha_desde = (referencia - timedelta(days=dias)).isoformat()
        frase.tachar(*m.span())
    elif m := _ULTIMO_RE.search(frase.plegada):
        dias = _DIAS_POR_UNIDAD[m.group("unidad")]
        fecha_desde = (referencia - timedelta(days=dias)).isoformat()
        frase.tachar(*m.span())
    elif m := _ESTA_SEMANA_RE.search(frase.plegada):
        fecha_desde = (referencia - timedelta(days=referencia.weekday())).isoformat()
        frase.tachar(*m.span())
    elif m := _ESTE_MES_RE.search(frase.plegada):
        fecha_desde = referencia.replace(day=1).isoformat()
        frase.tachar(*m.span())
    elif m := _ESTE_ANIO_RE.search(frase.plegada):
        fecha_desde = f"{referencia.year}-01-01"
        frase.tachar(*m.span())
    elif m := _EN_MES_RE.search(frase.plegada):
        mes = _MESES[m.group("mes")]
        anio = _anio_del_mes(mes, m.group("anio"), referencia, futuro=False)
        fecha_desde = date(anio, mes, 1).isoformat()
        fecha_hasta = _ultimo_dia(anio, mes).isoformat()
        frase.tachar(*m.span())
    else:
        if m := _DESDE_ANIO_RE.search(frase.plegada):
            fecha_desde = f"{m.group('anio')}-01-01"
            frase.tachar(*m.span())
        if m := _HASTA_ANIO_RE.search(frase.plegada):
            fecha_hasta = f"{m.group('anio')}-12-31"
            frase.tachar(*m.span())
        if fecha_desde is None and fecha_hasta is None and (m := _EN_ANIO_RE.search(frase.plegada)):
            fecha_desde = f"{m.group('anio')}-01-01"
            fecha_hasta = f"{m.group('anio')}-12-31"
            frase.tachar(*m.span())

    ccaa: dict[str, None] = {}
    for m in list(_CCAA_RE.finditer(frase.plegada)):
        for alias in _CCAA_UNA_RE.finditer(m.group(0)):
            ccaa.setdefault(ALIAS_CCAA[alias.group(0)], None)
        frase.tachar(*m.span())

    procedimiento: dict[str, None] = {}
    for patron, codigos in _PROCEDIMIENTOS:
        for m in list(patron.finditer(frase.plegada)):
            procedimiento.update(dict.fromkeys(codigos))
            frase.tachar(*m.span())

    solo_abiertas = False
    for m in list(_ABIERTAS_RE.finditer(frase.plegada)):
        solo_abiertas = True
        frase.tachar(*m.span())

    orden: Orden = "relevancia"
    for m in list(_RECIENTES_RE.finditer(frase.plegada)):
        orden = "recientes"
        frase.tachar(*m.span())

    texto, terminos, con_operadores = _texto_y_terminos(frase.original)
    return ConsultaInterpretada(
        original=consulta,
        texto=texto,
        terminos=terminos,
        con_operadores=con_operadores,
        ccaa=tuple(ccaa),
        importe_min=importe_min,
        importe_max=importe_max,
        solo_abiertas=solo_abiertas,
        fecha_desde=fecha_desde,
        fecha_hasta=fecha_hasta,
        cierre_desde=cierre_desde,
        cierre_hasta=cierre_hasta,
        procedimiento=tuple(procedimiento),
        orden=orden,
    )
