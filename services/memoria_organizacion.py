"""Memoria de la organización: indexar sus adjuntos y citarlos (ADR-040).

Una organización puede marcar un adjunto como indexable
(``services/pursuit_attachments.py::marcar_indexable``). Aquí vive lo que ese
permiso pone en marcha y lo que permite:

1. **Indexar** (:func:`indexar`): el mismo camino que un pliego —texto por
   página, fragmentos con su página, embeddings— como trabajo de la cola.
2. **Citar** (:func:`citas`): fragmentos **literales** de esos documentos que
   casan con una pregunta, con el fichero, la página y la oportunidad de la que
   salen. El Investigador y el guion de oferta los enseñan junto a la cita del
   pliego.

Lo que NO hace, y por qué
-------------------------
- **No entra en el prompt de ningún modelo.** La cita es un extracto del
  documento, no una frase generada a partir de él (D33): se puede comprobar
  abriendo el fichero. De paso, el texto de una propuesta no sale hacia el
  proveedor del LLM ni puede acabar en la caché de respuestas, que es
  compartida entre organizaciones.
- **No comparte tablas con el corpus de pliegos** (``v179``): ninguna búsqueda
  de pliegos puede devolver un fragmento de aquí.

El aislamiento va en el SQL (``db/repositories/pursuit_attachments.py`` exige
la organización en el fragmento y en el adjunto) y en la RLS de la tabla, que
no deja ver nada sin ámbito. Por eso todo lo de este módulo corre dentro de
``tenant_scope``: también el worker, que no tiene petición que se lo ponga.
"""

from __future__ import annotations

import re
from collections.abc import Callable, Iterable, Sequence
from dataclasses import dataclass
from typing import Final, Literal

from pydantic import BaseModel, ConfigDict

from config.settings_memoria import memoria_org_max_bytes_por_documento, memoria_org_max_documentos
from db.repositories.pursuit_attachments import FragmentoEncontrado, PursuitAttachmentsRepository
from observability.logging import get_logger
from shared.tenant_context import tenant_scope

log = get_logger(__name__)

__all__ = [
    "MAX_CITAS",
    "TIPOS_INDEXABLES",
    "CitaOrganizacion",
    "PoliticaIndexado",
    "TextoNoExtraible",
    "citas",
    "completar_embeddings",
    "indexar",
    "politica_indexado",
    "terminos_de",
]

#: Tipos de la lista blanca de adjuntos de los que se sabe sacar texto. Un
#: subconjunto de lo que lee ``scraper.document_fetcher`` (lo comprueba
#: ``tests/test_unit_memoria_organizacion.py``): una hoja de cálculo de Office,
#: una presentación o una imagen se pueden adjuntar, pero no indexar.
TIPOS_INDEXABLES: Final[frozenset[str]] = frozenset(
    {
        "application/pdf",
        "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
        "application/vnd.oasis.opendocument.text",
        "application/vnd.oasis.opendocument.spreadsheet",
        "application/zip",
        "text/plain",
    }
)

#: Citas de documentos propios por pregunta (o por criterio del guion).
MAX_CITAS: Final = 3

#: Similitud coseno mínima para citar un fragmento por significado.
#: shortcut: 0,4 sin medir; ajustarlo cuando haya juicios de relevancia sobre
#: documentos reales (backlog, «Memoria de la organización»).
UMBRAL_SIGNIFICADO: Final = 0.4

#: Términos de la pregunta que un fragmento debe contener para citarse por
#: palabras (o todos, si la pregunta tiene menos). Con uno solo, cualquier
#: documento que diga «experiencia» acompañaría a cualquier pregunta.
COBERTURA_MINIMA: Final = 2

_MAX_TERMINOS: Final = 12
_PALABRA = re.compile(r"\w{3,}", re.UNICODE)

EstadoSinTexto = Literal["error", "unsupported", "sin_texto"]

#: ``(binario, content_type declarado) → texto de cada página``. Lo inyecta el
#: worker: la extracción vive en ``scraper/``, que está por encima de esta capa.
Extractor = Callable[[bytes, str], Sequence[str]]


