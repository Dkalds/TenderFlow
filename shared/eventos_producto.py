"""Catálogo de eventos de producto que la API acepta (`POST /telemetria/eventos`).

La web los emitía solo a Vercel Web Analytics, y en el plan Hobby los eventos
personalizados no se guardan (la API responde ``402``, medido el 2026-10-25):
los 23 del catálogo se perdían, y la Ola 3 del plan 2026-10 («medir y
recortar») no tenía con qué decidir qué espacio sobra. Desde el 2026-11-03 la
web los manda también aquí y la API solo los **cuenta** en Prometheus, por
evento y por cada propiedad con su valor: sin tabla, sin usuario, sin
organización.

:data:`PROPIEDADES` es copia de ``PROPIEDADES_PERMITIDAS`` de
``web/src/lib/analytics.ts`` y ``tests/test_unit_eventos_producto.py`` falla si
se separan. Lo que no está aquí se descarta, igual que en la web.

Las etiquetas de Prometheus no pueden crecer sin techo: cada combinación
(evento, propiedad, valor) es una serie que vive en memoria. Los valores solo
pasan si tienen forma de categoría (:data:`_VALOR`), y a partir de
:data:`MAX_SERIES` combinaciones distintas en el proceso un valor nuevo se
cuenta como ``otro``.
"""

from __future__ import annotations

import re
import threading
from collections.abc import Mapping
from typing import Final

PROPIEDADES: Final[Mapping[str, tuple[str, ...]]] = {
    "sesion_iniciada": ("metodo",),
    "espacio_abierto": (
        "espacio",
        "origen",
        "vista",
        "glosario_abierto",
        "hito_visto",
        "evidencia_abierta",
        "banda",
    ),
    "radar_triaje": ("accion", "explicacion_abierta", "flag"),
    "licitacion_seguida": ("accion",),
    "pursuit_creado": ("primera_vez", "origen"),
    "pursuit_estado_cambiado": ("estado", "motivo"),
    "perfil_configurado": ("primera_vez", "nivel"),
    "onboarding_ocultado": ("progreso",),
    "regla_creada": ("primera_vez", "ruido_avisado", "origen"),
    "asistente_usado": ("modo", "ambito", "resultado", "n_expedientes"),
    "asistente_feedback": ("modo", "util"),
    "export_lanzado": ("formato", "recurso"),
    "busqueda_realizada": ("superficie", "con_resultados", "filtros", "tipo_resultado"),
    "vista_experimental_abierta": ("vista", "flag"),
    "vista_guardada": ("primera_vez", "origen"),
    "organo_seguido": ("accion",),
    "etiqueta_aplicada": ("objeto",),
    "simulador_usado": ("formula_tipo", "con_tarifas"),
    "kit_abierto": ("items",),
    "guion_generado": ("criterios",),
    "partners_consultado": ("con_resultados",),
    "cartera_abierta": ("origen",),
    "dato_reportado": ("tipo",),
}

#: Forma de un valor categórico: corto y sin espacios (``radar``, ``1-2``, ``3+``).
_VALOR: Final = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.+-]{0,47}$")

#: Combinaciones (evento, propiedad, valor) distintas que admite el proceso.
MAX_SERIES: Final = 2000

_vistas: set[tuple[str, str, str]] = set()
_cerrojo = threading.Lock()


def dimensiones(evento: str, propiedades: Mapping[str, str]) -> list[tuple[str, str]]:
    """Las ``(propiedad, valor)`` que se cuentan; lo que no es del catálogo se descarta.

    ``evento`` tiene que estar en :data:`PROPIEDADES` (lo valida quien llama).
    """
    permitidas = PROPIEDADES[evento]
    salida: list[tuple[str, str]] = []
    for propiedad in permitidas:
        valor = propiedades.get(propiedad)
        if valor is None or not _VALOR.match(valor):
            continue
        salida.append((propiedad, _con_techo(evento, propiedad, valor)))
    return salida


def _con_techo(evento: str, propiedad: str, valor: str) -> str:
    clave = (evento, propiedad, valor)
    with _cerrojo:
        if clave in _vistas:
            return valor
        if len(_vistas) >= MAX_SERIES:
            return "otro"
        _vistas.add(clave)
        return valor
