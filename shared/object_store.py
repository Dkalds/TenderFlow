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
- Cuatro implementaciones: :class:`S3ObjectStore` (cualquier bucket
  S3-compatible — Cloudflare R2, el endpoint S3 de Supabase, MinIO, vía boto3);
  :class:`SupabaseStorageObjectStore` (la API REST de Supabase Storage por
  HTTPS con ``shared/outbound_http``, sin SDK y sin claves S3 aparte: basta la
  clave de servidor del proyecto); :class:`FilesystemObjectStore`, que cumple **la misma interfaz**
  sobre un directorio y es la que ejercitan los tests y el desarrollo local; y
  :class:`NullObjectStore`, que es lo que hay cuando nadie ha configurado nada
  —conservar el binario es una mejora, no un requisito, así que su ausencia no
  puede romper la ingesta—.
- :func:`document_blob_key`, la clave canónica ``documentos/{source_hash}``, y
  :func:`model_artifact_key`, la de los artefactos de modelo (S8.4), que viven
  en el mismo bucket bajo otro prefijo.

Configuración
-------------
Declarada en ``config/settings_object_store.py`` (mezclada en ``Settings``),
que la documenta con tipo y default y recoge el ``.env``. Una variable presente
en el entorno del proceso **gana** a lo que ``settings`` cargó al arrancar: así
un job o un test con ``monkeypatch.setenv`` ven el valor nuevo sin reconstruir
``settings``::

    DOCUMENT_BLOB_BACKEND     auto (defecto) | s3 | supabase | filesystem | disabled
    DOCUMENT_BLOB_BUCKET      nombre del bucket (S3-compatible o Supabase Storage)
    DOCUMENT_BLOB_ENDPOINT_URL  endpoint S3 del proveedor (R2/Supabase/MinIO)
    DOCUMENT_BLOB_REGION      región del bucket (defecto: auto)
    DOCUMENT_BLOB_PREFIX      prefijo de las claves (defecto: documentos/)
    DOCUMENT_BLOB_DIR         raíz del backend de sistema de ficheros
    DOCUMENT_BLOB_SUPABASE_URL  https://<ref>.supabase.co (backend supabase)
    DOCUMENT_BLOB_SUPABASE_KEY  clave de servidor del proyecto (backend supabase)
    MODEL_BLOB_PREFIX         prefijo de los artefactos de modelo (defecto: modelos/)

``auto`` resuelve a ``filesystem`` si hay ``DOCUMENT_BLOB_DIR``, a ``supabase``
si hay bucket y ``DOCUMENT_BLOB_SUPABASE_URL``, a ``s3`` si hay bucket, y a
``disabled`` si no hay nada.

