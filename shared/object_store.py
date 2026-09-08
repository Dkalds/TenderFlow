"""Almacén de objetos para los binarios de los pliegos (plan 2026-09 v2, S8.1).

Hasta ahora el binario de un adjunto se procesaba en memoria y se descartaba
(así lo decía el docstring de ``scraper/document_fetcher.py`` y la nota de la
revisión ``v56``, que dejó ``documentos.storage_key`` reservada y nunca
escrita). La consecuencia práctica es que **re-extraer exige volver a PLACSP**,
y los enlaces de PLACSP llevan un token rotativo que caduca: cuando queremos
reprocesar —OCR nuevo, parser nuevo, chunking distinto— el 82% de las URIs
antiguas ya no sirve. Conservar el binario convierte la re-extracción en una
operación local.

Qué expone
----------
- :class:`ObjectStore`, la interfaz mínima que necesita el fetcher: ``put``,
  ``get``, ``delete`` y ``stats``.
- Tres implementaciones: :class:`S3ObjectStore` (cualquier bucket
  S3-compatible — Cloudflare R2, Supabase Storage, MinIO), que es la de
  producción; :class:`FilesystemObjectStore`, que cumple **la misma interfaz**
  sobre un directorio y es la que ejercitan los tests y el desarrollo local; y
  :class:`NullObjectStore`, que es lo que hay cuando nadie ha configurado nada
  —conservar el binario es una mejora, no un requisito, así que su ausencia no
  puede romper la ingesta—.
- :func:`document_blob_key`, la clave canónica ``documentos/{source_hash}``, y
  :func:`model_artifact_key`, la de los artefactos de modelo (S8.4), que viven
  en el mismo bucket bajo otro prefijo.

Configuración (variables de entorno)
------------------------------------
No viven en ``config/settings.py`` a propósito: ``settings`` es un
``BaseSettings`` que se valida al arrancar **cualquier** proceso (API, scraper,
scheduler) y este almacén es opcional y sólo lo tocan dos de ellos. Se leen
aquí, una vez, y se cachean::

    DOCUMENT_BLOB_BACKEND     auto (defecto) | s3 | filesystem | disabled
    DOCUMENT_BLOB_BUCKET      nombre del bucket S3-compatible
    DOCUMENT_BLOB_ENDPOINT_URL  endpoint del proveedor (R2/Supabase/MinIO)
    DOCUMENT_BLOB_REGION      región del bucket (defecto: auto)
    DOCUMENT_BLOB_PREFIX      prefijo de las claves (defecto: documentos/)
    DOCUMENT_BLOB_DIR         raíz del backend de sistema de ficheros
    MODEL_BLOB_PREFIX         prefijo de los artefactos de modelo (defecto: modelos/)
    PURSUIT_BLOB_PREFIX       prefijo de los adjuntos propios (defecto: adjuntos/)

``auto`` resuelve a ``filesystem`` si hay ``DOCUMENT_BLOB_DIR``, a ``s3`` si hay
``DOCUMENT_BLOB_BUCKET``, y a ``disabled`` si no hay ninguna de las dos.

Todas las operaciones son **best-effort desde el punto de vista del llamante**:
lanzan :class:`ObjectStoreError` y el fetcher decide (nunca se pierde un
documento porque el bucket esté caído).
"""

from __future__ import annotations

import abc
import importlib
import os
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any, ClassVar, Final

from observability.logging import get_logger

log = get_logger(__name__)

#: Prefijo por defecto de las claves. El plan lo fija como
#: ``documentos/{source_hash}``.
DEFAULT_PREFIX: Final = "documentos/"

#: Un ``source_hash`` del CODICE es hexadecimal, pero la columna es TEXT libre y
#: una clave se convierte en ruta en el backend de ficheros: se acota a lo que
#: no puede escaparse de la raíz ni del prefijo.
_SAFE_TOKEN = re.compile(r"^[A-Za-z0-9._-]{1,128}$")
_SAFE_KEY = re.compile(r"^[A-Za-z0-9._/-]{1,256}$")


class ObjectStoreError(RuntimeError):
    """Fallo de acceso al almacén de objetos."""


@dataclass(frozen=True)
class ObjectStoreStats:
    """Ocupación del almacén: lo que ``/analytics/quality`` publica."""

    objetos: int
    bytes: int


