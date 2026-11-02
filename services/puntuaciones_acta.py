"""Lee las puntuaciones por licitador del acta de la mesa y las guarda (v169).

Tres entradas. Las dos primeras, sin contexto de tenant (el acta es dato de mercado):

* :func:`encolar_pendientes` la llama el cierre de la pasada
  (``scheduler/pipeline_runs.py``) tras el aviso de adjudicaciones. Recorre los
  expedientes de PLACSP que alguien sigue, ya adjudicados, cuya lectura del acta
  falta, es de otra versión o falló: si PLACSP no publicó ningún documento
  ``acta`` deja escrito ``sin_acta`` (así no se vuelve a mirar hasta que llegue
  uno) y, si lo hay, encola un job ``puntuaciones_acta`` por expediente. Los de
  otras fuentes (PSCP, TED…) no entran: no ingieren actas y no tienen fila.
* :func:`extraer_puntuaciones` es el cuerpo de ese job
  (``scheduler/worker.py::ejecutar_puntuaciones_acta``): descarga las actas,
  elige las páginas que parecen traer la tabla, hace **una** llamada al modelo y
  guarda solo las filas cuya cita está literalmente en el acta (ADR-014; las
  reglas viven en ``services/puntuaciones_acta_reglas``).
* :func:`puntuaciones_de_pursuit` y :func:`validar_fila_acta` son la lectura de la
  ficha de la oportunidad (``services/pursuits.py``): arman la tabla por lote con
  su fila ganadora, la propia y la diferencia, y comprueban la fila que una
  persona confirma como suya.

Qué queda escrito
-----------------
Siempre una fila de ``acta_extracciones`` con el resultado, que es lo que le
dice a la ficha si un expediente está sin leer, leído y vacío, o roto:

* ``ok``: hay filas con cita verificable.
* ``sin_tabla``: el acta se leyó y no trae puntuaciones por licitador (o está
  escaneada, o ninguna fila del modelo sobrevivió a la validación). No se
  reintenta, salvo que al expediente le queden actas publicables sin descargar
  (se leen ``_MAX_ACTAS`` por pasada): con ellas la tabla puede estar en otra.
  Si no, repetir la lectura daría lo mismo.
* ``error``: la descarga o el modelo fallaron. El job **relanza** la excepción
  después de dejar la fila: la cola solo reintenta (con su backoff) lo que lanza,
  y la próxima pasada vuelve a encolar los ``error``.

El modelo es siempre el que se pasa (``settings.PLIEGO_FACTS_MODEL`` al encolar)
y sin fallback de proveedor: la fila guarda ``model`` y un cambio silencioso la
haría mentir sobre quién leyó el acta.

Los imports de RAG y de LLM son diferidos a propósito: ``services/pursuits.py``
importa este módulo y no debe arrastrar el cliente del modelo al arrancar la API.
"""

from __future__ import annotations

import json
import threading
from collections.abc import Sequence
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Final

from config.settings import settings
from db.repositories.condiciones_oficiales import CondicionesOficialesRepository
from db.repositories.documentos import TIPO_ACTA, DocumentosRepository
from db.repositories.puntuaciones_acta import (
    ActaStatus,
    PuntuacionesActaRepository,
    PuntuacionNueva,
    PuntuacionRow,
)
from db.repositories.pursuits import FilaActaEventRow, PursuitRepository
from observability.logging import get_logger
from services.jobs import TIPO_PUNTUACIONES_ACTA, enqueue
from services.normalization import fold_text, normalize_company
from shared.dto import (
    CriterioPuntuado,
    DiferenciaCriterio,
    FilaActaRef,
    FilaPuntuacion,
    PuntuacionesActa,
    PuntuacionesLote,
)

if TYPE_CHECKING:
    from services.puntuaciones_acta_reglas import CriterioCalculo, DiferenciaCalculo

log = get_logger(__name__)

