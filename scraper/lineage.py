"""Versionado reproducible del universo de inclusión del scraper."""

from __future__ import annotations

import hashlib
import json


def current_filter_version() -> str:
    """Hash estable del filtro que decide el universo tecnológico observado."""
    from config.keywords import TECHNOLOGY_KEYWORDS

    canonical: dict[str, object] = {
        technology: sorted({keyword.casefold() for keyword in keywords})
        for technology, keywords in sorted(TECHNOLOGY_KEYWORDS.items())
    }
    # La regla de universo forma parte del filtro tanto como el diccionario:
    # desde 2026-09 PLACSP conserva todo su CPV 48/72 (``cpv_ti_universe``),
    # así que las series anteriores y posteriores no son comparables y el hash
    # tiene que cambiar aunque no cambie una sola keyword.
    canonical["__universo__"] = {"cpv_ti": ["48", "72"], "version": 1}
    payload = json.dumps(canonical, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return "keywords-" + hashlib.sha256(payload.encode("utf-8")).hexdigest()[:12]