class ObjectStore(abc.ABC):
    """Interfaz mínima del almacén de binarios.

    Deliberadamente pequeña: el fetcher sólo necesita guardar, recuperar,
    borrar y medir. Cuanto menos superficie, más barato es que el backend de
    ficheros sea **equivalente** al de S3 y no una maqueta que diverge.
    """

    #: Nombre corto del backend, para logs y para el diagnóstico de /analytics.
    backend: ClassVar[str] = "abstract"

    @property
    def enabled(self) -> bool:
        """``False`` sólo en :class:`NullObjectStore` (nada configurado)."""
        return True

    @abc.abstractmethod
    def put(self, key: str, data: bytes, *, content_type: str | None = None) -> None:
        """Guarda ``data`` bajo ``key``, sobrescribiendo si ya existía."""

    @abc.abstractmethod
    def get(self, key: str) -> bytes | None:
        """Devuelve el binario de ``key``, o ``None`` si no está."""

    @abc.abstractmethod
    def delete(self, key: str) -> bool:
        """Borra ``key``. ``True`` si existía y se borró."""

    @abc.abstractmethod
    def stats(self, *, prefix: str = "") -> ObjectStoreStats:
        """Número de objetos y bytes totales bajo ``prefix``."""


class NullObjectStore(ObjectStore):
    """Almacén inexistente: nada configurado.

    No lanza al guardar. Conservar el binario es una mejora sobre el
    comportamiento anterior (descartarlo), así que un despliegue sin bucket
    tiene que seguir ingiriendo exactamente igual que antes de S8.
    """

    backend: ClassVar[str] = "disabled"

    @property
    def enabled(self) -> bool:
        return False

    def put(self, key: str, data: bytes, *, content_type: str | None = None) -> None:
        return None

    def get(self, key: str) -> bytes | None:
        return None

    def delete(self, key: str) -> bool:
        return False

    def stats(self, *, prefix: str = "") -> ObjectStoreStats:
        return ObjectStoreStats(objetos=0, bytes=0)


class FilesystemObjectStore(ObjectStore):
    """La misma interfaz sobre un directorio.

    Existe por los tests —el criterio de aceptación de S8.1 lo pide de forma
    explícita— y sirve además para desarrollo local sin credenciales. No es una
    maqueta: implementa el contrato entero, así que un test que pase aquí
    describe el comportamiento que el fetcher tendrá contra S3.
    """

    backend: ClassVar[str] = "filesystem"

    def __init__(self, root: Path | str) -> None:
        self.root = Path(root)

    def _path(self, key: str) -> Path:
        # ``_normalize_key`` ya prohíbe ``..`` y las rutas absolutas; el
        # ``resolve`` de abajo es la segunda barrera, por si la raíz es un
        # symlink que apunta fuera.
        candidato = (self.root / _normalize_key(key)).resolve()
        raiz = self.root.resolve()
        if not candidato.is_relative_to(raiz):
            raise ObjectStoreError(f"clave fuera de la raíz del almacén: {key!r}")
        return candidato

    def put(self, key: str, data: bytes, *, content_type: str | None = None) -> None:
        destino = self._path(key)
        destino.parent.mkdir(parents=True, exist_ok=True)
        # Escritura en dos pasos: un proceso que lea mientras otro escribe no
        # puede encontrarse medio fichero (el fetcher y la re-extracción pueden
        # correr a la vez sobre el mismo documento).
        temporal = destino.with_name(f".{destino.name}.tmp")
        temporal.write_bytes(data)
        temporal.replace(destino)

    def get(self, key: str) -> bytes | None:
        origen = self._path(key)
        if not origen.is_file():
            return None
        return origen.read_bytes()

    def delete(self, key: str) -> bool:
        objetivo = self._path(key)
        if not objetivo.is_file():
            return False
        objetivo.unlink()
        return True

    def stats(self, *, prefix: str = "") -> ObjectStoreStats:
        base = self.root / prefix if prefix else self.root
        if not base.exists():
            return ObjectStoreStats(objetos=0, bytes=0)
        objetos = 0
        total = 0
        for fichero in base.rglob("*"):
            if fichero.is_file() and not fichero.name.endswith(".tmp"):
                objetos += 1
                total += fichero.stat().st_size
        return ObjectStoreStats(objetos=objetos, bytes=total)


