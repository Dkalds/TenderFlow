"""Registro de páginas — mapea nombres de pestaña a funciones render."""

from __future__ import annotations

from collections.abc import Callable
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from dashboard.pages._base import PageContext

from dashboard.pages import (
    active_learning,
    admin,
    admin_flags,
    calendario,
    calidad_datos,
    clusters,
    comparador,
    competidores,
    detalle,
    geografia,
    investigador,
    licitadores,
    mi_watchlist,
    observabilidad,
    organos,
    pipeline_alertas,
    proyectos_modulos,
    resumen,
    tecnologias,
    tendencias,
    tendencias_cpv,
    utes,
)

PAGE_REGISTRY: dict[str, Callable[[PageContext], None]] = {
    "Resumen": resumen.render,
    "Tendencias": tendencias.render,
    "Tendencias CPV": tendencias_cpv.render,
    "Calendario": calendario.render,
    "Comparador": comparador.render,
    "Órganos": organos.render,
    "Geografía": geografia.render,
    "Proyectos & Módulos": proyectos_modulos.render,
    "Tecnologías": tecnologias.render,
    "Detalle": detalle.render,
    "Competidores": competidores.render,
    "Licitadores": licitadores.render,
    "UTEs": utes.render,
    "Pipeline & Alertas": pipeline_alertas.render,
    "Mi Watchlist": mi_watchlist.render,
    "Investigador": investigador.render,
    "Observabilidad": observabilidad.render,
    "Calidad de Datos": calidad_datos.render,
    "Clusters": clusters.render,
    "Administración": admin.render,
    "Feature Flags": admin_flags.render,
    "Active Learning": active_learning.render,
}
