"""Topes de los adjuntos propios y de su indexado (C6.3, ADR-040).

Funciones que leen ``os.environ`` en cada llamada, como las de
``config/settings_cola.py``: son ajustes de un componente, y un test los mueve
sin reconstruir el singleton de ``Settings``.

**Ninguno de estos valores es una decisión de producto.** La cuota de adjuntos
sigue siendo la que había (2 GiB) y los topes del indexado son un suelo
conservador para que la función no nazca sin límite; cuánto se ofrece a cada
organización lo decide el propietario (backlog, «Memoria de la organización»).
"""

from __future__ import annotations

from config.settings_cola import _entero_env

#: Lo que ocupan los adjuntos de una organización, retirados incluidos.
PURSUIT_ATTACHMENT_MAX_BYTES_POR_ORGANIZACION_DEFAULT = 2 * 1024 * 1024 * 1024

#: Documentos que una organización puede tener indexados a la vez. ``0`` apaga
#: el indexado y la recuperación sin desplegar código.
MEMORIA_ORG_MAX_DOCUMENTOS_DEFAULT = 5

#: Tamaño máximo de un documento para poder indexarse. Por debajo del tope de
#: subida (25 MiB): extraer y embeber cuesta CPU del proceso que sirve la API.
MEMORIA_ORG_MAX_BYTES_POR_DOCUMENTO_DEFAULT = 5 * 1024 * 1024


def pursuit_attachment_max_bytes_por_organizacion() -> int:
    return _entero_env(
        "PURSUIT_ATTACHMENT_MAX_BYTES_POR_ORGANIZACION",
        PURSUIT_ATTACHMENT_MAX_BYTES_POR_ORGANIZACION_DEFAULT,
        minimo=1,
    )


def memoria_org_max_documentos() -> int:
    return _entero_env("MEMORIA_ORG_MAX_DOCUMENTOS", MEMORIA_ORG_MAX_DOCUMENTOS_DEFAULT, minimo=0)


def memoria_org_max_bytes_por_documento() -> int:
    return _entero_env(
        "MEMORIA_ORG_MAX_BYTES_POR_DOCUMENTO",
        MEMORIA_ORG_MAX_BYTES_POR_DOCUMENTO_DEFAULT,
        minimo=1,
    )