class S3ObjectStore(ObjectStore):
    """Bucket S3-compatible vía boto3 (dependencia ya presente en el proyecto).

    ``endpoint_url`` es lo que hace que valga igual para AWS S3, Cloudflare R2,
    Supabase Storage o un MinIO local; las credenciales las resuelve boto3 por
    su cadena habitual (``AWS_ACCESS_KEY_ID``/``AWS_SECRET_ACCESS_KEY``, perfil,
    rol), así que este módulo no las lee ni las registra nunca.
    """

    backend: ClassVar[str] = "s3"

    def __init__(
        self,
        bucket: str,
        *,
        endpoint_url: str | None = None,
        region_name: str | None = None,
    ) -> None:
        self.bucket = bucket
        self._endpoint_url = endpoint_url
        self._region_name = region_name
        self._client: Any | None = None  # boto3 no publica stubs; ver _cliente().

    def _cliente(self) -> Any:
        """Cliente boto3 perezoso.

        El import va por ``importlib`` y no por ``import boto3`` para que el
        tipo sea ``Any`` sin un ``# type: ignore``: boto3 no publica stubs ni
        ``py.typed``, y este módulo tiene que pasar mypy strict como el resto de
        producción.
        """
        if self._client is not None:
            return self._client
        try:
            boto3 = importlib.import_module("boto3")
        except ImportError as exc:  # pragma: no cover — boto3 es dependencia base
            raise ObjectStoreError("boto3 no está instalado") from exc
        kwargs: dict[str, str] = {}
        if self._endpoint_url:
            kwargs["endpoint_url"] = self._endpoint_url
        if self._region_name:
            kwargs["region_name"] = self._region_name
        self._client = boto3.client("s3", **kwargs)
        return self._client

    def put(self, key: str, data: bytes, *, content_type: str | None = None) -> None:
        extra: dict[str, str] = {"ContentType": content_type} if content_type else {}
        try:
            self._cliente().put_object(
                Bucket=self.bucket, Key=_normalize_key(key), Body=data, **extra
            )
        except ObjectStoreError:
            raise
        except Exception as exc:
            raise ObjectStoreError(f"no se pudo guardar {key!r}: {exc}") from exc

    def get(self, key: str) -> bytes | None:
        cliente = self._cliente()
        try:
            respuesta = cliente.get_object(Bucket=self.bucket, Key=_normalize_key(key))
        except Exception as exc:
            # boto3 modela "no existe" como excepción (``NoSuchKey``/404). El
            # llamante necesita distinguir "no está" de "el bucket falla":
            # lo primero es ``None`` y lo segundo un error.
            if _es_no_encontrado(exc):
                return None
            raise ObjectStoreError(f"no se pudo leer {key!r}: {exc}") from exc
        cuerpo: bytes = respuesta["Body"].read()
        return cuerpo

    def delete(self, key: str) -> bool:
        cliente = self._cliente()
        normalizada = _normalize_key(key)
        try:
            cliente.head_object(Bucket=self.bucket, Key=normalizada)
        except Exception as exc:
            if _es_no_encontrado(exc):
                return False
            raise ObjectStoreError(f"no se pudo comprobar {key!r}: {exc}") from exc
        try:
            cliente.delete_object(Bucket=self.bucket, Key=normalizada)
        except Exception as exc:
            raise ObjectStoreError(f"no se pudo borrar {key!r}: {exc}") from exc
        return True

    def stats(self, *, prefix: str = "") -> ObjectStoreStats:
        cliente = self._cliente()
        objetos = 0
        total = 0
        try:
            paginador = cliente.get_paginator("list_objects_v2")
            for pagina in paginador.paginate(Bucket=self.bucket, Prefix=prefix):
                for obj in pagina.get("Contents", []):
                    objetos += 1
                    total += int(obj.get("Size", 0))
        except Exception as exc:
            raise ObjectStoreError(f"no se pudo listar el bucket: {exc}") from exc
        return ObjectStoreStats(objetos=objetos, bytes=total)


def _es_no_encontrado(exc: Exception) -> bool:
    """¿La excepción de boto3 dice «esa clave no existe»?

    Se mira el ``Error.Code`` de la respuesta antes que el nombre de la clase:
    los proveedores S3-compatibles no comparten la jerarquía de excepciones de
    AWS, pero sí el código (``NoSuchKey``, ``404``, ``NotFound``).
    """
    respuesta = getattr(exc, "response", None)
    if isinstance(respuesta, dict):
        codigo = str(respuesta.get("Error", {}).get("Code", ""))
        if codigo in {"NoSuchKey", "NoSuchBucket", "NotFound", "404"}:
            return True
    return type(exc).__name__ in {"NoSuchKey", "ClientError404"}


def _normalize_key(key: str) -> str:
    """Valida la clave y la devuelve tal cual.

    Una clave llega a ser una ruta en :class:`FilesystemObjectStore`, así que
    ``..``, las barras invertidas y las rutas absolutas se rechazan aquí y no
    en cada backend.
    """
    limpia = key.strip()
    if not limpia or not _SAFE_KEY.match(limpia):
        raise ObjectStoreError(f"clave de objeto inválida: {key!r}")
    if limpia.startswith("/") or ".." in limpia.split("/"):
        raise ObjectStoreError(f"clave de objeto inválida: {key!r}")
    return limpia


