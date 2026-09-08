"""El diccionario de tecnologías vigente, venga de donde venga (C5.6, D28).

Qué resuelve
------------
Añadir una keyword era un PR, una revisión, un merge y un despliegue. Mientras
tanto, los expedientes que la llevaban entraban al corpus sin etiqueta — o, en
las fuentes donde el filtro decide qué se persiste (PSCP, Euskadi, los RSS), no
entraban en absoluto. Una keyword que falta no es una etiqueta que falta: es un
expediente que no está.

De dónde sale el diccionario
----------------------------
De ``tecnologias_keywords`` (``v126``) si tiene filas activas; de
``config/keywords.py`` si no. Ese orden, y no al revés:

- Una instalación limpia arranca con la semilla y funciona sin sembrar nada.
- Una base sembrada manda, que es lo que hace que editar no requiera desplegar.
- Un fallo de base de datos cae a la semilla. Un diccionario vacío **no** es «no
  filtres nada»: es «no persistas nada», y esa no puede ser la respuesta a una
  caída de BD.

La caché
--------
El diccionario se lee en el camino caliente de la ingesta —una vez por aviso— y
consultarlo cada vez sería una consulta por fila. Se cachea en memoria con un
TTL corto: sesenta segundos son el retardo máximo entre guardar una keyword en
``/ops`` y verla aplicada, que para esto es inmediato, y el coste es una consulta
por minuto y proceso.

``invalidar()`` la vacía en el proceso que escribe; los demás la renuevan al
caducar. No hace falta más: el diccionario no es un dato transaccional y una
ventana de un minuto no rompe nada — el mismo aviso lo vuelve a ver la siguiente
pasada.
"""

from __future__ import annotations

import hashlib
import json
import threading
import time

from observability.logging import get_logger

log = get_logger(__name__)

#: Segundos que vive la copia en memoria. Ver el docstring.
TTL_SEGUNDOS = 60.0

_lock = threading.Lock()
_cache: dict[str, list[str]] | None = None
_cache_en: float = 0.0
_origen: str = "semilla"


def semilla() -> dict[str, list[str]]:
    """El diccionario de ``config/keywords.py``, que es código y no dato."""
    from config.keywords import TECHNOLOGY_KEYWORDS

    return {tecnologia: list(keywords) for tecnologia, keywords in TECHNOLOGY_KEYWORDS.items()}


#: El aviso de «no hay BD» se da una vez por proceso. Sin esto, un entorno sin
#: base —tests, un CLI de análisis— imprimiría una traza por cada aviso
#: filtrado, y el ruido acabaría escondiendo el fallo que sí importa.
_avisado_sin_bd = False


def _desde_bd() -> dict[str, list[str]] | None:
    """Lo activo en la tabla, o ``None`` si no hay tabla, no hay filas o falla."""
    global _avisado_sin_bd
    try:
        from db.repositories.tecnologias_keywords import TecnologiaKeywordRepository

        filas = TecnologiaKeywordRepository().cargar_activas()
    except Exception as exc:
        if not _avisado_sin_bd:
            _avisado_sin_bd = True
            log.info("tech_dictionary_desde_semilla", motivo=str(exc)[:120])
        return None
    return filas or None


def vigente(*, refrescar: bool = False) -> dict[str, list[str]]:
    """Diccionario efectivo ``{tecnologia: [keywords]}``.

    ``refrescar=True`` salta la caché: lo usan la vista previa de ``/ops`` y los
    tests, que necesitan ver el efecto inmediato de lo que acaban de escribir.
    """
    global _cache, _cache_en, _origen
    ahora = time.monotonic()
    with _lock:
        if not refrescar and _cache is not None and (ahora - _cache_en) < TTL_SEGUNDOS:
            return _cache
    de_bd = _desde_bd()
    efectivo = de_bd if de_bd is not None else semilla()
    with _lock:
        _cache = efectivo
        _cache_en = time.monotonic()
        _origen = "bd" if de_bd is not None else "semilla"
    return efectivo