#: Se sube al cambiar la pregunta o las reglas de validación: los expedientes
#: leídos con otra versión vuelven a la cola (``expedientes_pendientes``).
EXTRACTION_VERSION: Final = "acta-puntuaciones-v1"
#: Actas que se descargan por lectura (la mesa suele levantar una o dos). Las
#: demás de un expediente con más siguen ``pending``: si esta lectura no
#: encontró la tabla (``sin_tabla``) el expediente vuelve a la cola mientras
#: quede alguna (``PuntuacionesActaRepository.expedientes_pendientes``). Entran
#: por ``prioridad_de_acta``: las que puntúan antes que las resoluciones.
_MAX_ACTAS: Final = 3
#: Tope propio de la llamada al modelo. Un job que lo supera falla por tiempo en
#: vez de dejar el lock del worker caducar con la llamada colgada.
_TOPE_LLM_SEGUNDOS: Final = 300
_MAX_TOKENS: Final = 4000

_SIN_TEXTO: Final = "El acta no tiene texto extraíble (escaneada); falta OCR"
_NO_SOPORTADO: Final = "El acta está en un formato no soportado; no se puede leer"
#: ``documentos.status`` que no cambia solo: volver a descargar no lo arregla. Los
#: demás (``pending``, ``downloaded``, ``error``) sí se reintentan.
_ESTADOS_SIN_TEXTO: Final = frozenset({"sin_texto", "unsupported"})
_SIN_SENALES: Final = (
    "Ninguna página del acta tiene las señales de una tabla de puntuaciones "
    "(«puntuación», «total», «sobre N puntos»)"
)

#: Viaja como ``question`` en modo ``extraction`` (tope ``MAX_INTERNAL_QUESTION_LEN``).
#: El JSON que pide es el de ``RespuestaActa``; lo que el modelo no puede
#: sostener con una cita se tira después, no se corrige.
_PREGUNTA_ACTA: Final = """
Las páginas son de un acta de la mesa de contratación que puntúa a los licitadores.
Devuelve un único objeto JSON con esta forma exacta:
{"lotes": [{"lote": "LOTE 1", "filas": [{"licitador": "...", "criterios": [{"nombre": "...",
"puntos": 0, "maximo": 0}], "total": 0, "excluida": false, "cita": "...", "pagina": 0,
"documento_id": 0}]}]}
lotes: un elemento por lote del acta, con lote tal como aparece ("LOTE 1"); si el acta no
distingue lotes, uno solo con lote null.
filas: una fila por licitador y lote, incluidos los excluidos, que llevan excluida: true y
las cifras que el acta les dé (o null). No inventes licitadores que el acta no puntúe.
criterios: uno por criterio de la tabla, con nombre tal como lo titula el acta, los puntos
que obtiene ese licitador y maximo, el máximo del criterio ("sobre 30 puntos" es maximo 30).
total: la puntuación total del licitador.
Copia las cifras tal como se leen en el acta, sin calcularlas, sumarlas ni corregirlas; null
si una cifra no se lee.
cita: copiada literalmente de la página, de hasta 300 caracteres, con el nombre del licitador
y su total: la fila de la tabla, no el párrafo entero. No la reescribas ni la resumas.
pagina y documento_id: los números M y N de la cabecera [doc:N p.M] de la página de la que
sale la cita.
Si el acta no trae una tabla de puntuaciones por licitador, devuelve {"lotes": []}.
""".strip()


def encolar_pendientes(*, limit: int = 200) -> int:
    """Deja en marcha la lectura de las actas que tocan. Devuelve cuántos expedientes trató.

    Por cada expediente de :meth:`PuntuacionesActaRepository.expedientes_pendientes`:
    sin documento ``acta`` escribe ``sin_acta`` (sin job ni modelo), con él encola
    el job. Cuenta los dos casos, también el job que la cola deduplicó por estar
    ya en curso. Idempotente: un expediente tratado no vuelve a salir hasta que
    algo cambie (otra versión, un ``error``, un acta que llega tras un ``sin_acta``,
    un ``sin_tabla`` con actas todavía por descargar).

    Sin contexto de tenant: lee los ``pursuits`` de todas las organizaciones, así
    que el job se encola con ``organization_id=None``.
    """
    repo = PuntuacionesActaRepository()
    pendientes = repo.expedientes_pendientes(extraction_version=EXTRACTION_VERSION, limit=limit)
    for pendiente in pendientes:
        licitacion_id = pendiente["licitacion_id"]
        if pendiente["tiene_acta"]:
            enqueue(
                TIPO_PUNTUACIONES_ACTA,
                {"licitacion_id": licitacion_id, "model": settings.PLIEGO_FACTS_MODEL},
                organization_id=None,
            )
        else:
            repo.guardar(
                licitacion_id,
                status="sin_acta",
                extraction_version=EXTRACTION_VERSION,
                model=None,
                documentos_leidos=0,
                error_detail=None,
                filas=[],
            )
    if pendientes:
        log.info("puntuaciones_acta_encoladas", expedientes=len(pendientes))
    return len(pendientes)


