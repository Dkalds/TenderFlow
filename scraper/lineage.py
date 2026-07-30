"""Versionado reproducible del universo de inclusión del scraper."""

from __future__ import annotations

import hashlib
import json


def current_filter_version() -> str:
    """Hash estable del filtro que decide el universo tecnológico observado."""
    from config.keywords import TECHNOLOGY_KEYWORDS

    canonical = {
        technology: sorted({keyword.casefold() for keyword in keywords})
        for technology, keywords in sorted(TECHNOLOGY_KEYWORDS.items())
    }
    payload = json.dumps(canonical, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return "keywords-" + hashlib.sha256(payload.encode("utf-8")).hexdigest()[:12]
