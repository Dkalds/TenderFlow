"""Versionado reproducible del universo de inclusión del scraper."""

from __future__ import annotations


def current_filter_version() -> str:
    """Hash estable del filtro que decide el universo tecnológico observado.

    Desde C5.6 el diccionario vive en `tecnologias_keywords` (v126) y
    `config/keywords.py` es la semilla; el hash se calcula sobre el **vigente**,
    venga de donde venga. La propiedad que importa no cambia: dos filas
    ingeridas con el mismo `filter_version` se filtraron con el mismo
    diccionario, así que cambiar una keyword desde `/ops` cambia el linaje de
    las filas nuevas sin necesidad de un despliegue.

    La regla de universo forma parte del filtro tanto como el diccionario: desde
    2026-09 PLACSP conserva todo su CPV 48/72 (``cpv_ti_universe``), así que las
    series anteriores y posteriores no son comparables y el hash tiene que
    cambiar aunque no cambie una sola keyword. Esa regla la incorpora
    `services.tecnologias_diccionario._hash_de`, que es donde vive ahora el
    cálculo — tenerlo en dos sitios lo dejaría divergir.
    """
    from services.tecnologias_diccionario import version

    return version()
