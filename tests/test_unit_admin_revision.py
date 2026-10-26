"""Rutas de ``/admin/revision``: colas del dato y panel de verdad, sin BD.

Lo que se fija aquí es la traducción de cada resultado del repositorio o del
servicio a su respuesta: 404 para lo que ya no está pendiente, auditoría solo
cuando algo cambió y con el id del administrador (nunca su correo, ADR-030).
El recorrido con BD está en ``tests/test_escenario_revision_datos.py``.
"""

from __future__ import annotations

import asyncio
from typing import Any

import pytest
from fastapi import HTTPException, Response

import api.routes.admin_revision as ruta_mod
from services.organos import DecisionRevision
from services.verdad_dominio import MetricaVerdad, SeccionVerdad

ADMIN = {"user_id": 3, "email": "admin@example.com", "is_admin": True}


@pytest.fixture()
def auditoria(monkeypatch) -> list[dict[str, Any]]:
    eventos: list[dict[str, Any]] = []
    monkeypatch.setattr(ruta_mod, "log_event", lambda **kw: eventos.append(kw))
    return eventos


# ---------------------------------------------------------------------------
# Duplicados
# ---------------------------------------------------------------------------


def test_listado_de_duplicados_mapea_las_dos_filas(monkeypatch) -> None:
    fila = {
        "licitacion_id": "pscp:EXP-1",
        "canonical_id": "EXP-1",
        "clave_match": "org|7200|2026-05|titulo",
        "confianza": 0.8,
        "detectado_en": "2026-10-01T00:00:00+00:00",
        "titulo": "Contrato B",
        "fuente": "pscp",
        "organo": "Ajuntament",
        "fecha_publicacion": "2026-05-01",
        "importe": 1000.0,
        "titulo_canonica": "Contrato A",
        "fuente_canonica": "placsp",
        "organo_canonica": "Ajuntament",
        "fecha_publicacion_canonica": "2026-05-01",
        "importe_canonica": None,
    }
    monkeypatch.setattr(ruta_mod, "pendientes_de_revision", lambda limit: [fila])
    monkeypatch.setattr(ruta_mod, "pendientes_count", lambda: 7)

    res = asyncio.run(ruta_mod.listar_duplicados(limit=50, _admin=ADMIN))

    assert res.total == 7
    [item] = res.items
    assert item.licitacion_id == "pscp:EXP-1" and item.canonical_id == "EXP-1"
    assert item.fuente_canonica == "placsp" and item.importe_canonica is None


async def _sin_alias(id_licitacion: str, _response: object) -> str:
    """Sin BD: ningún id es un alias (``api.identidad.id_vigente``)."""
    return id_licitacion


@pytest.mark.parametrize(("aceptar", "estado"), [(True, "confirmed"), (False, "rejected")])
def test_resolver_duplicado_audita_con_el_id_del_admin(
    monkeypatch, auditoria, aceptar: bool, estado: str
) -> None:
    llamadas: list[tuple[str, bool, str]] = []

    def _resolver(lid: str, *, accept: bool, resolved_by: str) -> bool:
        llamadas.append((lid, accept, resolved_by))
        return True

    monkeypatch.setattr(ruta_mod, "resolver_pendiente", _resolver)
    monkeypatch.setattr(ruta_mod, "id_vigente", _sin_alias)

    res = asyncio.run(
        ruta_mod.resolver_duplicado(
            id_externo="ted:1-2026",
            body=ruta_mod.RevisionDecision(aceptar=aceptar),
            response=Response(),
            admin=ADMIN,
        )
    )

    assert res.estado == estado
    assert res.detalle
    assert llamadas == [("ted:1-2026", aceptar, "3")]
    assert auditoria == [
        {
            "event_type": "dedupe.review_resolved",
            "actor": "3",
            "user_id": 3,
            "resource": "licitacion_duplicada:ted:1-2026",
            "detail": f"estado={estado}",
        }
    ]


