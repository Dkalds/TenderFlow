"""Validación de entrada de POST /search/semantic (sin BD).

Regresión del hallazgo de Schemathesis: un ``q`` con bytes NUL (0x00) llegaba
hasta Postgres, que lo rechaza con ``DataError`` — un 5xx para el cliente. El
DTO lo corta ahora en validación (422).
"""

from __future__ import annotations

import pytest
from pydantic import ValidationError


def test_semantic_request_rejects_nul_in_q():
    from api.routes.search import SemanticSearchRequest

    with pytest.raises(ValidationError, match="NUL"):
        SemanticSearchRequest(q="consulta\x00maliciosa")


def test_semantic_request_rejects_nul_in_filters():
    from api.routes.search import SemanticSearchRequest

    with pytest.raises(ValidationError, match="NUL"):
        SemanticSearchRequest(q="consulta normal", ccaa=["Mad\x00rid"])
    with pytest.raises(ValidationError, match="NUL"):
        SemanticSearchRequest(q="consulta normal", tecnologia=["S\x00AP"])
    with pytest.raises(ValidationError, match="NUL"):
        SemanticSearchRequest(q="consulta normal", fecha_desde="2026\x00-01-01")


def test_semantic_request_accepts_normal_input():
    from api.routes.search import SemanticSearchRequest

    req = SemanticSearchRequest(q="SAP S/4HANA consultoría", ccaa=["Madrid"])
    assert req.q.startswith("SAP")
