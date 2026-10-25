"""Qué cuenta como palabra relevante de una pregunta en lenguaje natural.

``extract_keywords`` y ``FTS5_STOPWORDS`` los comparten el último recurso por
subcadena de ``/ask`` (``db/repositories/licitaciones.py::search_like_for_ask``)
y la interpretación de la frase (:mod:`services.investigador.consulta`). Viven
en ``shared/`` porque los consume la persistencia, que no puede importar de la
capa de dominio (AGENTS.md §2); ``services.investigador.search_engine`` los
reexporta. Solo biblioteca estándar.
"""

from __future__ import annotations

import re

# Stopwords en español: palabras interrogativas, conectores, verbos de petición y
# los pocos términos que *definen* el corpus (y por tanto no discriminan: aparecen
# en casi todos los documentos). Se filtran antes de construir la query FTS5/LIKE
# para evitar que saturen el ranking con documentos irrelevantes. Deliberadamente
# NO incluye sustantivos de dominio discriminantes (contrato, servicio, obra,
# pública...) — esos sí aportan señal en búsquedas por palabra clave.
# Compartido con el fallback LIKE del repositorio (search_like_for_ask).
FTS5_STOPWORDS: frozenset[str] = frozenset(
    {
        # Conectores y artículos
        "de",
        "la",
        "el",
        "y",
        "o",
        "u",
        "a",
        "en",
        "es",
        "que",
        "qué",
        "cuál",
        "cuáles",
        "cómo",
        "como",
        "donde",
        "dónde",
        "hay",
        "ha",
        "un",
        "una",
        "unos",
        "unas",
        "los",
        "las",
        "del",
        "por",
        "para",
        "con",
        "sin",
        "sobre",
        "entre",
        "hasta",
        "si",
        "no",
        "le",
        "lo",
        "su",
        "sus",
        "se",
        "al",
        "más",
        "pero",
        "este",
        "esta",
        "estos",
        "estas",
        "ese",
        "esa",
        "esos",
        "esas",
        "aquel",
        "aquella",
        "yo",
        "tú",
        "él",
        "ella",
        "nosotros",
        "vosotros",
        "ellos",
        "ellas",
        "mi",
        "tu",
        "mis",
        "tus",
        "nuestro",
        "vuestro",
        "nuestra",
        "vuestra",
        "son",
        "ser",
        "estar",
        "están",
        "fue",
        "sido",
        "sería",
        "tiene",
        "tienen",
        "tuvo",
        "tendrán",
        "sea",
        "sean",
        "todas",
        "todos",
        "toda",
        "todo",
        "ambos",
        "cada",
        "cuánto",
        "cuánta",
        "cuántos",
        "cuántas",
        # Verbos de petición comunes en preguntas RAG
        "dame",
        "dime",
        "muestra",
        "muéstrame",
        "mostrame",
        "lista",
        "listar",
        "busca",
        "buscar",
        "encuentra",
        "información",
        "info",
        "quiero",
        "necesito",
        "saber",
        "conocer",
        # Conectores de tema ("...relacionadas con X", "...sobre Y") que
        # sobreviven al filtro de longitud pero no aportan señal y, bajo
        # semántica OR, arrastran documentos irrelevantes.
        "relacionada",
        "relacionadas",
        "relacionado",
        "relacionados",
        "relativa",
        "relativas",
        "relativo",
        "relativos",
        "referente",
        "referentes",
        "acerca",
        "respecto",
        "vinculada",
        "vinculadas",
        "vinculado",
        "vinculados",
        # Términos que *definen* el corpus (un buscador de licitaciones: estas
        # palabras son el equivalente de buscar "email" dentro del buzón —
        # presentes en casi todo, no discriminan y saturan el OR).
        "licitación",
        "licitacion",
        "licitaciones",
        "expediente",
        "expedientes",
        "importe",
        "total",
    }
)


def extract_keywords(query: str) -> list[str]:
    """Extrae los tokens significativos de una query en lenguaje natural.

    Elimina metacaracteres, pasa a minúsculas, filtra stopwords y tokens de
    <=2 caracteres, y deduplica conservando los términos más largos (heurística
    barata de especificidad). Lo usa el último recurso LIKE de ``/ask``
    (``search_like_for_ask``).
    """
    cleaned = re.sub(r'["*+\-():\^/¿¡!?,.;]', " ", query).lower()
    tokens = [t for t in cleaned.split() if len(t) > 2 and t not in FTS5_STOPWORDS]
    if not tokens:
        return []
    return sorted(set(tokens), key=len, reverse=True)[:12]
