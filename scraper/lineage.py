"""Versionado reproducible del universo de inclusión del scraper."""

from __future__ import annotations

import hashlib
import json


def current_filter_version() -> str:
    """Hash estable del filtro que decide el universo tecnológico observado.

    Desde C5.6 (D28) el diccionario puede venir de ``tecnologias_keywords`` y no
    sólo de ``config/keywords.py``, así que la huella se toma del **efectivo**:
    editar una keyword en ``/ops`` cambia el ``filter_version`` de las filas
    nuevas sin desplegar nada. Si se siguiera hasheando la semilla, dos corpus
    filtrados con diccionarios distintos llevarían la misma versión y dejarían de
    poder compararse — que es lo único para lo que este campo sirve.
    """
    from services.tech_dictionary import huella, vigente

    canonical: dict[str, object] = {"__diccionario__": huella(vigente())}
    # La regla de universo forma parte del filtro tanto como el diccionario:
    # desde 2026-09 PLACSP conserva todo su CPV 48/72 (``cpv_ti_universe``),
    # así que las series anteriores y posteriores no son comparables y el hash
    # tiene que cambiar aunque no cambie una sola keyword.
    canonical["__universo__"] = {"cpv_ti": ["48", "72"], "version": 1}
    payload = json.dumps(canonical, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return "keywords-" + hashlib.sha256(payload.encode("utf-8")).hexdigest()[:12]