# ── Configuración y resolución del backend ─────────────────────────────────


@dataclass(frozen=True)
class ObjectStoreConfig:
    """Lo que el entorno declara sobre el almacén."""

    backend: str
    bucket: str
    endpoint_url: str
    region: str
    prefix: str
    directory: str


def load_config() -> ObjectStoreConfig:
    """Lee la configuración del entorno (sin cachear)."""
    prefijo = os.environ.get("DOCUMENT_BLOB_PREFIX", DEFAULT_PREFIX).strip()
    if prefijo and not prefijo.endswith("/"):
        prefijo += "/"
    return ObjectStoreConfig(
        backend=os.environ.get("DOCUMENT_BLOB_BACKEND", "auto").strip().lower() or "auto",
        bucket=os.environ.get("DOCUMENT_BLOB_BUCKET", "").strip(),
        endpoint_url=os.environ.get("DOCUMENT_BLOB_ENDPOINT_URL", "").strip(),
        region=os.environ.get("DOCUMENT_BLOB_REGION", "").strip(),
        prefix=prefijo or DEFAULT_PREFIX,
        directory=os.environ.get("DOCUMENT_BLOB_DIR", "").strip(),
    )


def build_object_store(config: ObjectStoreConfig | None = None) -> ObjectStore:
    """Construye el almacén que describe ``config`` (sin cachear)."""
    cfg = config or load_config()
    backend = cfg.backend
    if backend == "auto":
        if cfg.directory:
            backend = "filesystem"
        elif cfg.bucket:
            backend = "s3"
        else:
            backend = "disabled"

    if backend == "filesystem":
        if not cfg.directory:
            raise ObjectStoreError("DOCUMENT_BLOB_BACKEND=filesystem exige DOCUMENT_BLOB_DIR")
        return FilesystemObjectStore(cfg.directory)
    if backend == "s3":
        if not cfg.bucket:
            raise ObjectStoreError("DOCUMENT_BLOB_BACKEND=s3 exige DOCUMENT_BLOB_BUCKET")
        return S3ObjectStore(
            cfg.bucket,
            endpoint_url=cfg.endpoint_url or None,
            region_name=cfg.region or None,
        )
    if backend == "disabled":
        return NullObjectStore()
    raise ObjectStoreError(f"DOCUMENT_BLOB_BACKEND desconocido: {backend!r}")


_cache: tuple[ObjectStoreConfig, ObjectStore] | None = None


def get_object_store() -> ObjectStore:
    """Almacén vigente, cacheado por configuración.

    La caché se invalida sola cuando el entorno cambia (los tests hacen
    ``monkeypatch.setenv`` y esperan ver el backend nuevo sin acordarse de
    llamar a nada). Construir el cliente de boto3 no es gratis, así que se
    reutiliza mientras la configuración sea la misma.
    """
    global _cache
    cfg = load_config()
    if _cache is not None and _cache[0] == cfg:
        return _cache[1]
    store = build_object_store(cfg)
    _cache = (cfg, store)
    log.info("object_store_resolved", backend=store.backend, enabled=store.enabled)
    return store


def reset_object_store_cache() -> None:
    """Olvida el almacén cacheado (tests)."""
    global _cache
    _cache = None


def document_blob_key(source_hash: str | None, *, fallback: str | None = None) -> str | None:
    """Clave canónica del binario de un adjunto: ``documentos/{source_hash}``.

    ``source_hash`` es el ``cbc:DocumentHash`` del CODICE, que depende del
    contenido y no del token rotativo de la URI (ver ``v88``): es la identidad
    correcta para un binario deduplicado. Las filas anteriores a ``v88`` no lo
    tienen, y para esas se usa ``fallback`` —el sha256 del binario descargado—,
    que identifica el mismo contenido aunque no venga de la fuente.

    Devuelve ``None`` cuando no hay ninguno de los dos: sin identidad no hay
    clave estable, y guardar bajo el id de la fila haría que la deduplicación
    dejara de funcionar en silencio.
    """
    for candidato in (source_hash, fallback):
        token = (candidato or "").strip()
        if token and _SAFE_TOKEN.match(token):
            return f"{load_config().prefix}{token}"
    return None


def blob_prefix() -> str:
    """Prefijo bajo el que viven los binarios de pliegos."""
    return load_config().prefix


#: Prefijo de los artefactos de modelo. Separado del de los pliegos porque su
#: ciclo de vida no tiene nada que ver: los pliegos los purga la retención a los
#: 24 meses y un artefacto de modelo tiene que sobrevivir mientras haya una
#: versión activa que lo referencie.
DEFAULT_MODEL_PREFIX: Final = "modelos/"


