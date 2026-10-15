"""Tools de dominio: atajos para lo que es incómodo de escribir en SQL.

Son tres: ``buscar_licitaciones`` (búsqueda de texto con filtros),
``buscar_en_pliegos`` (fragmentos de pliego relevantes para una pregunta) y
``ficha_licitacion`` (el expediente completo).

A diferencia de ``consultar_sql``, **no** leen con el rol del MCP: pasan por los
repositorios y servicios normales de la aplicación (``DATABASE_URL``), igual que
la API. La entrada se valida con modelos Pydantic; un valor fuera de rango
levanta ``pydantic.ValidationError`` y el servidor lo devuelve al LLM como
error de la tool. Todo lo que sale pasa por ``serializar_valor`` para que sea
JSON seguro.
"""

from __future__ import annotations

import re
from datetime import date
from typing import Annotated

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    StringConstraints,
    field_validator,
    model_validator,
)

from db.consulta_libre import JSONValue, serializar_valor
from mcp_server.tools import ErrorHerramienta
from services.expediente import expediente_completo
from services.licitaciones import search_advanced
from services.rag.fragmentos import Fragmento, fragmentos_de_pliego

__all__ = ["buscar_en_pliegos", "buscar_licitaciones", "ficha_licitacion"]

#: Tope del identificador que se repite en un mensaje de error.
_MAX_ECO = 60
_FECHA = re.compile(r"\d{4}-\d{2}-\d{2}")

_IdExterno = Annotated[str, StringConstraints(min_length=1, max_length=200)]
_Etiqueta = Annotated[str, StringConstraints(min_length=1, max_length=100)]


class _Entrada(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)


class _EntradaBuscarLicitaciones(_Entrada):
    texto: str = Field(max_length=500)
    estado: list[_Etiqueta] | None = Field(default=None, max_length=20)
    ccaa: list[_Etiqueta] | None = Field(default=None, max_length=30)
    tecnologia: list[_Etiqueta] | None = Field(default=None, max_length=30)
    importe_min: float | None = Field(default=None, ge=0)
    importe_max: float | None = Field(default=None, ge=0)
    desde: str | None = None
    hasta: str | None = None
    limite: int = Field(default=20, ge=1, le=50)

    @field_validator("desde", "hasta")
    @classmethod
    def _fecha_iso(cls, v: str | None) -> str | None:
        """``YYYY-MM-DD`` y un día real (el repositorio ignoraría en silencio otro formato)."""
        if v is None:
            return None
        if not _FECHA.fullmatch(v):
            raise ValueError("la fecha debe tener el formato YYYY-MM-DD")
        date.fromisoformat(v)
        return v

    @model_validator(mode="after")
    def _rango_de_fechas(self) -> _EntradaBuscarLicitaciones:
        if self.desde is not None and self.hasta is not None and self.desde > self.hasta:
            raise ValueError("'desde' no puede ser posterior a 'hasta'")
        return self


class _EntradaBuscarEnPliegos(_Entrada):
    pregunta: str = Field(min_length=1, max_length=1_000)
    id_externo: _IdExterno | None = None
    limite: int = Field(default=10, ge=1, le=20)


class _EntradaFicha(_Entrada):
    id_externo: _IdExterno


def _fragmento_json(f: Fragmento) -> JSONValue:
    """Fragmento como JSON sin pasar por ``serializar_valor``.

    Su ``texto`` ya está acotado a 1 500 caracteres en ``Fragmento``; el tope de
    celda de ``serializar_valor`` (1 000, con marca ``…[+N]``) lo cortaría otra
    vez y la marca mentiría sobre lo que se perdió del documento.
    """
    return {
        "id_externo": f.id_externo,
        "documento": f.documento,
        "tipo": f.tipo,
        "pagina": f.pagina,
        "texto": f.texto,
    }


def _como_dict(valor: JSONValue) -> dict[str, JSONValue]:
    # `serializar_valor` de un dict siempre devuelve un dict; el assert lo demuestra a mypy.
    assert isinstance(valor, dict)
    return valor