Todas las operaciones son **best-effort desde el punto de vista del llamante**:
lanzan :class:`ObjectStoreError` y el fetcher decide (nunca se pierde un
documento porque el bucket esté caído).
"""

from __future__ import annotations

import abc
import importlib
import json
import os
import re
from collections.abc import Callable, Iterator, Mapping
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, ClassVar, Final, Protocol
from urllib.parse import quote, urlparse

from pydantic import SecretStr

from config.settings import settings
from observability.logging import get_logger
from shared.outbound_http import pinned_https_request

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


class _RespuestaHttp(Protocol):
    """Lo que el backend de Supabase usa de una respuesta HTTP.

    Es el subconjunto de :class:`shared.outbound_http.PinnedHttpsResponse` que
    hace falta, declarado como protocolo para que los tests inyecten un doble
    sin red (ADR-029 §B).
    """

    status_code: int

    def iter_content(self, chunk_size: int = ...) -> Iterator[bytes]: ...

    def close(self) -> None: ...


#: Firma del transporte: ``(método, url, cabeceras, cuerpo) -> respuesta``.
TransporteHttp = Callable[[str, str, Mapping[str, str], bytes | None], _RespuestaHttp]


class SupabaseStorageObjectStore(ObjectStore):
    """Supabase Storage por su API REST, sobre ``shared/outbound_http``.

    Alternativa a :class:`S3ObjectStore` para Supabase que no necesita SDK ni
    un par de claves S3 aparte: autentica con la clave de servidor del proyecto
    (``Authorization: Bearer`` + ``apikey``). El transporte es
    :func:`shared.outbound_http.pinned_https_request` —DNS resuelto y validado
    una vez, sin redirecciones— con el host del proyecto como única entrada de
    la allowlist: aunque la clave de objeto venga de datos externos, la
    petición no puede salir hacia otro sitio.

    Endpoints (``/storage/v1``): ``POST object/{bucket}/{clave}`` con
    ``x-upsert: true`` para guardar, ``GET object/authenticated/{bucket}/{clave}``
    para leer, ``DELETE object/{bucket}/{clave}`` para borrar y
    ``POST object/list/{bucket}`` (no recursivo: las carpetas se recorren) para
    medir. Supabase contesta «no existe» unas veces con 404 y otras con 400 y
    ``{"statusCode": "404"}`` en el cuerpo; las dos se tratan igual.
    """

    backend: ClassVar[str] = "supabase"

    #: Tope de cada petición. Un pliego cabe holgado (``MAX_DOCUMENT_BYTES``).
    TIMEOUT_SECONDS: ClassVar[float] = 60.0
    #: Página del listado; el máximo que admite la API es 1000.
    PAGINA_LISTADO: ClassVar[int] = 1000

    def __init__(
        self,
        base_url: str,
        bucket: str,
        service_key: str,
        *,
        transporte: TransporteHttp | None = None,
    ) -> None:
        parsed = urlparse(base_url.strip())
        if parsed.scheme != "https" or not parsed.hostname:
            raise ObjectStoreError("DOCUMENT_BLOB_SUPABASE_URL debe ser una URL https")
        if not bucket or not _SAFE_TOKEN.match(bucket):
            raise ObjectStoreError(f"bucket de Supabase inválido: {bucket!r}")
        if not service_key:
            raise ObjectStoreError("el backend supabase exige DOCUMENT_BLOB_SUPABASE_KEY")
        self.bucket = bucket
        self._base = f"https://{parsed.netloc}/storage/v1"
        self._host = parsed.hostname
        self._key = service_key
        self._transporte: TransporteHttp = transporte or self._transporte_por_defecto

    def _transporte_por_defecto(
        self, metodo: str, url: str, cabeceras: Mapping[str, str], cuerpo: bytes | None
    ) -> _RespuestaHttp:
        return pinned_https_request(
            metodo,
            url,
            headers=cabeceras,
            body=cuerpo,
            timeout_seconds=self.TIMEOUT_SECONDS,
            allowed_hosts=frozenset({self._host}),
        )

    def _cabeceras(self, extra: Mapping[str, str] | None = None) -> dict[str, str]:
        cabeceras = {"Authorization": f"Bearer {self._key}", "apikey": self._key}
        cabeceras.update(extra or {})
        return cabeceras

    def _url_objeto(self, key: str, *, autenticado: bool = False) -> str:
        ruta = quote(_normalize_key(key), safe="/")
        tramo = "object/authenticated" if autenticado else "object"
        return f"{self._base}/{tramo}/{self.bucket}/{ruta}"

    def _peticion(
        self,
        metodo: str,
        url: str,
        *,
        cabeceras: Mapping[str, str] | None = None,
        cuerpo: bytes | None = None,
    ) -> tuple[int, bytes]:
        """Hace la petición y devuelve ``(status, cuerpo)``.

        Cualquier fallo de transporte se convierte en :class:`ObjectStoreError`
        **sin** el detalle de la excepción original: la clave de servidor viaja
        en las cabeceras y no puede acabar en un log.
        """
        try:
            respuesta = self._transporte(metodo, url, self._cabeceras(cabeceras), cuerpo)
        except Exception as exc:
            raise ObjectStoreError(
                f"Supabase Storage no responde ({metodo}): {type(exc).__name__}"
            ) from exc
        try:
            datos = b"".join(respuesta.iter_content(65536))
        except Exception as exc:
            raise ObjectStoreError(
                f"respuesta de Supabase Storage ilegible ({metodo}): {type(exc).__name__}"
            ) from exc
        finally:
            respuesta.close()
        return respuesta.status_code, datos

    @staticmethod
    def _es_no_encontrado(status: int, cuerpo: bytes) -> bool:
        if status == 404:
            return True
        if status != 400:
            return False
        try:
            datos = json.loads(cuerpo.decode("utf-8", errors="replace"))
        except ValueError:
            return False
        if not isinstance(datos, dict):
            return False
        codigo = f"{datos.get('statusCode', '')} {datos.get('error', '')}"
        return "404" in codigo or "not_found" in codigo.lower()

    @staticmethod
    def _fallo(operacion: str, key: str, status: int) -> ObjectStoreError:
        # Solo el código: el cuerpo de un error puede reflejar la petición.
        return ObjectStoreError(f"no se pudo {operacion} {key!r}: HTTP {status}")

    def put(self, key: str, data: bytes, *, content_type: str | None = None) -> None:
        status, _ = self._peticion(
            "POST",
            self._url_objeto(key),
            cabeceras={
                "Content-Type": content_type or "application/octet-stream",
                "x-upsert": "true",
            },
            cuerpo=data,
        )
        if status >= 300:
            raise self._fallo("guardar", key, status)

    def get(self, key: str) -> bytes | None:
        status, cuerpo = self._peticion("GET", self._url_objeto(key, autenticado=True))
        if status < 300:
            return cuerpo
        if self._es_no_encontrado(status, cuerpo):
            return None
        raise self._fallo("leer", key, status)

    def delete(self, key: str) -> bool:
        status, cuerpo = self._peticion("DELETE", self._url_objeto(key))
        if status < 300:
            return True
        if self._es_no_encontrado(status, cuerpo):
            return False
        raise self._fallo("borrar", key, status)

    def _listar(self, prefijo: str, offset: int) -> list[dict[str, Any]]:
        cuerpo = json.dumps(
            {
                "prefix": prefijo,
                "limit": self.PAGINA_LISTADO,
                "offset": offset,
                "sortBy": {"column": "name", "order": "asc"},
            }
        ).encode("utf-8")
        status, datos = self._peticion(
            "POST",
            f"{self._base}/object/list/{self.bucket}",
            cabeceras={"Content-Type": "application/json"},
            cuerpo=cuerpo,
        )
        if status >= 300:
            raise ObjectStoreError(f"no se pudo listar el bucket: HTTP {status}")
        try:
            filas = json.loads(datos.decode("utf-8"))
        except ValueError as exc:
            raise ObjectStoreError("listado de Supabase Storage ilegible") from exc
        if not isinstance(filas, list):
            raise ObjectStoreError("listado de Supabase Storage con forma inesperada")
        return [fila for fila in filas if isinstance(fila, dict)]

    def stats(self, *, prefix: str = "") -> ObjectStoreStats:
        """Recorre el prefijo carpeta a carpeta (la API no lista en recursivo).

        Una fila sin ``id`` es una carpeta; las demás son objetos y llevan el
        tamaño en ``metadata.size``.
        """
        objetos = 0
        total = 0
        pendientes = [prefix.rstrip("/")]
        while pendientes:
            carpeta = pendientes.pop()
            offset = 0
            while True:
                filas = self._listar(carpeta, offset)
                for fila in filas:
                    nombre = str(fila.get("name") or "")
                    if not nombre:
                        continue
                    if fila.get("id") is None:
                        pendientes.append(f"{carpeta}/{nombre}" if carpeta else nombre)
                        continue
                    objetos += 1
                    metadata = fila.get("metadata")
                    if isinstance(metadata, dict):
                        total += int(metadata.get("size") or 0)
                if len(filas) < self.PAGINA_LISTADO:
                    break
                offset += len(filas)
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
    supabase_url: str = ""
    #: Fuera del ``repr``: la configuración se registra y se compara, y la
    #: clave de servidor no puede acabar en un log.
    supabase_key: str = field(default="", repr=False)


def _valor(nombre: str) -> str:
    """Valor de una variable: el entorno del proceso gana a ``settings``.

    ``settings`` recoge el ``.env`` y los defaults declarados en
    ``config/settings_object_store.py``; el entorno manda para que un job o un
    test que cambie la variable lo vea sin reconstruir ``settings``.
    """
    if nombre in os.environ:
        return os.environ[nombre].strip()
    valor: object = getattr(settings, nombre, "")
    if isinstance(valor, SecretStr):
        valor = valor.get_secret_value()
    return str(valor or "").strip()


def load_config() -> ObjectStoreConfig:
    """Lee la configuración (entorno sobre ``settings``, sin cachear)."""
    prefijo = _valor("DOCUMENT_BLOB_PREFIX") or DEFAULT_PREFIX
    if not prefijo.endswith("/"):
        prefijo += "/"
    return ObjectStoreConfig(
        backend=_valor("DOCUMENT_BLOB_BACKEND").lower() or "auto",
        bucket=_valor("DOCUMENT_BLOB_BUCKET"),
        endpoint_url=_valor("DOCUMENT_BLOB_ENDPOINT_URL"),
        region=_valor("DOCUMENT_BLOB_REGION"),
        prefix=prefijo,
        directory=_valor("DOCUMENT_BLOB_DIR"),
        supabase_url=_valor("DOCUMENT_BLOB_SUPABASE_URL"),
        supabase_key=_valor("DOCUMENT_BLOB_SUPABASE_KEY"),
    )


def build_object_store(config: ObjectStoreConfig | None = None) -> ObjectStore:
    """Construye el almacén que describe ``config`` (sin cachear)."""
    cfg = config or load_config()
    backend = cfg.backend
    if backend == "auto":
        if cfg.directory:
            backend = "filesystem"
        elif cfg.bucket and cfg.supabase_url:
            backend = "supabase"
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
    if backend == "supabase":
        if not cfg.bucket or not cfg.supabase_url:
            raise ObjectStoreError(
                "DOCUMENT_BLOB_BACKEND=supabase exige DOCUMENT_BLOB_BUCKET "
                "y DOCUMENT_BLOB_SUPABASE_URL"
            )
        return SupabaseStorageObjectStore(cfg.supabase_url, cfg.bucket, cfg.supabase_key)
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
    prefijo = _valor("MODEL_BLOB_PREFIX") or DEFAULT_MODEL_PREFIX
    if not prefijo.endswith("/"):
        prefijo += "/"
    return f"{prefijo}{nombre}"


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
    "FilesystemObjectStore",
    "NullObjectStore",
    "ObjectStore",
    "ObjectStoreConfig",
    "ObjectStoreError",
    "ObjectStoreStats",
    "S3ObjectStore",
    "SupabaseStorageObjectStore",
    "TransporteHttp",
    "blob_prefix",
    "build_object_store",
    "disk_usage_bytes",
    "document_blob_key",
    "get_object_store",
    "load_config",
    "model_artifact_key",
    "purge_keys",
    "reset_object_store_cache",
    "store_stats",
]
