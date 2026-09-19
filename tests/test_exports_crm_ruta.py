"""F6.3 — ``GET /exports/crm``: el tablero de oportunidades en CSV para el CRM.

``services/exports_crm.py`` tenía el mapeo (``payload_de_pursuit``,
``a_csv_fila``) y solo lo usaban los tests: no había forma de descargarlo. Aquí
se fija el fichero —cabeceras, BOM, etapa traducida, saneado de fórmulas—, que
la organización se resuelve en el servicio con los filtros del tablero, y que
la ruta audita la descarga como ``format=crm``.
"""

from __future__ import annotations

import asyncio
import csv
import io
from collections.abc import Iterator
from contextlib import contextmanager
from typing import Any
from unittest.mock import patch

import pytest

import services.exports_crm as svc
from services.exports_crm import CABECERAS_CSV, csv_crm


def _fila(**campos: Any) -> dict[str, Any]:
    return {
        "licitacion_id": "ES-1",
        "tender_title": "Soporte SAP S/4HANA",
        "organo_contratacion": "Ayuntamiento de Móstoles",
        "tender_importe": 120000.0,
        "status": "preparing",
        "tender_deadline": "2026-10-15T14:00:00",
        "responsable": "Ana",
        "tender_url": "https://contrataciondelestado.es/1",
        **campos,
    }


def _leer(contenido: bytes) -> list[list[str]]:
    assert contenido.startswith(b"\xef\xbb\xbf"), "sin BOM Excel rompe los acentos"
    return list(csv.reader(io.StringIO(contenido.decode("utf-8-sig"))))


def test_el_csv_lleva_las_cabeceras_del_mapeo_y_una_fila_por_oportunidad() -> None:
    filas = _leer(csv_crm([_fila(), _fila(licitacion_id="ES-2", status="won")]))
    assert tuple(filas[0]) == CABECERAS_CSV
    assert len(filas) == 3
    primera = dict(zip(CABECERAS_CSV, filas[1], strict=True))
    assert primera["external_id"] == "ES-1"
    assert primera["account_name"] == "Ayuntamiento de Móstoles"
    assert primera["stage"] == "Proposal"
    assert primera["close_date"] == "2026-10-15"
    assert primera["amount"] == "120000.0"
    assert primera["currency"] == "EUR"
    assert dict(zip(CABECERAS_CSV, filas[2], strict=True))["stage"] == "Closed Won"


def test_sin_importe_la_celda_va_vacia_no_a_cero() -> None:
    filas = _leer(csv_crm([_fila(tender_importe=None)]))
    assert dict(zip(CABECERAS_CSV, filas[1], strict=True))["amount"] == ""


def test_un_titulo_que_empieza_por_igual_no_es_una_formula() -> None:
    filas = _leer(csv_crm([_fila(tender_title='=HYPERLINK("x")')]))
    assert not dict(zip(CABECERAS_CSV, filas[1], strict=True))["opportunity_name"].startswith("=")


def test_sin_oportunidades_el_fichero_trae_solo_la_cabecera() -> None:
    assert _leer(csv_crm([])) == [list(CABECERAS_CSV)]


def test_el_servicio_resuelve_la_organizacion_y_pasa_los_filtros(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    llamadas: dict[str, Any] = {}

    @contextmanager
    def _alcance(user_id: int, organization_id: int | None, **_: Any) -> Iterator[tuple[int, str]]:
        llamadas["alcance"] = (user_id, organization_id)
        yield 7, "member"

    def _export_rows(self: Any, organization_id: int, **kwargs: Any) -> list[dict[str, Any]]:
        llamadas["export_rows"] = (organization_id, kwargs)
        return [_fila()]

    monkeypatch.setattr("services.organizations.alcance_resuelto", _alcance)
    monkeypatch.setattr("db.repositories.pursuits.PursuitRepository.export_rows", _export_rows)
    contenido, n = svc.render_crm_export(
        3, organization_id=7, status="submitted", responsible_user_id=5, limit=50
    )
    assert n == 1
    assert llamadas["alcance"] == (3, 7)
    assert llamadas["export_rows"] == (
        7,
        {"status": "submitted", "responsible_user_id": 5, "limit": 50},
    )
    assert _leer(contenido)[1][0] == "ES-1"


def test_la_ruta_devuelve_el_csv_y_audita_formato_crm() -> None:
    import api.routes.exports as exports_mod

    auditado: dict[str, Any] = {}

    async def _correr() -> tuple[Any, bytes]:
        respuesta = await exports_mod.download_crm(
            organization_id=7,
            pursuit_status=None,
            responsible_user_id=None,
            limit=100,
            user={"user_id": 3},
        )
        cuerpo = b"".join([trozo async for trozo in respuesta.body_iterator])
        return respuesta, cuerpo

    with (
        patch(
            "services.exports_crm.render_crm_export", return_value=(csv_crm([_fila()]), 1)
        ) as render,
        patch.object(exports_mod, "log_event", lambda **kw: auditado.update(kw)),
    ):
        respuesta, cuerpo = asyncio.run(_correr())

    assert render.call_args.kwargs["organization_id"] == 7
    assert respuesta.media_type.startswith("text/csv")
    assert "oportunidades_crm_" in respuesta.headers["content-disposition"]
    assert _leer(cuerpo)[1][0] == "ES-1"
    assert auditado["detail"]["format"] == "crm"


def test_sin_membresia_es_un_403() -> None:
    from fastapi import HTTPException

    import api.routes.exports as exports_mod
    from services.organizations import OrganizationAccessError

    with (
        patch(
            "services.exports_crm.render_crm_export",
            side_effect=OrganizationAccessError("No perteneces a esa organización."),
        ),
        pytest.raises(HTTPException) as error,
    ):
        asyncio.run(
            exports_mod.download_crm(
                organization_id=99,
                pursuit_status=None,
                responsible_user_id=None,
                limit=100,
                user={"user_id": 3},
            )
        )
    assert error.value.status_code == 403