@dataclass
class _Lectura:
    """Lo que dejó la lectura del acta, antes de escribirlo."""

    status: ActaStatus
    documentos_leidos: int
    #: ``None`` si no se llegó a llamar a ningún modelo.
    model: str | None = None
    error_detail: str | None = None
    filas: list[PuntuacionNueva] = field(default_factory=list)


def extraer_puntuaciones(licitacion_id: str, *, model: str) -> ActaStatus:
    """Lee las actas del expediente, valida las filas contra su cita y las guarda.

    Devuelve ``ok`` o ``sin_tabla``. Ante cualquier fallo (descarga, modelo,
    tope de tiempo, JSON ilegible, escritura) deja ``error`` con el motivo, sin
    filas, y **relanza** para que la cola reintente. El resultado reemplaza
    siempre al anterior del expediente (``PuntuacionesActaRepository.guardar``).
    """
    repo = PuntuacionesActaRepository()
    try:
        lectura = _leer_acta(licitacion_id, model)
        repo.guardar(
            licitacion_id,
            status=lectura.status,
            extraction_version=EXTRACTION_VERSION,
            model=lectura.model,
            documentos_leidos=lectura.documentos_leidos,
            error_detail=lectura.error_detail,
            filas=lectura.filas,
        )
    except Exception as exc:
        log.warning("puntuaciones_acta_fallida", licitacion_id=licitacion_id, error=str(exc)[:200])
        repo.guardar(
            licitacion_id,
            status="error",
            extraction_version=EXTRACTION_VERSION,
            model=model,
            documentos_leidos=0,
            error_detail=str(exc)[:500],
            filas=[],
        )
        raise
    log.info(
        "puntuaciones_acta_leidas",
        licitacion_id=licitacion_id,
        status=lectura.status,
        filas=len(lectura.filas),
    )
    return lectura.status


def _leer_acta(licitacion_id: str, model: str) -> _Lectura:
    """Del expediente a las filas validadas; lanza si no se pudo leer el acta."""
    # Diferidos (ver la nota del módulo): las reglas importan ``fact_sheet`` y este
    # el cliente del modelo. Los tests parchean ``services.rag.fact_sheet.<nombre>``.
    from llm.json_utils import extract_json_object
    from services.puntuaciones_acta_reglas import (
        RespuestaActa,
        filas_validadas,
        prioridad_de_acta,
        seleccionar_paginas,
    )
    from services.rag.fact_sheet import ensure_documents_ready

    solo_actas = frozenset({TIPO_ACTA})
    descarga = ensure_documents_ready(
        licitacion_id, tipos=solo_actas, max_documentos=_MAX_ACTAS, orden=prioridad_de_acta
    )
    paginas = DocumentosRepository().list_pages_by_licitacion(licitacion_id, tipos=solo_actas)
    if not paginas:
        motivo = _motivo_sin_texto(licitacion_id)
        if motivo:
            return _Lectura("sin_tabla", 0, error_detail=motivo)
        raise RuntimeError(f"No se pudo descargar ni leer el acta del expediente ({descarga})")

    documentos = len({pagina["documento_id"] for pagina in paginas})
    criterios = CondicionesOficialesRepository().get(licitacion_id)["criterios"]
    seleccionadas = seleccionar_paginas(
        paginas, [str(c["descripcion"]) for c in criterios if c.get("descripcion")]
    )
    if not seleccionadas:
        return _Lectura("sin_tabla", documentos, error_detail=_SIN_SENALES)

    raw = _preguntar_al_modelo(licitacion_id, seleccionadas, model)
    respuesta = RespuestaActa.model_validate(extract_json_object(raw))
    # Contra todas las páginas del acta y no solo las enviadas: una cita que el modelo
    # atribuye a la página contigua se corrige si el texto está allí (como en la ficha).
    filas = filas_validadas(respuesta, paginas, criterios)
    if filas:
        return _Lectura("ok", documentos, model, filas=filas)
    propuestas = sum(len(lote.filas) for lote in respuesta.lotes)
    if propuestas:
        detalle = (
            f"El modelo devolvió {propuestas} fila(s) y ninguna pasó la validación contra "
            "el acta (cita literal, lote)"
        )
    else:
        detalle = "El modelo no encontró una tabla de puntuaciones por licitador en el acta"
    return _Lectura("sin_tabla", documentos, model, detalle)