class TextoNoExtraible(Exception):
    """El extractor no pudo sacar texto, y reintentarlo no lo cambiaría."""

    def __init__(self, estado: EstadoSinTexto, motivo: str) -> None:
        super().__init__(motivo)
        self.estado: EstadoSinTexto = estado


@dataclass(frozen=True, slots=True)
class PoliticaIndexado:
    """Lo que la consola dice **antes** de activar el interruptor."""

    max_documentos: int
    max_bytes: int
    tipos: tuple[str, ...]

    @property
    def disponible(self) -> bool:
        return self.max_documentos > 0


def politica_indexado() -> PoliticaIndexado:
    """Topes vigentes del indexado (configuración, no producto: ver ``config``)."""
    return PoliticaIndexado(
        max_documentos=memoria_org_max_documentos(),
        max_bytes=memoria_org_max_bytes_por_documento(),
        tipos=tuple(sorted(TIPOS_INDEXABLES)),
    )


class CitaOrganizacion(BaseModel):
    """Un extracto literal de un documento que la organización indexó.

    No lleva ``organization_id`` ni la clave del binario: quien la recibe ya es
    de la organización, y el fichero se abre por el enlace firmado de siempre
    (``GET /pursuits/adjuntos/{attachment_id}/enlace``).
    """

    model_config = ConfigDict(extra="forbid")

    attachment_id: int
    filename: str
    page_number: int | None = None
    cita: str
    #: Oportunidad de origen, para rotular la cita y enlazarla.
    pursuit_id: int
    licitacion_id: str
    licitacion_titulo: str | None = None


# ── Indexado ────────────────────────────────────────────────────────────────


def _repo() -> PursuitAttachmentsRepository:
    return PursuitAttachmentsRepository()


def fragmentar(paginas: Sequence[str]) -> tuple[list[str], list[int | None]]:
    """Fragmentos del documento y la página (desde 1) en la que empieza cada uno.

    Las páginas se unen con ``\\n``, como hace ``mark_extracted`` con los
    pliegos, y el fragmento hereda la página que contiene su primer carácter.
    """
    from services.rag.chunking import chunk_text_with_offsets, pagina_de_offset

    texto = "\n".join(paginas)
    inicios: list[tuple[int, int]] = []
    offset = 0
    for numero, pagina in enumerate(paginas, start=1):
        inicios.append((offset, numero))
        offset += len(pagina) + 1
    # Los offsets del chunker son sobre el texto ya recortado.
    desfase = len(texto) - len(texto.lstrip())
    con_offset = chunk_text_with_offsets(texto)
    return (
        [trozo for trozo, _ in con_offset],
        [pagina_de_offset(pos + desfase, inicios) for _, pos in con_offset],
    )


def indexar(
    attachment_id: int,
    organization_id: int,
    *,
    extraer: Extractor,
    ultimo_intento: bool = False,
) -> dict[str, object]:
    """Extrae, fragmenta y guarda el texto de UN adjunto indexable.

    Idempotente: un adjunto ya indexado no se toca, y un reintento sustituye
    los fragmentos enteros. Si el permiso se retiró mientras tanto, no escribe
    nada. Un documento del que no se puede sacar texto no es un fallo del job:
    queda con su estado (``unsupported``, ``sin_texto``, ``error``) y el motivo.

    Lo que sí propaga es el fallo que un reintento puede curar (el almacén o la
    base no responden); con ``ultimo_intento`` deja antes el adjunto en
    ``error``, para que la pantalla no diga «pendiente» para siempre.
    """
    with tenant_scope(organization_id):
        repo = _repo()
        fila = repo.get(attachment_id, organization_id=organization_id)
        if fila is None or not fila.get("indexable"):
            return {"attachment_id": attachment_id, "estado": "sin_permiso"}
        if fila.get("index_status") == "indexed":
            return {"attachment_id": attachment_id, "estado": "indexed", "repetido": True}
        try:
            return _indexar_fila(
                repo,
                attachment_id,
                organization_id,
                blob_key=str(fila["blob_key"]),
                content_type=str(fila["content_type"]),
                extraer=extraer,
            )
        except TextoNoExtraible as exc:
            repo.marcar_sin_texto(
                attachment_id, organization_id=organization_id, estado=exc.estado, error=str(exc)
            )
            log.info("memoria_org_sin_texto", attachment_id=attachment_id, estado=exc.estado)
            return {"attachment_id": attachment_id, "estado": exc.estado}
        except Exception:
            if ultimo_intento:
                repo.marcar_sin_texto(
                    attachment_id,
                    organization_id=organization_id,
                    estado="error",
                    error="No se pudo indexar el documento. Desactívalo y vuelve a activarlo.",
                )
            raise