def buscar_licitaciones(
    texto: str,
    estado: list[str] | None = None,
    ccaa: list[str] | None = None,
    tecnologia: list[str] | None = None,
    importe_min: float | None = None,
    importe_max: float | None = None,
    desde: str | None = None,
    hasta: str | None = None,
    limite: int = 20,
) -> dict[str, JSONValue]:
    """Busca licitaciones por texto (título, descripción, órgano...) con filtros opcionales.

    Úsala para localizar expedientes concretos y obtener su ``id_externo``;
    para agregar, contar o cruzar tablas usa ``consultar_sql``.

    IMPORTANTE: solo cubre las licitaciones con tecnología asignada
    (``licitaciones.tecnologia`` no vacía), que es el universo del producto. El
    resto del corpus (licitaciones sin clasificar) NO aparece aquí: para
    recorrerlo entero consulta la tabla ``licitaciones`` con ``consultar_sql``.

    ``texto`` busca por subcadena sin distinguir mayúsculas ni acentos (vacío =
    sin filtro de texto). ``estado``, ``ccaa`` y ``tecnologia`` son listas de
    valores exactos (los códigos de ``estado`` y las tecnologías se ven con
    ``describir_esquema``). ``importe_min``/``importe_max`` acotan el importe en
    euros; ``desde``/``hasta`` acotan la fecha de publicación (``YYYY-MM-DD``,
    ambos incluidos). ``limite``: de 1 a 50 (por defecto 20).

    ``desde`` no puede ser posterior a ``hasta``. Devuelve ``{"total": N,
    "resultados": [...]}``: ``total`` cuenta todas las coincidencias,
    ``resultados`` solo las primeras ``limite`` (más recientes primero); los
    textos largos de cada fila se recortan a 1 000 caracteres.
    """
    e = _EntradaBuscarLicitaciones(
        texto=texto,
        estado=estado,
        ccaa=ccaa,
        tecnologia=tecnologia,
        importe_min=importe_min,
        importe_max=importe_max,
        desde=desde,
        hasta=hasta,
        limite=limite,
    )
    filas, total = search_advanced(
        q=e.texto or None,
        estado=e.estado,
        ccaa=e.ccaa,
        tecnologia=e.tecnologia,
        importe_min=e.importe_min,
        importe_max=e.importe_max,
        fecha_desde=e.desde,
        fecha_hasta=e.hasta,
        limit=e.limite,
    )
    return _como_dict(serializar_valor({"total": total, "resultados": filas}))


def buscar_en_pliegos(
    pregunta: str, id_externo: str | None = None, limite: int = 10
) -> dict[str, JSONValue]:
    """Recupera los fragmentos de los pliegos (PCAP/PPT) más relevantes para una pregunta.

    Úsala para responder cosas que solo están en el texto de los pliegos
    (plazos, penalidades, solvencia exigida, criterios, requisitos técnicos).
    Para datos estructurados (importes, adjudicatarios, lotes) usa
    ``ficha_licitacion`` o ``consultar_sql``.

    Con ``id_externo`` busca en los pliegos de ese expediente. Sin él, busca
    primero los 5 expedientes que mejor casan con la pregunta por texto
    completo y devuelve fragmentos de todos ellos, mezclados por relevancia.
    ``limite``: de 1 a 20 fragmentos (por defecto 10); cada texto se recorta a
    1 500 caracteres.

    Devuelve ``{"fragmentos": [{"id_externo", "documento", "tipo", "pagina",
    "texto"}, ...]}``. Si el expediente no tiene pliegos indexados la lista
    sale vacía y se añade un ``aviso``.
    """
    e = _EntradaBuscarEnPliegos(pregunta=pregunta, id_externo=id_externo, limite=limite)
    fragmentos = fragmentos_de_pliego(e.pregunta, id_externo=e.id_externo, limite=e.limite)
    salida: dict[str, JSONValue] = {"fragmentos": [_fragmento_json(f) for f in fragmentos]}
    if not fragmentos:
        salida["aviso"] = (
            "No hay fragmentos de pliego para esta consulta: el expediente no existe, no "
            "tiene pliegos indexados o ningún expediente casa con la pregunta. Sin "
            "id_externo la búsqueda exige todos los términos a la vez: reintenta con menos "
            "palabras clave, o con el id_externo del expediente (ver buscar_licitaciones)."
            if e.id_externo is None
            else "No hay fragmentos de pliego para este expediente: no existe o no tiene "
            "pliegos indexados."
        )
    return salida


def ficha_licitacion(id_externo: str) -> dict[str, JSONValue]:
    """Devuelve el expediente completo de una licitación por su ``id_externo``.

    Reúne en una sola llamada: ``licitacion`` (todas las columnas del anuncio),
    ``canonica`` (``id_externo`` del anuncio original si este es una
    republicación), ``lotes``, ``adjudicaciones`` (con lote y adjudicatario),
    ``criterios`` de adjudicación, ``solvencia`` y ``garantias`` exigidas
    (condiciones oficiales de CODICE) y ``ficha_pliego`` (datos extraídos de
    los pliegos, o ``null``). Es el atajo a ~7 consultas SQL; úsala cuando ya
    conozcas el ``id_externo`` (búscalo con ``buscar_licitaciones``). Los
    textos largos se recortan a 1 000 caracteres.
    """
    e = _EntradaFicha(id_externo=id_externo)
    expediente = expediente_completo(e.id_externo)
    if expediente is None:
        eco = e.id_externo if len(e.id_externo) <= _MAX_ECO else f"{e.id_externo[:_MAX_ECO]}…"
        raise ErrorHerramienta(
            f"No existe la licitación {eco!r}.",
            "búscala con buscar_licitaciones",
        )
    return _como_dict(serializar_valor(expediente))