def model_artifact_key(asset_name: str) -> str | None:
    """Clave de un artefacto de modelo en el mismo bucket (S8.4).

    ``None`` si el nombre no es un token seguro: nunca se construye una clave a
    partir de una ruta arbitraria del registro de modelos.
    """
    nombre = (asset_name or "").strip()
    if not nombre or not _SAFE_TOKEN.match(nombre):
        return None
    prefijo = os.environ.get("MODEL_BLOB_PREFIX", DEFAULT_MODEL_PREFIX).strip()
    if prefijo and not prefijo.endswith("/"):
        prefijo += "/"
    return f"{prefijo or DEFAULT_MODEL_PREFIX}{nombre}"


#: Prefijo de los adjuntos propios de una oportunidad (C6.3). Separado del de
#: los pliegos por la misma razón que el de modelos: su ciclo de vida es otro.
#: Un pliego es dato público que la retención purga a los 24 meses; la propuesta
#: que preparó el equipo es dato corporativo y se borra cuando se borra la
#: organización, no cuando el expediente envejece.
DEFAULT_PURSUIT_PREFIX: Final = "adjuntos/"


def pursuit_attachment_key(organization_id: int, sha256: str) -> str | None:
    """Clave de un adjunto propio: ``adjuntos/{organization_id}/{sha256}``.

    La organización va **en la clave** y no sólo en la fila. Dos motivos: el
    listado del bucket por prefijo se puede acotar a un cliente sin consultar la
    base —que es lo que hace barato responder a un borrado de organización— y un
    error de programación que pierda el ``WHERE`` no puede entregar el objeto de
    otro equipo, porque su ruta ni siquiera se puede construir.

    El sha256 y no el id de la fila: el mismo fichero subido dos veces es un
    objeto, no dos. ``None`` si la huella no es un token seguro — nunca se
    construye una clave con texto que venga de fuera.
    """
    huella = (sha256 or "").strip().lower()
    if not huella or not _SAFE_TOKEN.match(huella):
        return None
    try:
        org = int(organization_id)
    except (TypeError, ValueError):
        return None
    if org <= 0:
        return None
    prefijo = os.environ.get("PURSUIT_BLOB_PREFIX", DEFAULT_PURSUIT_PREFIX).strip()
    if prefijo and not prefijo.endswith("/"):
        prefijo += "/"
    return f"{prefijo or DEFAULT_PURSUIT_PREFIX}{org}/{huella}"


def store_stats() -> ObjectStoreStats | None:
    """Ocupación del almacén, o ``None`` si no hay almacén o falla.

    ``None`` significa **no medido**, que es lo que ``/analytics/quality`` debe
    publicar cuando no lo sabe: un 0 en la pantalla que acredita la calidad del
    dato se lee como «el bucket está vacío», que es una afirmación distinta.
    """
    try:
        store = get_object_store()
        if not store.enabled:
            return None
        return store.stats(prefix=blob_prefix())
    except Exception as exc:
        log.warning("object_store_stats_unavailable", error=str(exc))
        return None


def purge_keys(keys: list[str]) -> int:
    """Borra las claves indicadas y devuelve cuántas existían.

    Fail-open por clave: una que no se pueda borrar no puede impedir que se
    purguen las demás (mismo criterio que el resto de la retención).
    """
    store = get_object_store()
    if not store.enabled:
        return 0
    borradas = 0
    for key in keys:
        try:
            if store.delete(key):
                borradas += 1
        except Exception as exc:
            log.warning("object_store_delete_failed", key=key, error=str(exc))
    return borradas


def disk_usage_bytes(path: Path) -> int:
    """Bytes ocupados por ``path`` (utilidad para el backend de ficheros)."""
    if path.is_file():
        return path.stat().st_size
    if not path.exists():
        return 0
    return sum(f.stat().st_size for f in path.rglob("*") if f.is_file())


__all__ = [
    "DEFAULT_MODEL_PREFIX",
    "DEFAULT_PREFIX",
    "DEFAULT_PURSUIT_PREFIX",
    "FilesystemObjectStore",
    "NullObjectStore",
    "ObjectStore",
    "ObjectStoreConfig",
    "ObjectStoreError",
    "ObjectStoreStats",
    "S3ObjectStore",
    "blob_prefix",
    "build_object_store",
    "disk_usage_bytes",
    "document_blob_key",
    "get_object_store",
    "load_config",
    "model_artifact_key",
    "purge_keys",
    "pursuit_attachment_key",
    "reset_object_store_cache",
    "store_stats",
]
