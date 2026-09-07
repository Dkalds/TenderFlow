"""Códigos CODICE de procedimiento, tramitación y tipo de contrato → etiqueta.

``v85`` guarda ``procedimiento`` y ``tramitacion`` como **código crudo** y
explica por qué: traducir en ingesta obliga a congelar una copia de las listas
controladas de la Plataforma, que envejece en silencio y convierte un código
nuevo en una etiqueta plausible pero falsa. Esa decisión no se revierte aquí.
Lo que hace este módulo es lo que aquel docstring dejaba pendiente — «la
etiqueta legible es trabajo de la capa de presentación, con la codelist
delante»— y lo hace en **un solo sitio**, del lado del servidor, para que la
consola no acabe con su propia copia (invariante 3 de ``web/AGENTS.md``: sin
hardcode que el backend debe proveer).

Procedencia de cada mapa (verificada el 2026-09-06 contra el servidor de la
Plataforma, no de memoria)
--------------------------------------------------------------------------
- **Procedimiento**: unión de ``SyndicationTenderingProcessCode-2.07.gc`` —la
  lista que el ``listURI`` del ATOM que ingerimos declara— y
  ``TenderingProcessCode-2.13.gc``, la vigente del CODICE completo. Coinciden
  en 1-13 salvo matices de redaccion; 2.13 anade el 14. Se toman las dos
  porque el corpus mezcla expedientes de ambas épocas y ningún código de una
  contradice a la otra.
- **Tipo de contrato**: ``SyndicationContractCode-2.07.gc``.
- **Tramitación**: **no hay codelist publicada**. El ``listURI`` que emite el
  ATOM (``SyndicationUrgencyCode-2.07.gc``) devuelve 404 en el servidor de la
  Plataforma, y no existe ninguna lista de urgencia en ``codice/cl/latest/``.
  El mapa sale por tanto de la fuente normativa —LCSP (Ley 9/2017) arts. 119
  (tramitacion urgente) y 120 (emergencia), sobre la ordinaria del 116. Es
  el unico de los tres mapas que no se puede reverificar contra un ``.gc``, y
  el comentario sobre ``TRAMITACIONES`` lo dice ahi mismo para que nadie lo
  "corrija" contra una lista que no existe.

Cómo se comporta ante un código que no está
-------------------------------------------
No se inventa etiqueta. :func:`etiqueta_procedimiento` devuelve el código tal
cual y :func:`catalogado` dice que no, que es lo que la UI convierte en el
aviso «código no catalogado» y lo que ``/analytics/quality`` cuenta. Un código
nuevo se ve como código nuevo; nunca como el vecino más parecido.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from types import MappingProxyType
from typing import Final, Literal

__all__ = [
    "CODICE_PROCEDIMIENTO_LIST_URI",
    "CODICE_TIPO_CONTRATO_LIST_URI",
    "PROCEDIMIENTOS",
    "TIPOS_CONTRATO",
    "TRAMITACIONES",
    "CodigoCatalogado",
    "Familia",
    "catalogado",
    "catalogo",
    "etiqueta_procedimiento",
    "etiqueta_tipo_contrato",
    "etiqueta_tramitacion",
    "no_catalogados",
    "opciones",
]

# Familias que este módulo cataloga. Es un `Literal` y no un `str` libre para
# que un typo en un llamante lo pare mypy y no la respuesta vacía de un dict.
Familia = Literal["procedimiento", "tramitacion", "tipo_contrato"]

CODICE_PROCEDIMIENTO_LIST_URI: Final = (
    "https://contrataciondelestado.es/codice/cl/latest/SyndicationTenderingProcessCode-2.07.gc"
)
CODICE_TIPO_CONTRATO_LIST_URI: Final = (
    "https://contrataciondelestado.es/codice/cl/latest/SyndicationContractCode-2.07.gc"
)


@dataclass(frozen=True, slots=True)
class CodigoCatalogado:
    """Un código de lista controlada con lo que hace falta para pintarlo.

    ``descripcion`` no es decoración: F1.8 pide un glosario contextual y la
    consola no puede escribirlo por su cuenta sin duplicar la lista. Viaja con
    la etiqueta desde el mismo sitio para que no puedan divergir.
    """

    codigo: str
    etiqueta: str
    descripcion: str


def _mapa(*entradas: tuple[str, str, str]) -> Mapping[str, CodigoCatalogado]:
    """``MappingProxyType`` para que un consumidor no pueda mutar el catálogo."""
    return MappingProxyType(
        {codigo: CodigoCatalogado(codigo, etiqueta, desc) for codigo, etiqueta, desc in entradas}
    )


# ── Procedimiento (cbc:ProcedureCode) ────────────────────────────────────
#
# Las descripciones dicen lo que cambia para quien licita —publicidad,
# concurrencia, negociación—, no reescriben el artículo de la ley. Quien
# necesite el texto legal tiene el enlace a /metodologia en el glosario.
PROCEDIMIENTOS: Final[Mapping[str, CodigoCatalogado]] = _mapa(
    ("1", "Abierto", "Cualquier empresa interesada puede presentar oferta. Sin negociación."),
    (
        "2",
        "Restringido",
        "Dos fases: el órgano selecciona candidatos por solvencia y solo ellos ofertan.",
    ),
    (
        "3",
        "Negociado sin publicidad",
        "El órgano invita a empresas concretas y negocia las condiciones. Sin anuncio previo.",
    ),
    (
        "4",
        "Negociado con publicidad",
        "Se anuncia y, tras las ofertas iniciales, el órgano negocia las condiciones.",
    ),
    (
        "5",
        "Diálogo competitivo",
        "El órgano dialoga con los candidatos para definir la solución antes de pedir ofertas.",
    ),
    (
        "6",
        "Contrato menor",
        "Adjudicación directa por importe bajo, sin licitación pública.",
    ),
    (
        "7",
        "Derivado de acuerdo marco",
        "Contrato basado en un acuerdo marco ya adjudicado; solo compiten sus adjudicatarios.",
    ),
    (
        "8",
        "Concurso de proyectos",
        "Un jurado selecciona un proyecto (arquitectura, ingeniería, tratamiento de datos).",
    ),
    (
        "9",
        "Abierto simplificado",
        "Abierto con plazos y trámites reducidos, para importes por debajo del umbral.",
    ),
    (
        "10",
        "Asociación para la innovación",
        "Se contrata el desarrollo de una solución que aún no existe en el mercado.",
    ),
    (
        "11",
        "Derivado de asociación para la innovación",
        "Compra de la solución desarrollada en una asociación para la innovación previa.",
    ),
    (
        "12",
        "Basado en sistema dinámico de adquisición",
        "Contrato dentro de un sistema dinámico; solo compiten las empresas ya admitidas.",
    ),
    (
        "13",
        "Licitación con negociación",
        "Se anuncia, se reciben ofertas iniciales y se negocian con los licitadores.",
    ),
    (
        "14",
        "Abierto simplificado abreviado",
        "Variante más corta del simplificado, para los importes más bajos que lo admiten.",
    ),
    (
        "100",
        "Normas internas",
        "Adjudicación por las instrucciones internas del poder adjudicador, no por la LCSP.",
    ),
    ("999", "Otros", "La fuente lo clasifica como «otros» sin más detalle."),
)


# ── Tramitación (cbc:UrgencyCode) ────────────────────────────────────────
#
# Sin codelist publicada: ver el docstring del módulo. Los tres valores son los
# de la LCSP y el corpus de CI solo trae 1 y 2, pero se cataloga también el 3
# porque la emergencia existe y aparecer sin etiqueta sería peor.
TRAMITACIONES: Final[Mapping[str, CodigoCatalogado]] = _mapa(
    ("1", "Ordinaria", "Plazos normales de presentación y de resolución."),
    (
        "2",
        "Urgente",
        "Plazos reducidos a la mitad por declararse de urgencia. Deja menos tiempo para ofertar.",
    ),
    (
        "3",
        "Emergencia",
        "Contratación inmediata ante un suceso catastrófico, sin expediente previo.",
    ),
)


# ── Tipo de contrato (SyndicationContractCode) ───────────────────────────
#
# Este mapa **corrige** el que vivía en `services/classification.py`, que tenía
# 40 como «Patrimonial» y 50 como «Privado» cuando la codelist dice 40 =
# colaboración público-privada, 50 = patrimonial y 8 = privado, y que además no
# tenía el 7, el 8, el 22 ni el 32. Dos etiquetas desplazadas y cuatro códigos
# sin etiqueta: exactamente el fallo contra el que avisa v85. Aquel módulo
# ahora delega aquí.
TIPOS_CONTRATO: Final[Mapping[str, CodigoCatalogado]] = _mapa(
    ("1", "Suministros", "Compra, alquiler o arrendamiento de bienes."),
    ("2", "Servicios", "Prestación de una actividad; es el tipo de casi todo lo tecnológico."),
    ("3", "Obras", "Ejecución de una obra o de un trabajo de construcción."),
    (
        "7",
        "Administrativo especial",
        "Contrato administrativo de objeto propio del órgano, distinto de los típicos.",
    ),
    ("8", "Privado", "Contrato sujeto a derecho privado, no a la parte administrativa de la LCSP."),
    (
        "21",
        "Gestión de servicios públicos",
        "Figura anterior a la LCSP 2017; la sustituyen las concesiones.",
    ),
    (
        "22",
        "Concesión de servicios",
        "La empresa explota el servicio y asume el riesgo operacional.",
    ),
    ("31", "Concesión de obras públicas", "Figura anterior a la LCSP 2017 para obra concesional."),
    ("32", "Concesión de obras", "La empresa construye y explota la obra asumiendo el riesgo."),
    (
        "40",
        "Colaboración público-privada",
        "Figura derogada por la LCSP 2017; solo aparece en expedientes antiguos.",
    ),
    ("50", "Patrimonial", "Compraventa o arrendamiento de bienes del patrimonio del órgano."),
    ("999", "Otros", "La fuente lo clasifica como «otros» sin más detalle."),
)


_CATALOGOS: Final[Mapping[Familia, Mapping[str, CodigoCatalogado]]] = MappingProxyType(
    {
        "procedimiento": PROCEDIMIENTOS,
        "tramitacion": TRAMITACIONES,
        "tipo_contrato": TIPOS_CONTRATO,
    }
)


def catalogo(familia: Familia) -> Mapping[str, CodigoCatalogado]:
    """El mapa de una familia. Existe para que el llamante no importe el dict."""
    return _CATALOGOS[familia]


def opciones(familia: Familia) -> list[CodigoCatalogado]:
    """Las entradas de una familia, ordenadas por código numérico.

    Orden numérico y no lexicográfico: con ``sorted`` sobre el string, el 10 se
    cuela entre el 1 y el 2 y el selector queda ilegible. Los códigos no
    numéricos (ninguno hoy) van al final, por texto, en vez de reventar.
    """
    return sorted(
        _CATALOGOS[familia].values(),
        key=lambda c: (0, int(c.codigo), "") if c.codigo.isdigit() else (1, 0, c.codigo),
    )


def _normaliza(code: str | None) -> str | None:
    """Código listo para buscar: sin espacios y sin ceros a la izquierda.

    La fuente publica ``01`` y ``1`` para el mismo procedimiento según el
    emisor. Sin esto, la mitad de los expedientes de algunos órganos saldrían
    como «código no catalogado» por un cero.
    """
    if code is None:
        return None
    limpio = code.strip()
    if not limpio:
        return None
    if limpio.isdigit():
        return str(int(limpio))
    return limpio


def _etiqueta(familia: Familia, code: str | None, *, vacio: str) -> str:
    normalizado = _normaliza(code)
    if normalizado is None:
        return vacio
    entrada = _CATALOGOS[familia].get(normalizado)
    return entrada.etiqueta if entrada is not None else normalizado


def etiqueta_procedimiento(code: str | None, *, vacio: str = "—") -> str:
    """Etiqueta legible del procedimiento. Sin catalogar → el código tal cual."""
    return _etiqueta("procedimiento", code, vacio=vacio)


def etiqueta_tramitacion(code: str | None, *, vacio: str = "—") -> str:
    """Etiqueta legible de la tramitación. Sin catalogar → el código tal cual."""
    return _etiqueta("tramitacion", code, vacio=vacio)


def etiqueta_tipo_contrato(code: str | None, *, vacio: str = "—") -> str:
    """Etiqueta legible del tipo de contrato. Sin catalogar → el código tal cual."""
    return _etiqueta("tipo_contrato", code, vacio=vacio)


def catalogado(familia: Familia, code: str | None) -> bool:
    """``True`` si el código tiene etiqueta en esta familia.

    Un código ausente (``None`` o vacío) **no** cuenta como no catalogado: es
    un hueco de cobertura, que es otra métrica y ya la mide la completitud de
    la columna. Aquí solo interesa el código presente que nadie sabe traducir.
    """
    normalizado = _normaliza(code)
    if normalizado is None:
        return True
    return normalizado in _CATALOGOS[familia]


def no_catalogados(familia: Familia, codes: list[str | None]) -> list[str]:
    """Los códigos distintos de ``codes`` que esta familia no sabe traducir.

    Lo consume ``/analytics/quality``: la vista de calidad del dato tiene que
    poder decir *cuál* es el código nuevo, no solo cuántos hay, porque el
    trabajo que abre es «añadir esta entrada al catálogo».
    """
    vistos: dict[str, None] = {}
    for code in codes:
        normalizado = _normaliza(code)
        if normalizado is not None and normalizado not in _CATALOGOS[familia]:
            vistos[normalizado] = None
    return sorted(vistos)