def origen() -> str:
    """``bd`` o ``semilla``: de dónde salió lo que hay cacheado.

    Lo enseña ``/ops``. Un panel que deja editar el diccionario sin decir que lo
    que se está aplicando es la semilla —porque la tabla está vacía— hace perder
    una tarde a quien no entiende por qué su cambio no hace nada.
    """
    if _cache is None:
        vigente()
    return _origen


def invalidar() -> None:
    """Olvida la copia cacheada. La llama quien escribe en el diccionario."""
    global _cache, _cache_en
    with _lock:
        _cache = None
        _cache_en = 0.0


def huella(diccionario: dict[str, list[str]] | None = None) -> str:
    """Hash canónico del diccionario: la parte de ``filter_version`` que cambia.

    Se normaliza —minúsculas, sin duplicados, ordenado— para que reordenar la
    lista o cambiar una mayúscula **no** produzca una versión nueva. Un
    ``filter_version`` que cambia sin que cambie el filtro rompe la comparación
    de series históricas, que es justo lo que ese campo existe para permitir.
    """
    fuente = diccionario if diccionario is not None else vigente()
    canonico = {
        tecnologia: sorted({k.casefold() for k in keywords})
        for tecnologia, keywords in sorted(fuente.items())
    }
    payload = json.dumps(canonico, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()[:12]


# ── Edición desde /ops ──────────────────────────────────────────────────────


def sembrar_si_vacio() -> int:
    """Vuelca ``config/keywords.py`` en la tabla si está vacía. Devuelve filas nuevas.

    Idempotente y **no reactiva** lo que alguien retiró: si la semilla pudiera
    resucitar keywords, cada despliegue desharía las decisiones del equipo.
    """
    from db.repositories.tecnologias_keywords import TecnologiaKeywordRepository

    nuevas = TecnologiaKeywordRepository().sembrar(semilla())
    if nuevas:
        invalidar()
    return nuevas


def previsualizar(keyword: str, *, dias: int = 90) -> dict[str, object]:
    """«Esta keyword añadiría N expedientes de los últimos 90 días» (C5.6).

    Es la pregunta que hay que poder responder **antes** de aplicar el cambio.
    Sin ella, ampliar el diccionario es una apuesta, y la que sale mal —una
    keyword demasiado genérica— mete miles de filas de ruido en el corpus y no
    se nota hasta que alguien mira una gráfica rara.
    """
    from db.repositories.tecnologias_keywords import TecnologiaKeywordRepository

    return dict(TecnologiaKeywordRepository().impacto(keyword, dias=dias))


def guardar_keyword(
    *,
    tecnologia: str,
    keyword: str,
    activa: bool,
    user_id: int | None = None,
) -> dict[str, object]:
    """Añade o retira una keyword, con el impacto medido en el registro de auditoría.

    El `audit_log` guarda **el delta de expedientes**, no sólo qué se tocó: seis
    meses después, «se añadió *hcm cloud*» no explica nada y «se añadió *hcm
    cloud*, +38 expedientes en 90 días» sí. Es también lo que permite revertir
    con criterio.

    Cambiar el diccionario cambia ``filter_version`` para las filas nuevas, así
    que el linaje separa solo lo filtrado con un criterio del filtrado con otro.
    """
    from db.audit import log_event
    from db.repositories.tecnologias_keywords import TecnologiaKeywordRepository

    repo = TecnologiaKeywordRepository()
    impacto = repo.impacto(keyword)
    fila = repo.upsert(tecnologia=tecnologia, keyword=keyword, activa=activa, user_id=user_id)
    if fila is None:
        raise ValueError("La keyword no puede estar vacía.")
    invalidar()
    version_nueva = huella(vigente(refrescar=True))
    log_event(
        event_type="tecnologias.keyword_updated",
        user_key=f"user:{user_id}" if user_id else "system",
        resource=f"tecnologia:{tecnologia}",
        detail={
            "keyword": fila["keyword"],
            "activa": activa,
            "impacto_90d": impacto,
            "filter_version": version_nueva,
        },
    )
    return {**fila, "impacto_90d": impacto, "filter_version": version_nueva}