def test_duplicado_ya_resuelto_es_404_y_no_se_audita(monkeypatch, auditoria) -> None:
    monkeypatch.setattr(ruta_mod, "resolver_pendiente", lambda *_a, **_k: False)
    monkeypatch.setattr(ruta_mod, "id_vigente", _sin_alias)

    with pytest.raises(HTTPException) as exc:
        asyncio.run(
            ruta_mod.resolver_duplicado(
                id_externo="X",
                body=ruta_mod.RevisionDecision(aceptar=True),
                response=Response(),
                admin=ADMIN,
            )
        )

    assert exc.value.status_code == 404
    assert auditoria == []


# ---------------------------------------------------------------------------
# Órganos
# ---------------------------------------------------------------------------


def test_listado_de_organos_trae_el_candidato(monkeypatch) -> None:
    fila = {
        "id": 4,
        "nombre_original": "Ayto. de Villanueva",
        "alias_normalizado": "ayto villanueva",
        "dir3": None,
        "candidato_organo_id": 9,
        "candidato_nombre": "Ayuntamiento de Villanueva",
        "score": 0.9,
        "status": "pending",
        "created_at": "2026-10-01T00:00:00+00:00",
    }
    monkeypatch.setattr(ruta_mod, "listar_pendientes", lambda limit: [fila])
    monkeypatch.setattr(ruta_mod, "revision_pendiente_count", lambda: 1)

    res = asyncio.run(ruta_mod.listar_organos(limit=50, _admin=ADMIN))

    assert res.total == 1
    assert res.items[0].candidato_nombre == "Ayuntamiento de Villanueva"
    assert res.items[0].score == pytest.approx(0.9)


def test_resolver_organo_dice_que_paso_y_lo_audita(monkeypatch, auditoria) -> None:
    monkeypatch.setattr(
        ruta_mod,
        "decidir_revision",
        lambda rid, *, aceptar, resolved_by: DecisionRevision(
            organo_id=12, organo_nuevo=not aceptar, filas_asignadas=40
        ),
    )

    res = asyncio.run(
        ruta_mod.resolver_organo(
            revision_id=4, body=ruta_mod.RevisionDecision(aceptar=False), admin=ADMIN
        )
    )

    assert res.estado == "rejected"
    assert res.organo_id == 12 and res.organo_nuevo is True and res.filas_asignadas == 40
    assert "40" in res.detalle
    assert auditoria == [
        {
            "event_type": "organo.review_resolved",
            "actor": "3",
            "user_id": 3,
            "resource": "organo_review:4",
            "detail": "estado=rejected organo_id=12 filas=40",
        }
    ]


def test_organo_ya_resuelto_es_404(monkeypatch, auditoria) -> None:
    monkeypatch.setattr(ruta_mod, "decidir_revision", lambda *_a, **_k: None)

    with pytest.raises(HTTPException) as exc:
        asyncio.run(
            ruta_mod.resolver_organo(
                revision_id=4, body=ruta_mod.RevisionDecision(aceptar=True), admin=ADMIN
            )
        )

    assert exc.value.status_code == 404
    assert auditoria == []


# ---------------------------------------------------------------------------
# Verdad del dato
# ---------------------------------------------------------------------------


def test_verdad_junta_secciones_y_violaciones(monkeypatch) -> None:
    datos = {"ute": {"pct_filas_afectadas": 9.0}}
    monkeypatch.setattr(ruta_mod, "medir_bd", lambda: datos)
    monkeypatch.setattr(ruta_mod, "evaluar", lambda d: ["UTE: demasiado"] if d is datos else [])
    monkeypatch.setattr(
        ruta_mod,
        "resumir",
        lambda d: [
            SeccionVerdad(
                "ute", "UTE", (MetricaVerdad("Filas afectadas", 9.0, "%", 0.02, True, "9 de 10"),)
            )
        ],
    )

    res = ruta_mod.medir_verdad()

    assert res.violaciones == ["UTE: demasiado"]
    [seccion] = res.secciones
    assert seccion.estado == "violacion"
    assert seccion.metricas[0].supera is True and seccion.metricas[0].detalle == "9 de 10"
    assert res.medido_en
