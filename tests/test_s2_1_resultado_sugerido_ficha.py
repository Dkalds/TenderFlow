"""S2.1 — la propuesta de cierre por NIF llega de verdad a la ficha.

`services/pursuit_awards.sugerir_resultado` existía y estaba probada desde
#274, pero ningún llamador de producción la usaba: `PursuitAdjudicacionDetectada`
se construía sin `resultado_sugerido` y el campo salía `null` siempre. Estos
tests fijan el cableado —que la ficha lo calcule con la organización que mira—
y el límite del cableado: propone, no cierra.

No tocan Postgres: se sustituye el repositorio de `organization_nifs`, que es
lo único que baja a la BD en esta cadena.
"""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager
from typing import Any
from unittest.mock import patch

import pytest

import services.pursuit_awards as awards
import services.pursuits as mod

# NIFs con el formato fiscal español. Constantes y no en línea por lo mismo que
# en `tests/test_s2_pursuit_awards_nif.py`: detect-secrets los lee como cadenas
# de alta entropía y el pragma tiene que quedar pegado al literal.
_NIF_PROPIO = "B12345678"  # pragma: allowlist secret
_NIF_AJENO = "A87654321"  # pragma: allowlist secret

_ORGANIZACION = 7


@contextmanager
def _identidad_declarada(*, nifs: list[str], empresa_ids: list[int] | None = None) -> Iterator[Any]:
    """Sustituye la lectura de ``organization_nifs`` por una identidad fija."""
    with (
        patch.object(awards._nif_repo, "nifs", return_value=list(nifs)) as lector,
        patch.object(awards._nif_repo, "empresa_ids", return_value=list(empresa_ids or [])),
    ):
        yield lector


def _fila(**extra: Any) -> dict[str, Any]:
    base: dict[str, Any] = {
        "id": 5,
        "organization_id": _ORGANIZACION,
        "licitacion_id": "LIC-1",
        "status": "submitted",
    }
    base.update(extra)
    return base


def _adjudicaciones(nif: str | None) -> list[dict[str, Any]]:
    return [
        {
            "nombre": "Adjudicataria SL",
            "nif": nif,
            "importe_adjudicado": 100_000.0,
            "fecha_adjudicacion": "2026-08-20T00:00:00",
            "n_ofertas_recibidas": 3,
            "lote_id": None,
        }
    ]


@contextmanager
def _adjudicacion_publicada(nif: str | None) -> Iterator[None]:
    with (
        patch.object(mod._adj_repo, "list_for_licitacion", return_value=_adjudicaciones(nif)),
        patch.object(mod._lic_repo, "get_by_id", return_value={"estado": "ADJ"}),
    ):
        yield


@pytest.mark.parametrize(
    ("nif_publicado", "esperado"),
    [(_NIF_PROPIO, "won"), (_NIF_AJENO, "lost"), (None, None)],
)
def test_la_ficha_propone_el_resultado_calculado_por_nif(
    nif_publicado: str | None, esperado: str | None
) -> None:
    """El caso que el DTO declaraba y el backend nunca rellenaba."""
    with _adjudicacion_publicada(nif_publicado), _identidad_declarada(nifs=[_NIF_PROPIO]):
        detectada = mod._adjudicacion_detectada(_fila(), organization_id=_ORGANIZACION)

    assert detectada is not None
    assert detectada.resultado_sugerido == esperado


def test_una_organizacion_sin_nifs_declarados_no_recibe_propuesta() -> None:
    """`None` es «no lo sé», no «no ganó»: es el comportamiento previo a S2.1."""
    with _adjudicacion_publicada(_NIF_AJENO), _identidad_declarada(nifs=[]):
        detectada = mod._adjudicacion_detectada(_fila(), organization_id=_ORGANIZACION)

    assert detectada is not None and detectada.resultado_sugerido is None


def test_sin_organizacion_resuelta_no_se_consulta_la_identidad() -> None:
    """El ámbito lo pone quien llama; sin él no se inventa una organización."""
    with _adjudicacion_publicada(_NIF_PROPIO), _identidad_declarada(nifs=[_NIF_PROPIO]) as lector:
        detectada = mod._adjudicacion_detectada(_fila())

    assert detectada is not None and detectada.resultado_sugerido is None
    lector.assert_not_called()


def test_proponer_no_es_cerrar() -> None:
    """La propuesta viaja junto al cierre pendiente: la persona sigue decidiendo."""
    with _adjudicacion_publicada(_NIF_PROPIO), _identidad_declarada(nifs=[_NIF_PROPIO]):
        abierta = mod._adjudicacion_detectada(_fila(), organization_id=_ORGANIZACION)
        cerrada = mod._adjudicacion_detectada(_fila(status="won"), organization_id=_ORGANIZACION)

    assert abierta is not None and cerrada is not None
    assert abierta.resultado_sugerido == "won" and abierta.cierre_pendiente is True
    # En una oportunidad ya cerrada la propuesta sigue siendo sólo contexto.
    assert cerrada.resultado_sugerido == "won" and cerrada.cierre_pendiente is False


def test_un_fallo_leyendo_los_nifs_no_tumba_la_ficha() -> None:
    """La propuesta es información añadida; la adjudicación ya se muestra sin ella."""
    with (
        _adjudicacion_publicada(_NIF_PROPIO),
        patch.object(awards._nif_repo, "nifs", side_effect=RuntimeError("BD caída")),
    ):
        detectada = mod._adjudicacion_detectada(_fila(), organization_id=_ORGANIZACION)

    assert detectada is not None
    assert detectada.resultado_sugerido is None
    assert detectada.importe_total == 100_000.0


def test_el_detalle_pasa_la_organizacion_ya_resuelta() -> None:
    """El cableado real: `_detalle` conoce el ámbito validado, la fila no.

    Se comprueba aquí porque es justo lo que faltaba en #274 — la función
    existía, nadie le pasaba la organización— y porque usar
    `row["organization_id"]` en vez del ámbito resuelto sería confiar en la
    fila para decidir contra qué identidad se cruza.
    """
    fila_detalle: dict[str, Any] = {
        "id": 5,
        "organization_id": _ORGANIZACION,
        "licitacion_id": "LIC-1",
        "status": "submitted",
        "decision": "go",
        "outcome": "pending",
        "identified_at": "2026-07-30T10:00:00Z",
        "created_at": "2026-07-30T10:00:00Z",
        "updated_at": "2026-07-30T10:00:00Z",
        "version": 4,
    }
    with (
        patch.object(mod._repo, "list_events", return_value=[]),
        patch.object(mod, "_adjudicacion_detectada", return_value=None) as detectada,
    ):
        mod._detalle(fila_detalle, _ORGANIZACION, 5)

    assert detectada.call_args.kwargs["organization_id"] == _ORGANIZACION