def _motivo_sin_texto(licitacion_id: str) -> str | None:
    """Por qué el acta no tiene nada que leer, si ningún reintento lo va a cambiar.

    Se lee el estado guardado de los documentos y no el recuento de la descarga:
    un acta ya marcada ``sin_texto`` no se vuelve a intentar y su recuento sale a
    cero (también tras subir ``EXTRACTION_VERSION`` o si el worker murió entre
    marcarla y guardar), y ``unsupported`` ni siquiera cuenta como ``sin_texto``.
    Solo si hay actas publicadas y todas están en un estado terminal; con una
    pendiente, en error o sin publicar, ``None``: eso sí es un fallo que reintentar.
    """
    estados = [
        fila.get("status")
        for fila in DocumentosRepository().list_by_licitacion(licitacion_id)
        if fila.get("tipo") == TIPO_ACTA and not fila.get("sin_publicar")
    ]
    if not estados or any(estado not in _ESTADOS_SIN_TEXTO for estado in estados):
        return None
    return _SIN_TEXTO if "sin_texto" in estados else _NO_SOPORTADO


def _preguntar_al_modelo(licitacion_id: str, paginas: list[dict[str, object]], model: str) -> str:
    """Una llamada al modelo con tope de tiempo; ``TimeoutError`` si lo vence."""
    from services.rag.fact_sheet import _llamar_modelo

    tope = f"La lectura del acta superó el tope de {_TOPE_LLM_SEGUNDOS} s"
    stop = threading.Event()
    temporizador = threading.Timer(_TOPE_LLM_SEGUNDOS, stop.set)
    temporizador.daemon = True
    temporizador.start()
    try:
        raw = _llamar_modelo(
            _PREGUNTA_ACTA,
            paginas,
            licitacion_id=licitacion_id,
            model=model,
            keywords=("puntuación", "total"),
            max_tokens=_MAX_TOKENS,
            stop=stop,
        )
    except Exception as exc:
        # Con ``stop`` activo el cliente termina sin tokens y ``_llamar_modelo`` lo
        # cuenta como «respuesta vacía»: lo que falló fue el tiempo, no el proveedor.
        if stop.is_set():
            raise TimeoutError(tope) from exc
        raise
    finally:
        temporizador.cancel()
    if stop.is_set():
        raise TimeoutError(tope)
    return raw


# --- Lectura para la ficha -----------------------------------------------------


@dataclass
class _Licitador:
    """Un licitador de un lote tal como sale de las filas de ``acta_puntuaciones``."""

    nombre: str
    normalizado: str
    excluida: bool = False
    total: float | None = None
    #: ``(documento_id, pagina)`` de la fila del total.
    cita_total: tuple[int, int] | None = None
    criterios: list[CriterioCalculo] = field(default_factory=list)