def _a_listas(vectores: Iterable[Iterable[float]]) -> list[list[float]]:
    """La matriz que devuelve el motor de embeddings, como listas de ``float``."""
    return [[float(x) for x in vector] for vector in vectores]


def _indexar_fila(
    repo: PursuitAttachmentsRepository,
    attachment_id: int,
    organization_id: int,
    *,
    blob_key: str,
    content_type: str,
    extraer: Extractor,
) -> dict[str, object]:
    from config.settings import settings
    from services.embeddings import embeddings_masivos_disponibles, encode_texts
    from shared.object_store import get_object_store

    contenido = get_object_store().get(blob_key)
    if contenido is None:
        raise TextoNoExtraible("error", "El fichero ya no está en el almacén de documentos.")

    paginas = list(extraer(contenido, content_type))
    fragmentos, numeros = fragmentar(paginas)
    if not fragmentos:
        raise TextoNoExtraible("sin_texto", "El documento no tiene texto que indexar.")

    # Con solo el motor de consulta (ONNX, en el proceso de la API) el documento
    # se guarda sin vectores y ya es citable por palabras; los vectores los pone
    # `completar_embeddings` donde sí hay motor para un corpus.
    embeddings = _a_listas(encode_texts(fragmentos)) if embeddings_masivos_disponibles() else None
    guardados = repo.reemplazar_fragmentos(
        attachment_id,
        organization_id=organization_id,
        fragmentos=fragmentos,
        paginas=numeros,
        embeddings=embeddings,
        embedding_model=settings.EMBEDDING_MODEL,
        embedding_version=settings.EMBEDDING_VERSION,
    )
    if guardados is None:
        return {"attachment_id": attachment_id, "estado": "sin_permiso"}
    log.info(
        "memoria_org_indexado",
        attachment_id=attachment_id,
        organization_id=organization_id,
        paginas=len(paginas),
        fragmentos=guardados,
        con_embeddings=embeddings is not None,
    )
    return {
        "attachment_id": attachment_id,
        "estado": "indexed",
        "paginas": len(paginas),
        "fragmentos": guardados,
        "con_embeddings": embeddings is not None,
    }


def completar_embeddings(limite: int = 20) -> dict[str, int]:
    """Pone vectores a los adjuntos que se indexaron sin ellos, o con otra versión.

    Lo llama el job nocturno de embeddings, que es donde hay motor para un
    documento entero. Entra organización a organización con su ámbito: el
    listado inicial solo trae identificadores.
    """
    from config.settings import settings
    from services.embeddings import embeddings_masivos_disponibles, encode_texts

    cuenta = {"adjuntos": 0, "fragmentos": 0, "errores": 0}
    if not settings.EMBEDDING_VERSION or not embeddings_masivos_disponibles():
        return cuenta
    repo = _repo()
    for pendiente in repo.pendientes_de_embedding(settings.EMBEDDING_VERSION, limit=limite):
        attachment_id, organization_id = pendiente["id"], pendiente["organization_id"]
        try:
            with tenant_scope(organization_id):
                filas = repo.textos_de_fragmentos(attachment_id, organization_id=organization_id)
                vectores = _a_listas(encode_texts([texto for _, texto in filas])) if filas else []
                guardado = repo.guardar_embeddings(
                    attachment_id,
                    organization_id=organization_id,
                    indices=[indice for indice, _ in filas],
                    embeddings=vectores,
                    embedding_model=settings.EMBEDDING_MODEL,
                    embedding_version=settings.EMBEDDING_VERSION,
                )
        except Exception:
            cuenta["errores"] += 1
            log.warning(
                "memoria_org_embeddings_fallidos", attachment_id=attachment_id, exc_info=True
            )
            continue
        if guardado:
            cuenta["adjuntos"] += 1
            cuenta["fragmentos"] += len(filas)
    return cuenta


