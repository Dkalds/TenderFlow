"""Settings del almacén de objetos de binarios (ADR-029, plan v2 S8.1).

Módulo hermano de `config/settings.py`, como `settings_resumen.py`: `Settings`
hereda de esta clase, así que los nombres de las variables y el acceso
(`settings.DOCUMENT_BLOB_BACKEND`) son los de siempre.

Por qué aquí y no solo en `os.environ`: hasta 2026-10 `shared/object_store.py`
leía las variables directamente del entorno del proceso, y eso dejaba fuera el
`.env` del checkout (que pydantic sí lee y `os.environ` no). Declararlas aquí
las documenta con su tipo y su default en el mismo sitio que el resto.

Precedencia que aplica `shared/object_store.py::load_config`: **una variable
presente en el entorno del proceso gana** a lo que `settings` cargó al
arrancar. Así un despliegue, un job de GitHub Actions o un test con
`monkeypatch.setenv` ven el valor nuevo sin reconstruir `settings`.

Ningún campo es obligatorio y ninguno se valida al arrancar: el almacén es una
mejora opcional (sin configurar, la ingesta sigue y el binario no se conserva),
así que un valor raro no puede tumbar la API; lo rechaza
`build_object_store` cuando alguien lo usa.

Sin `model_config` propio a propósito (mismo motivo que `settings_resumen.py`).
"""

from __future__ import annotations

from pydantic import SecretStr
from pydantic_settings import BaseSettings


class ObjectStoreSettings(BaseSettings):
    """Backend y credenciales del almacén de binarios de documentos."""

    # auto (defecto) | filesystem | s3 | supabase | disabled.
    # `auto` resuelve, en este orden: filesystem si hay DOCUMENT_BLOB_DIR,
    # supabase si hay bucket y DOCUMENT_BLOB_SUPABASE_URL, s3 si hay bucket, y
    # disabled si no hay nada.
    DOCUMENT_BLOB_BACKEND: str = "auto"
    # Bucket (S3-compatible o de Supabase Storage). Privado: ADR-029, «Riesgo».
    DOCUMENT_BLOB_BUCKET: str = ""
    # Endpoint S3-compatible (R2, MinIO, el endpoint S3 de Supabase); vacío = AWS.
    # Las credenciales S3 las resuelve boto3 por su cadena (`AWS_*`).
    DOCUMENT_BLOB_ENDPOINT_URL: str = ""
    DOCUMENT_BLOB_REGION: str = ""
    DOCUMENT_BLOB_PREFIX: str = "documentos/"
    # Raíz del backend de sistema de ficheros (dev local o disco persistente).
    DOCUMENT_BLOB_DIR: str = ""
    # Backend `supabase`: la API REST de Supabase Storage por HTTPS, sin SDK.
    # URL del proyecto (`https://<ref>.supabase.co`) y una clave de servidor
    # (service role o secret key). Nunca la clave pública: el bucket es privado.
    DOCUMENT_BLOB_SUPABASE_URL: str = ""
    DOCUMENT_BLOB_SUPABASE_KEY: SecretStr = SecretStr("")
    # Prefijo de los artefactos de modelo en el mismo bucket (S8.4).
    MODEL_BLOB_PREFIX: str = "modelos/"
