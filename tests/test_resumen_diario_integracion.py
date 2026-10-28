"""El resumen diario con su pliego, de la base al correo (B3 del plan 2026-10).

CU-04 — lo que la regla casa llega por correo con fecha límite, importe base,
solvencia del pliego y veredicto del checklist. Recorre el camino real de
``send_pending_digests``: ``load_pending_digests`` con las columnas del importe
y la organización de la regla, la carga en lote de fichas y solvencia oficial
(``TenderFactSheetsRepository.get_many``,
``CondicionesOficialesRepository.solvencia_de``) y el checklist contra la
capacidad guardada. Solo el transporte del correo es un doble.
"""

from __future__ import annotations

from typing import Any
from unittest.mock import patch

import pytest

from db.database import connect
from db.repositories.condiciones_oficiales import CondicionesOficialesRepository
from db.repositories.organization_capabilities import OrganizationCapabilitiesRepository
from db.repositories.organizations import OrganizationRepository
from db.repositories.tender_fact_sheets import TenderFactSheetsRepository
from services.watchlist_rules import WatchlistRule, create_rule

_CITA = [{"documento_id": 11, "page_number": 13, "quote": "Volumen anual igual o superior."}]


def _lic(id_externo: str, **campos: Any) -> None:
    fila: dict[str, Any] = {
        "id_externo": id_externo,
        "titulo": f"Soporte {id_externo}",
        "fuente": "placsp",
        "estado": "PUB",
        "organo_contratacion": "Consejería de Hacienda",
        "fecha_publicacion": "2026-10-25",
        "fecha_limite": "2026-11-20T14:00:00+00:00",
        "fecha_extraccion": "2026-10-25T08:00:00+00:00",
    }
    fila.update(campos)
    columnas = ", ".join(fila)
    marcadores = ", ".join(["%s"] * len(fila))
    with connect() as c:
        c.execute(
            f"INSERT INTO licitaciones ({columnas}) VALUES ({marcadores})",  # noqa: S608 -- columnas fijadas por el test
            tuple(fila.values()),
        )


@pytest.fixture()
def correo(tmp_db: Any) -> dict[str, Any]:
    """Una organización con capacidad, una regla con correo y dos coincidencias."""
    from db.users import create_user

    owner = create_user(
        email="resumen@example.test",
        password_hash="test-hash",  # pragma: allowlist secret
        display_name="resumen",
    )
    org = int(OrganizationRepository().create_organization("Equipo resumen", owner)["id"])
    OrganizationCapabilitiesRepository().replace(
        org,
        certificaciones=[],
        facturacion=[{"ejercicio": 2025, "importe_eur": 5_000_000}],
        referencias=[],
        perfiles_equipo=[],
    )
    clave = "clave-resumen"
    regla = create_rule(
        clave,
        WatchlistRule(nombre="SAP", tecnologia="SAP"),
        user_id=owner,
        organization_id=org,
    )

    # Con ficha y base declarada; sin ficha y base desconocida.
    _lic(
        "RES-1",
        importe=250_000.0,
        importe_tipo="sin_iva",
        importe_base_sin_iva=250_000.0,
        tecnologia="SAP",
    )
    _lic("RES-2", importe=90_000.0, importe_tipo="desconocido", tecnologia="SAP")
    TenderFactSheetsRepository().upsert(
        licitacion_id="RES-1",
        status="extracted",
        extraction_version="v3",
        model="test",
        facts={
            "economic_solvency": [
                {
                    "description": "Volumen anual de negocios superior a 300.000 euros.",
                    "amount_eur": 300_000,
                    "confidence": 0.9,
                    "evidence": _CITA,
                }
            ]
        },
        field_count=1,
        evidence_count=1,
    )
    with connect() as c:
        for lic in ("RES-1", "RES-2"):
            c.execute(
                "INSERT INTO pending_digests "
                "(user_key, user_id, recipient_email, entry_id, licitacion_id, frequency, "
                " matched_at) VALUES (%s, %s, 'resumen@example.test', %s, %s, 'daily', "
                " '2026-10-26')",
                (clave, owner, regla, lic),
            )
    return {"org": org, "regla": regla}


def test_el_correo_lleva_base_solvencia_y_checklist(correo: dict[str, Any]) -> None:
    from scheduler.watchlist_alerts import send_pending_digests

    with (
        patch("services.app_urls.frontend_base_url", return_value="https://app.example"),
        patch("scheduler.watchlist_alerts.enviar_email_transaccional", return_value=True) as envio,
    ):
        assert send_pending_digests("daily") == 1

    texto = envio.call_args.kwargs["texto"]
    html = envio.call_args.kwargs["html"]
    assert "250.000 € sin IVA" in texto
    assert "fecha límite 2026-11-20" in texto
    assert "Solvencia económica: Volumen anual de negocios superior a 300.000 euros. (cumple)" in (
        texto
    )
    assert "Checklist frente a la capacidad de tu organización: cumple" in texto
    # La segunda, sin ficha: base desconocida y ni una línea de pliego.
    assert "base desconocida" in texto
    assert "90.000 €" not in texto
    assert texto.count("Solvencia que pide el pliego:") == 1
    assert "Ficha: https://app.example/detalle?lic=RES-1" in texto
    assert html.count("Abrir la ficha") == 2


def test_un_fallo_cargando_el_pliego_no_para_el_correo(correo: dict[str, Any]) -> None:
    from scheduler.watchlist_alerts import send_pending_digests

    with (
        patch.object(TenderFactSheetsRepository, "get_many", side_effect=RuntimeError("caída")),
        patch("scheduler.watchlist_alerts.enviar_email_transaccional", return_value=True) as envio,
    ):
        assert send_pending_digests("daily") == 1
    texto = envio.call_args.kwargs["texto"]
    assert "250.000 € sin IVA" in texto
    assert "Solvencia que pide el pliego:" not in texto


def test_lectura_en_lote_de_fichas_y_solvencia(correo: dict[str, Any]) -> None:
    fichas = TenderFactSheetsRepository().get_many(["RES-1", "RES-2", "NO-EXISTE"])
    assert set(fichas) == {"RES-1"}
    assert fichas["RES-1"]["facts"]["economic_solvency"][0]["amount_eur"] == 300_000

    with connect() as c:
        c.execute(
            "INSERT INTO licitacion_solvencia "
            "(licitacion_id, lote_numero, orden, clase, tipo_codigo, descripcion, "
            " umbral_importe, moneda, fecha_extraccion) "
            "VALUES ('RES-2', NULL, 1, 'tecnica', '2', 'Relación de servicios', NULL, NULL, "
            " '2026-10-25')"
        )
    solvencia = CondicionesOficialesRepository().solvencia_de(["RES-1", "RES-2"])
    assert list(solvencia) == ["RES-2"]
    (fila,) = solvencia["RES-2"]
    assert (fila["clase"], fila["descripcion"]) == ("tecnica", "Relación de servicios")
    assert CondicionesOficialesRepository().solvencia_de([]) == {}