def puntuaciones_de_pursuit(
    *,
    licitacion_id: str,
    organization_id: int,
    pursuit_id: int,
    lote_pursuit: str | None,
) -> PuntuacionesActa | None:
    """Las puntuaciones del acta de la oportunidad tal como las enseña la ficha.

    ``None`` si el expediente no tiene ningún documento ``acta`` ni lectura: no
    hay nada que decir. Con acta pero sin lectura, ``pendiente``. Con lectura, su
    estado; solo ``ok`` trae lotes (spec §6.1).

    Si ``lote_pursuit`` es un lote que el acta trae, solo ese lote; si no (la
    oportunidad es del expediente entero, o el acta no lo nombra), todos: ocultar
    la tabla porque los números de lote no casan sería peor que enseñar de más.

    La fila propia es la que una persona confirmó (el último evento
    ``fila_acta_confirmada`` del lote, si la fila sigue en el acta) y, si no, la
    que propone el nombre de la organización. Una confirmación cuya fila ya no
    está (el acta se volvió a leer) no deja el lote sin fila propia: vuelve a la
    propuesta.

    Lee la organización y la oportunidad: se llama con el ámbito ya resuelto.
    """
    repo = PuntuacionesActaRepository()
    extraccion = repo.get_extraccion(licitacion_id)
    if extraccion is None:
        if repo.tiene_actas(licitacion_id):
            return PuntuacionesActa(estado="pendiente", lotes=[])
        return None
    if extraccion["status"] != "ok":
        return PuntuacionesActa(estado=extraccion["status"], lotes=[])

    # Diferido: las reglas importan ``fact_sheet`` (ver la nota del módulo).
    from services.puntuaciones_acta_reglas import normalizar_lote

    grupos = _agrupar(repo.list_puntuaciones(licitacion_id))
    lote_oportunidad = normalizar_lote(lote_pursuit)
    if lote_oportunidad is not None and lote_oportunidad in grupos:
        grupos = {lote_oportunidad: grupos[lote_oportunidad]}

    adjudicatarios = [
        (normalizar_lote(a["lote_numero"]), nombre)
        for a in repo.adjudicatarios_por_lote(licitacion_id)
        if (nombre := normalize_company(a["nombre"]))
    ]
    nombres_organizacion = {
        nombre
        for crudo in repo.nombres_de_organizacion(organization_id)
        if (nombre := normalize_company(crudo))
    }
    confirmadas = _confirmaciones(PursuitRepository().fila_acta_events(organization_id, pursuit_id))
    return PuntuacionesActa(
        estado="ok",
        lotes=[
            _lote(
                lote, list(licitadores.values()), adjudicatarios, nombres_organizacion, confirmadas
            )
            for lote, licitadores in grupos.items()
        ],
    )


def validar_fila_acta(licitacion_id: str, ref: FilaActaRef) -> bool:
    """Si ``ref`` es una fila de las puntuaciones leídas del acta del expediente.

    El lote se compara tal como lo guarda la extracción (``normalizar_lote``
    aplicado al escribir): la interfaz devuelve el que recibió.
    """
    return any(
        fila["lote_numero"] == ref.lote_numero
        and fila["licitador_normalizado"] == ref.licitador_normalizado
        for fila in PuntuacionesActaRepository().list_puntuaciones(licitacion_id)
    )


def _agrupar(filas: Sequence[PuntuacionRow]) -> dict[str | None, dict[str, _Licitador]]:
    """Las filas de BD por lote y licitador, en el orden del acta.

    Por licitador hay una fila por criterio y una con ``criterio`` ``None`` que es
    el total.
    """
    from services.puntuaciones_acta_reglas import CriterioCalculo

    grupos: dict[str | None, dict[str, _Licitador]] = {}
    for fila in filas:
        licitadores = grupos.setdefault(fila["lote_numero"], {})
        clave = fila["licitador_normalizado"]
        if clave not in licitadores:
            licitadores[clave] = _Licitador(nombre=fila["licitador_nombre"], normalizado=clave)
        licitador = licitadores[clave]
        licitador.excluida = licitador.excluida or fila["excluida"]
        if fila["criterio"] is None:
            licitador.total = fila["puntos"]
            licitador.cita_total = (fila["documento_id"], fila["pagina"])
        else:
            licitador.criterios.append(
                CriterioCalculo(
                    nombre=fila["criterio"],
                    puntos=fila["puntos"],
                    maximo=fila["puntos_max"],
                    es_precio=fila["es_precio"],
                    documento_id=fila["documento_id"],
                    pagina=fila["pagina"],
                    cita=fila["cita"],
                )
            )
    return grupos


def _confirmaciones(eventos: Sequence[FilaActaEventRow]) -> dict[str | None, str]:
    """Por lote, el ``licitador_normalizado`` del último evento ``fila_acta_confirmada``.

    Los eventos llegan en orden de escritura, así que el último de cada lote pisa
    a los anteriores. Un payload ilegible se ignora: lo escribe este servicio, pero
    el ledger es append-only y una fila rota no puede tumbar la ficha.
    """
    confirmadas: dict[str | None, str] = {}
    for evento in eventos:
        try:
            payload: object = json.loads(evento["payload_json"])
        except ValueError:
            continue
        if not isinstance(payload, dict):
            continue
        lote, licitador = payload.get("lote_numero"), payload.get("licitador_normalizado")
        if isinstance(licitador, str) and licitador and (lote is None or isinstance(lote, str)):
            confirmadas[lote] = licitador
    return confirmadas


