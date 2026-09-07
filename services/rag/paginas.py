"""F2.5 — la página del pliego con la cita resaltada, sin binario.

La ficha del pliego enseña la cita («*el plazo de garantía será de 24
meses*») y ahí se acaba: quien quiere comprobarla tiene que abrir el PDF en el
portal, buscar la frase a mano y confiar en que es la misma. Eso es
exactamente la fricción que hace que una función de trazabilidad no se use.

``documento_pages`` ya guarda el texto y los offsets por página desde la
extracción, así que la comprobación se puede servir sin descargar nada: se
devuelve la página entera y **dónde** empieza y acaba el fragmento dentro de
ella. El binario real (v2 S8.1) añadirá después el PDF; esto no lo estorba.

Por qué el resaltado son offsets y no HTML
------------------------------------------
Devolver la página ya troceada en «antes / cita / después» obligaría a este
módulo a decidir cómo se pinta, y a escapar el texto del pliego —que es
entrada no confiable— para meterlo en marcado. Se devuelven índices sobre el
texto plano: el cliente corta donde le digan y renderiza como quiera, y no hay
ninguna cadena con marcado viajando por la API.
"""

from __future__ import annotations

from typing import Any, Final

from pydantic import BaseModel, ConfigDict, Field

from db.repositories.documentos import DocumentosRepository
from observability.logging import get_logger

log = get_logger(__name__)

_repo = DocumentosRepository()

#: Por qué un resaltado no se pudo aplicar. La página se sirve igual —completa
#: y sin resaltar—, pero el consumidor tiene que poder decir por qué, en vez de
#: enseñar una página sin marcar como si el usuario no hubiera pedido nada.
MOTIVO_SIN_OFFSETS: Final = "sin_offsets"
MOTIVO_FUERA_DE_RANGO: Final = "offsets_fuera_de_rango"
MOTIVO_INVERTIDOS: Final = "offsets_invertidos"


class PaginaDocumento(BaseModel):
    """Una página del pliego, con el fragmento a resaltar si es válido."""

    model_config = ConfigDict(extra="forbid")

    documento_id: int = Field(gt=0)
    page_number: int = Field(gt=0)
    texto: str
    #: Total de páginas del documento, para la navegación anterior/siguiente.
    total_paginas: int = Field(ge=1)
    #: Índices **relativos al texto de esta página**, no al documento. Los de
    #: `documento_pages` son absolutos sobre el documento entero, y pasárselos
    #: al cliente tal cual era la forma más fácil de resaltar el trozo
    #: equivocado en cuanto la página no fuese la primera.
    resaltado_inicio: int | None = Field(default=None, ge=0)
    resaltado_fin: int | None = Field(default=None, ge=0)
    #: `None` cuando el resaltado se aplicó. Con valor, la página va completa y
    #: sin marcar, y esto dice por qué (ver las constantes `MOTIVO_*`).
    resaltado_omitido: str | None = None
    tipo: str | None = None
    filename: str | None = None
    #: Enlace al documento original en el portal de la fuente.
    uri: str | None = None


def _relativos(
    *,
    inicio: int | None,
    fin: int | None,
    page_start: int | None,
    largo: int,
) -> tuple[int | None, int | None, str | None]:
    """Pasa unos offsets absolutos del documento a índices de esta página.

    Devuelve ``(inicio, fin, motivo_de_omision)``. Cualquier incoherencia
    —faltan, van al revés, caen fuera de la página— produce ``(None, None,
    motivo)`` y **no** una excepción: el usuario pidió ver la página, y
    negársela porque una cita venga mal guardada sería castigarle por un fallo
    de la extracción. Es lo que pide el criterio de aceptación: página completa
    sin resaltado y aviso.
    """
    if inicio is None or fin is None:
        return None, None, MOTIVO_SIN_OFFSETS
    if fin <= inicio:
        return None, None, MOTIVO_INVERTIDOS

    base = page_start or 0
    rel_inicio = inicio - base
    rel_fin = fin - base
    if rel_inicio < 0 or rel_fin > largo:
        return None, None, MOTIVO_FUERA_DE_RANGO
    return rel_inicio, rel_fin, None


def get_pagina(
    licitacion_id: str,
    documento_id: int,
    page_number: int,
    *,
    inicio: int | None = None,
    fin: int | None = None,
) -> PaginaDocumento | None:
    """La página ``page_number`` del documento, o ``None`` si no existe.

    ``licitacion_id`` no es decorativo: acota el documento a la licitación de
    la ruta, de modo que un ``documento_id`` de otro expediente devuelve 404 en
    vez de servir el pliego de otro. La comprobación se hace sobre las páginas
    que la propia licitación tiene, no sobre el id suelto.
    """
    paginas: list[dict[str, Any]] = _repo.list_pages_by_licitacion(licitacion_id)
    del_documento = [p for p in paginas if int(p["documento_id"]) == documento_id]
    if not del_documento:
        return None

    fila = next((p for p in del_documento if int(p["page_number"]) == page_number), None)
    if fila is None:
        return None

    texto = str(fila.get("texto") or "")
    rel_inicio, rel_fin, motivo = _relativos(
        inicio=inicio,
        fin=fin,
        page_start=fila.get("start_offset"),
        largo=len(texto),
    )
    if motivo is not None and (inicio is not None or fin is not None):
        log.info(
            "pagina_resaltado_omitido",
            documento_id=documento_id,
            page_number=page_number,
            motivo=motivo,
        )
    return PaginaDocumento(
        documento_id=documento_id,
        page_number=page_number,
        texto=texto,
        total_paginas=len(del_documento),
        resaltado_inicio=rel_inicio,
        resaltado_fin=rel_fin,
        # Sin offsets pedidos no hay omisión que declarar: el usuario abrió la
        # página, no una cita.
        resaltado_omitido=motivo if (inicio is not None or fin is not None) else None,
        tipo=fila.get("tipo"),
        filename=fila.get("filename"),
        uri=fila.get("uri"),
    )
