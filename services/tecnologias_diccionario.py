"""El diccionario de tecnologías vigente (C5.6, D28).

`config/keywords.py` era **código**: añadir «SAP BTP» exigía commit, revisión,
merge y despliegue, para una lista de palabras que decide qué ve el producto
entero. Ahora la fuente es `tecnologias_keywords` (v126) y la semilla es el
respaldo.

Las tres reglas del módulo
--------------------------
1. **La tabla manda; la semilla es el suelo.** Si la tabla está vacía o no se
   puede leer, se usa `config/keywords.py`. Un entorno nuevo, un test o una BD
   caída siguen teniendo diccionario: quedarse sin él no degradaría el filtro,
   lo apagaría — y un filtro apagado no descarta nada, mete el censo entero.
2. **La versión es el hash del contenido**, no un contador. Dos filas ingeridas
   con el mismo `filter_version` se filtraron con el mismo diccionario, viniera
   de donde viniera.
3. **Lo derivado se memoiza por versión**, no por tiempo. Los patrones
   compilados son caros y el diccionario cambia poco; atarlos a la versión hace
   que un cambio los invalide exactamente cuando toca, sin TTL que adivinar.

Sobre la caché y su ventana
---------------------------
El diccionario se releé como mucho cada `TTL_SEGUNDOS`. Es el precio de no ir a
la base de datos en cada texto que se filtra —el scraper llama a esto cientos de
miles de veces por pasada—, y significa que una edición desde `/ops` tarda hasta
un minuto en verse en todos los procesos. Un minuto de desfase en una lista de
palabras es aceptable; una consulta por documento no lo es.
"""

from __future__ import annotations

import hashlib
import json
import re
import threading
import time
from typing import Any

from observability.logging import get_logger

log = get_logger(__name__)

#: Cuánto se conserva el diccionario leído antes de volver a preguntar.
TTL_SEGUNDOS = 60.0

_lock = threading.Lock()
_cache: dict[str, Any] = {"diccionario": None, "version": None, "leido_en": 0.0}
_patrones_cache: dict[str, dict[str, re.Pattern[str]]] = {}


def semilla() -> dict[str, list[str]]:
    """El diccionario de `config/keywords.py`, que sigue siendo el respaldo."""
    from config.keywords import TECHNOLOGY_KEYWORDS

    return {tec: list(kws) for tec, kws in TECHNOLOGY_KEYWORDS.items()}


def _hash_de(diccionario: dict[str, list[str]]) -> str:
    """Hash canónico del contenido. Misma forma que `scraper/lineage.py`."""
    canonical: dict[str, object] = {
        tecnologia: sorted({kw.casefold() for kw in keywords})
        for tecnologia, keywords in sorted(diccionario.items())
    }
    canonical["__universo__"] = {"cpv_ti": ["48", "72"], "version": 1}
    payload = json.dumps(canonical, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return "keywords-" + hashlib.sha256(payload.encode("utf-8")).hexdigest()[:12]


def _leer() -> tuple[dict[str, list[str]], str]:
    from db.repositories.tecnologias_keywords import TecnologiasKeywordsRepository

    try:
        de_bd = TecnologiasKeywordsRepository().diccionario_activo()
    except Exception:
        # Caer a la semilla es la degradación correcta: que una BD caída deje el
        # filtro sin diccionario sería peor que servir uno de hace un minuto.
        #
        # Pero se registra AQUÍ y no solo en el repositorio, porque la
        # consecuencia se decide aquí: con la semilla, `filter_version` vuelve a
        # ser el hash del código y las filas que se ingieran mientras tanto
        # quedan marcadas con un linaje que no es el vigente. Sin esta traza,
        # una BD caída y un diccionario que no se ha tocado se ven igual.
        log.warning("tecnologias_diccionario_desde_semilla", exc_info=True)
        de_bd = {}
    efectivo = de_bd or semilla()
    return efectivo, _hash_de(efectivo)


def vigente(*, forzar: bool = False) -> tuple[dict[str, list[str]], str]:
    """`(diccionario, version)` efectivos, con caché de `TTL_SEGUNDOS`."""
    ahora = time.monotonic()
    with _lock:
        fresco = (
            _cache["diccionario"] is not None and (ahora - float(_cache["leido_en"])) < TTL_SEGUNDOS
        )
        if fresco and not forzar:
            diccionario = _cache["diccionario"]
            assert isinstance(diccionario, dict)
            return diccionario, str(_cache["version"])
    diccionario, version = _leer()
    with _lock:
        _cache.update({"diccionario": diccionario, "version": version, "leido_en": ahora})
    return diccionario, version


def version() -> str:
    """Hash del diccionario vigente. Es lo que `filter_version` publica."""
    return vigente()[1]


def patrones() -> dict[str, re.Pattern[str]]:
    """`{tecnologia: regex}` con límites de palabra, memoizado por versión.

    El límite de palabra es el mismo criterio de siempre: sin él, «sap» casa
    dentro de «desaparecer». La memoización va por versión y no por tiempo
    porque compilar doscientos patrones en cada texto sería el coste dominante
    del filtro, y porque así un cambio del diccionario los invalida exactamente
    cuando cambia y no un minuto después.
    """
    diccionario, ver = vigente()
    cacheado = _patrones_cache.get(ver)
    if cacheado is not None:
        return cacheado
    compilados = {
        tec: re.compile(
            r"\b(" + "|".join(re.escape(k) for k in keywords) + r")\b",
            flags=re.IGNORECASE,
        )
        for tec, keywords in diccionario.items()
        if keywords
    }
    with _lock:
        # Solo se guarda la versión vigente: el diccionario cambia poco y
        # guardar el histórico haría crecer el proceso sin que nadie lo mire.
        _patrones_cache.clear()
        _patrones_cache[ver] = compilados
    return compilados


def invalidar() -> None:
    """Olvida lo cacheado. La llama quien acaba de escribir en la tabla."""
    with _lock:
        _cache.update({"diccionario": None, "version": None, "leido_en": 0.0})
        _patrones_cache.clear()


def sembrar_desde_semilla() -> int:
    """Vuelca en la tabla las keywords de la semilla que falten. Idempotente.

    No vive en la migración a propósito: meter las ~200 keywords allí congelaría
    en el historial de esquema una copia que envejece sola —la semilla cambia
    con el código y la migración no se vuelve a ejecutar—. Esto se puede repetir
    tras cada cambio de la semilla.
    """
    from db.repositories.tecnologias_keywords import TecnologiasKeywordsRepository

    insertadas = TecnologiasKeywordsRepository().sembrar(semilla())
    invalidar()
    return insertadas