# ── Recuperación ────────────────────────────────────────────────────────────


def terminos_de(consulta: str) -> list[str]:
    """Palabras de la consulta para la búsqueda por palabras, sin repetir.

    Las palabras vacías no se quitan aquí: lo hace el diccionario español de
    Postgres en la propia consulta, que es el mismo que indexó los fragmentos.
    """
    vistos: list[str] = []
    for palabra in _PALABRA.findall(consulta.casefold()):
        if palabra not in vistos:
            vistos.append(palabra)
    return vistos[:_MAX_TERMINOS]


def seleccionar(
    por_significado: Sequence[FragmentoEncontrado],
    por_palabras: Sequence[FragmentoEncontrado],
    *,
    limite: int = MAX_CITAS,
) -> list[CitaOrganizacion]:
    """Elige las filas que merecen citarse y las convierte en citas.

    Primero lo que casa por significado por encima del umbral, después lo que
    casa por palabras con cobertura suficiente; una sola cita por página de
    cada documento, para que tres fragmentos solapados no ocupen las tres.
    """
    from services.rag.citas import MAX_CITA_CHARS

    candidatas = [f for f in por_significado if f["score"] >= UMBRAL_SIGNIFICADO]
    candidatas += [
        f for f in por_palabras if f["cobertura"] >= min(COBERTURA_MINIMA, f["n_terminos"]) > 0
    ]
    elegidas: list[CitaOrganizacion] = []
    vistas: set[tuple[int, int | None]] = set()
    for fila in candidatas:
        clave = (fila["attachment_id"], fila["page_number"])
        if clave in vistas:
            continue
        vistas.add(clave)
        texto = " ".join((fila["extracto"] or fila["texto"]).split())
        if not texto:
            continue
        if len(texto) > MAX_CITA_CHARS:
            texto = texto[:MAX_CITA_CHARS].rsplit(" ", 1)[0] + "…"
        elegidas.append(
            CitaOrganizacion(
                attachment_id=fila["attachment_id"],
                filename=fila["filename"],
                page_number=fila["page_number"],
                cita=texto,
                pursuit_id=fila["pursuit_id"],
                licitacion_id=fila["licitacion_id"],
                licitacion_titulo=fila["licitacion_titulo"] or None,
            )
        )
        if len(elegidas) >= limite:
            break
    return elegidas


def _vectores(consultas: Sequence[str]) -> list[list[float]] | None:
    """Embedding de cada consulta, o ``None`` si este proceso no puede codificar."""
    from services.embeddings import embeddings_available, encode_texts

    if not embeddings_available():
        return None
    try:
        return _a_listas(encode_texts(list(consultas)))
    except Exception:
        log.warning("memoria_org_consulta_sin_vector", exc_info=True)
        return None


def citas(
    organization_id: int, consultas: Sequence[str], *, limite: int = MAX_CITAS
) -> list[list[CitaOrganizacion]]:
    """Citas de los documentos indexados de ``organization_id``, una lista por consulta.

    Con el indexado apagado (``MEMORIA_ORG_MAX_DOCUMENTOS=0``) o sin ningún
    documento indexable no consulta nada más: es el caso de casi todas las
    peticiones, y no debe costarles ni un embedding.
    """
    from config.settings import settings

    vacio: list[list[CitaOrganizacion]] = [[] for _ in consultas]
    if not consultas or not politica_indexado().disponible:
        return vacio
    with tenant_scope(organization_id):
        repo = _repo()
        if repo.contar_indexables(organization_id) == 0:
            return vacio
        vectores = _vectores(consultas) if settings.EMBEDDING_VERSION else None
        resultado: list[list[CitaOrganizacion]] = []
        for posicion, consulta in enumerate(consultas):
            por_significado = (
                repo.buscar_por_significado(
                    organization_id,
                    vectores[posicion],
                    embedding_version=settings.EMBEDDING_VERSION,
                )
                if vectores is not None
                else []
            )
            por_palabras = repo.buscar_por_palabras(organization_id, terminos_de(consulta))
            resultado.append(seleccionar(por_significado, por_palabras, limite=limite))
        return resultado