def _ordenadas(licitadores: list[_Licitador]) -> list[_Licitador]:
    """Las no excluidas por total descendente (sin total detrás) y las excluidas al final.

    ``sorted`` es estable: a igualdad de total manda el orden del acta.
    """
    activas = sorted(
        (lic for lic in licitadores if not lic.excluida),
        key=lambda lic: (lic.total is None, -(lic.total or 0.0)),
    )
    return [*activas, *(lic for lic in licitadores if lic.excluida)]


def _lote(
    lote: str | None,
    licitadores: list[_Licitador],
    adjudicatarios: Sequence[tuple[str | None, str]],
    nombres_organizacion: set[str],
    confirmadas: dict[str | None, str],
) -> PuntuacionesLote:
    """La tabla de un lote con su ganadora, su fila propia, la diferencia y el motivo."""
    from services.puntuaciones_acta_reglas import (
        FilaCalculo,
        diferencia,
        fila_ganadora,
        fila_propia,
        motivo_sugerido,
    )

    filas = _ordenadas(licitadores)
    calculos = [
        FilaCalculo(
            licitador=lic.nombre,
            licitador_normalizado=lic.normalizado,
            total=lic.total,
            excluida=lic.excluida,
            criterios=tuple(lic.criterios),
        )
        for lic in filas
    ]
    # Un adjudicatario sin lote vale para todos; un acta sin lotes, también para cualquiera.
    de_este_lote = {
        nombre
        for lote_adjudicado, nombre in adjudicatarios
        if lote_adjudicado is None or lote is None or lote_adjudicado == lote
    }
    ganadora, es_mayor_puntuacion = fila_ganadora(calculos, de_este_lote)

    propia = fila_propia(calculos, nombres_organizacion)
    confirmada = confirmadas.get(lote)
    indice_confirmada = next(
        (i for i, lic in enumerate(filas) if confirmada and lic.normalizado == confirmada), None
    )
    if indice_confirmada is not None:
        propia = indice_confirmada

    diferencias: list[DiferenciaCriterio] = []
    motivo = None
    if propia is not None and ganadora is not None and propia != ganadora:
        motivo = motivo_sugerido(calculos[propia], calculos[ganadora], propia_es_ganadora=False)
        diferencias = [
            _diferencia_dto(d, filas[ganadora])
            for d in diferencia(calculos[propia], calculos[ganadora])
        ]

    return PuntuacionesLote(
        lote_numero=lote,
        filas=[_fila_dto(lic) for lic in filas],
        fila_ganadora=ganadora,
        ganadora_es_mayor_puntuacion=es_mayor_puntuacion,
        fila_propia=propia,
        fila_propia_confirmada=indice_confirmada is not None,
        diferencia=diferencias,
        motivo_sugerido=motivo,
    )


def _fila_dto(licitador: _Licitador) -> FilaPuntuacion:
    return FilaPuntuacion(
        licitador=licitador.nombre,
        licitador_normalizado=licitador.normalizado,
        total=licitador.total,
        excluida=licitador.excluida,
        criterios=[
            CriterioPuntuado(
                nombre=c.nombre,
                puntos=c.puntos,
                maximo=c.maximo,
                es_precio=c.es_precio,
                documento_id=c.documento_id,
                pagina=c.pagina,
                cita=c.cita,
            )
            for c in licitador.criterios
        ],
    )


def _diferencia_dto(calculo: DiferenciaCalculo, ganadora: _Licitador) -> DiferenciaCriterio:
    """La diferencia con la página del acta donde la ganadora tiene esa cifra."""
    cita: tuple[int, int] | None
    if calculo.criterio is None:
        cita = ganadora.cita_total
    else:
        buscado = fold_text(calculo.criterio)
        cita = next(
            (
                (c.documento_id, c.pagina)
                for c in ganadora.criterios
                if fold_text(c.nombre) == buscado
            ),
            None,
        )
    return DiferenciaCriterio(
        criterio=calculo.criterio,
        diferencia=calculo.diferencia,
        maximo=calculo.maximo,
        es_precio=calculo.es_precio,
        documento_id=cita[0] if cita else None,
        pagina=cita[1] if cita else None,
    )
