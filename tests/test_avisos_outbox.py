"""Productores de avisos del outbox (F1.5, F3.4, F5.1, F5.2, F5.3) — sin BD.

Se sustituyen los repositorios y la escritura del evento por dobles: lo que se
prueba aquí es la **política** —a quién va cada aviso, cuántos eventos salen,
hasta dónde avanza el cursor y qué no se repite—. El SQL de los candidatos y el
reparto real están en ``test_avisos_outbox_integracion.py`` (Postgres).
"""

from __future__ import annotations

from typing import Any

import pytest

from services import avisos_outbox
from shared.events import validar_payload


class _Cursores:
    """``ingestion_cursors`` en memoria."""

    def __init__(self, inicial: dict[str, dict[str, Any]] | None = None) -> None:
        self.filas: dict[str, dict[str, Any]] = dict(inicial or {})

    def get(self, fuente: str) -> dict[str, Any] | None:
        return self.filas.get(fuente)

    def set(self, fuente: str, **campos: Any) -> None:
        self.filas[fuente] = {k: v for k, v in campos.items() if v is not None}


@pytest.fixture()
def eventos(monkeypatch: pytest.MonkeyPatch) -> list[dict[str, Any]]:
    """Captura lo que se escribiría en el outbox, validado contra el catálogo."""
    escritos: list[dict[str, Any]] = []

    def _append(
        tipo: str,
        aggregate_id: str | int,
        aggregate_type: str,
        payload: dict[str, Any],
        *,
        organization_id: int | None = None,
        **_: Any,
    ) -> int:
        validar_payload(tipo, payload)
        escritos.append(
            {
                "tipo": tipo,
                "aggregate_id": aggregate_id,
                "aggregate_type": aggregate_type,
                "payload": payload,
                "organization_id": organization_id,
            }
        )
        return len(escritos)

    monkeypatch.setattr(avisos_outbox, "append_domain_event", _append)
    return escritos


def _cursores(monkeypatch: pytest.MonkeyPatch, inicial: dict[str, dict[str, Any]]) -> _Cursores:
    cursores = _Cursores(inicial)
    monkeypatch.setattr(avisos_outbox, "get_cursor", cursores.get)
    monkeypatch.setattr(avisos_outbox, "set_cursor", cursores.set)
    return cursores


class _AvisosRepo:
    def __init__(self, documentos: list[dict[str, Any]], recursos: list[dict[str, Any]]) -> None:
        self.documentos = documentos
        self.recursos = recursos
        self.max_doc = max((int(d["documento_id"]) for d in documentos), default=0)
        self.max_rec = max((int(r["resolucion_id"]) for r in recursos), default=0)

    def max_documento_id(self) -> int:
        return self.max_doc

    def documentos_nuevos_seguidos(
        self, *, desde_id: int, hasta_id: int, limit: int
    ) -> list[dict[str, Any]]:
        filas = [d for d in self.documentos if desde_id < int(d["documento_id"]) <= hasta_id]
        return filas[:limit]

    def max_resolucion_id(self) -> int:
        return self.max_rec

    def recursos_seguidos(
        self, *, desde_id: int, hasta_id: int, limit: int
    ) -> list[dict[str, Any]]:
        filas = [r for r in self.recursos if desde_id < int(r["resolucion_id"]) <= hasta_id]
        return filas[:limit]


_SEGUIDORES = {
    "EXP-1": [
        {"user_key": "k-ana", "organization_id": 1, "user_id": 10},
        {"user_key": None, "organization_id": 1, "user_id": 11},
        {"user_key": "k-luis", "organization_id": 2, "user_id": 20},
        {"user_key": "k-sin-org", "organization_id": None, "user_id": 30},
    ],
    "EXP-2": [],
}


@pytest.fixture()
def seguidores(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        avisos_outbox, "seguidores_de_licitacion", lambda id_externo: _SEGUIDORES[id_externo]
    )


# ── F5.1: documentos nuevos ──────────────────────────────────────────────────


def test_la_primera_pasada_fija_el_cursor_y_no_mira_atras(
    monkeypatch: pytest.MonkeyPatch, eventos: list[dict[str, Any]], seguidores: None
) -> None:
    """Encender los avisos no puede convertir el histórico entero en avisos."""
    repo = _AvisosRepo([{"documento_id": 5, "licitacion_id": "EXP-1", "tipo": "technical"}], [])
    monkeypatch.setattr(avisos_outbox, "_avisos", repo)
    cursores = _cursores(monkeypatch, {})

    assert avisos_outbox.emitir_documentos_nuevos() == 0
    assert eventos == []
    assert cursores.filas[avisos_outbox.CURSOR_DOCUMENTOS]["last_entry_id"] == "5"


def test_un_documento_nuevo_avisa_una_vez_por_organizacion_seguidora(
    monkeypatch: pytest.MonkeyPatch, eventos: list[dict[str, Any]], seguidores: None
) -> None:
    repo = _AvisosRepo(
        [
            {"documento_id": 6, "licitacion_id": "EXP-1", "tipo": "technical", "titulo": "SAP"},
            {"documento_id": 7, "licitacion_id": "EXP-2", "tipo": "legal"},
        ],
        [],
    )
    monkeypatch.setattr(avisos_outbox, "_avisos", repo)
    cursores = _cursores(monkeypatch, {avisos_outbox.CURSOR_DOCUMENTOS: {"last_entry_id": "5"}})

    assert avisos_outbox.emitir_documentos_nuevos() == 2

    assert {e["organization_id"] for e in eventos} == {1, 2}
    de_org1 = next(e for e in eventos if e["organization_id"] == 1)
    assert de_org1["tipo"] == "licitacion.documento_nuevo"
    assert de_org1["payload"]["documento_id"] == 6
    assert de_org1["payload"]["subtipo"] == "documento_nuevo"
    assert de_org1["payload"]["aviso_titulo"] == "Documento nuevo: technical"
    # Cada organización sólo ve a sus seguidores, y nadie sin organización.
    assert {s["user_id"] for s in de_org1["payload"]["seguidores"]} == {10, 11}
    # El expediente sin seguidores no emite, pero el cursor sí lo deja atrás.
    assert cursores.filas[avisos_outbox.CURSOR_DOCUMENTOS]["last_entry_id"] == "7"


def test_una_pasada_sin_documentos_nuevos_no_toca_nada(
    monkeypatch: pytest.MonkeyPatch, eventos: list[dict[str, Any]], seguidores: None
) -> None:
    repo = _AvisosRepo([{"documento_id": 5, "licitacion_id": "EXP-1", "tipo": "legal"}], [])
    monkeypatch.setattr(avisos_outbox, "_avisos", repo)
    _cursores(monkeypatch, {avisos_outbox.CURSOR_DOCUMENTOS: {"last_entry_id": "5"}})

    assert avisos_outbox.emitir_documentos_nuevos() == 0
    assert eventos == []


def test_con_el_lote_lleno_el_cursor_avanza_solo_hasta_lo_leido(
    monkeypatch: pytest.MonkeyPatch, eventos: list[dict[str, Any]], seguidores: None
) -> None:
    monkeypatch.setattr(avisos_outbox, "LOTE_DOCUMENTOS", 2)
    repo = _AvisosRepo(
        [
            {"documento_id": i, "licitacion_id": "EXP-2", "tipo": "legal"}
            for i in range(1, 6)  # 1..5
        ],
        [],
    )
    monkeypatch.setattr(avisos_outbox, "_avisos", repo)
    cursores = _cursores(monkeypatch, {avisos_outbox.CURSOR_DOCUMENTOS: {"last_entry_id": "0"}})

    avisos_outbox.emitir_documentos_nuevos()

    assert cursores.filas[avisos_outbox.CURSOR_DOCUMENTOS]["last_entry_id"] == "2"


# ── F5.2: recursos ───────────────────────────────────────────────────────────


@pytest.mark.parametrize(
    ("sentido", "titular"),
    [
        ("estimado", "Recurso estimado"),
        ("desestimado", "Recurso desestimado"),
        ("inadmitido", "Recurso inadmitido"),
        (None, "Resolución de recurso publicada"),
    ],
)
def test_el_recurso_avisa_con_su_sentido(
    monkeypatch: pytest.MonkeyPatch,
    eventos: list[dict[str, Any]],
    seguidores: None,
    sentido: str | None,
    titular: str,
) -> None:
    repo = _AvisosRepo(
        [],
        [{"resolucion_id": 3, "licitacion_id": "EXP-1", "sentido": sentido, "titulo": "SAP"}],
    )
    monkeypatch.setattr(avisos_outbox, "_avisos", repo)
    _cursores(monkeypatch, {avisos_outbox.CURSOR_RECURSOS: {"last_entry_id": "2"}})

    assert avisos_outbox.emitir_recursos() == 2  # dos organizaciones siguen EXP-1

    payload = eventos[0]["payload"]
    assert eventos[0]["tipo"] == "licitacion.recurso"
    assert payload["sentido"] == sentido
    assert payload["subtipo"] == "recurso"
    assert payload["aviso_titulo"] == titular


# ── F1.5: cuentas ────────────────────────────────────────────────────────────


class _CuentasRepo:
    def __init__(
        self,
        publicaciones: list[dict[str, Any]] | None = None,
        vencimientos: list[dict[str, Any]] | None = None,
    ) -> None:
        self.publicaciones = publicaciones or []
        self.vencimientos = vencimientos or []
        self.consultas_miembros: list[int] = []
        self.franja: tuple[int, int] | None = None

    def publicaciones_nuevas(
        self, *, desde_iso: str, hasta_iso: str, limit: int
    ) -> list[dict[str, Any]]:
        return self.publicaciones[:limit]

    def vencimientos_entrando(
        self, *, dias_desde: int, dias_hasta: int, limit: int = 500
    ) -> list[dict[str, Any]]:
        self.franja = (dias_desde, dias_hasta)
        return self.vencimientos

    def miembros_activos(self, organization_id: int) -> list[int]:
        self.consultas_miembros.append(organization_id)
        return {1: [10, 11], 2: [20]}.get(organization_id, [])


def _publicacion(org: int, id_externo: str) -> dict[str, Any]:
    return {
        "organization_id": org,
        "cuenta_id": 100 + org,
        "organo_nombre": "Ayuntamiento de Alcalá",
        "id_externo": id_externo,
        "titulo": f"Expediente {id_externo}",
        "primera_extraccion": "2026-09-19T08:00:00+00:00",
    }


def test_cuentas_primera_pasada_fija_el_cursor(
    monkeypatch: pytest.MonkeyPatch, eventos: list[dict[str, Any]]
) -> None:
    monkeypatch.setattr(avisos_outbox, "_cuentas", _CuentasRepo([_publicacion(1, "A")]))
    cursores = _cursores(monkeypatch, {})

    assert avisos_outbox.emitir_avisos_de_cuentas() == 0
    assert eventos == []
    assert cursores.filas[avisos_outbox.CURSOR_CUENTAS]["last_seen_updated"]


def test_publicacion_nueva_de_una_cuenta_avisa_a_los_miembros_de_cada_organizacion(
    monkeypatch: pytest.MonkeyPatch, eventos: list[dict[str, Any]]
) -> None:
    repo = _CuentasRepo([_publicacion(1, "A"), _publicacion(1, "B"), _publicacion(2, "A")])
    monkeypatch.setattr(avisos_outbox, "_cuentas", repo)
    _cursores(
        monkeypatch,
        {avisos_outbox.CURSOR_CUENTAS: {"last_seen_updated": "2026-09-18T00:00:00+00:00"}},
    )

    assert avisos_outbox.emitir_avisos_de_cuentas() == 3

    assert [e["tipo"] for e in eventos] == ["cuenta.publicacion_nueva"] * 3
    primero = eventos[0]["payload"]
    assert primero["organo"] == "Ayuntamiento de Alcalá"
    assert primero["aviso_titulo"] == "Publicación nueva de Ayuntamiento de Alcalá"
    assert [s["user_id"] for s in primero["seguidores"]] == [10, 11]
    assert [s["user_id"] for s in eventos[2]["payload"]["seguidores"]] == [20]
    # Una consulta de miembros por organización, no una por publicación.
    assert repo.consultas_miembros == [1, 2]


def test_vencimiento_mira_la_franja_del_borde_de_los_seis_meses(
    monkeypatch: pytest.MonkeyPatch, eventos: list[dict[str, Any]]
) -> None:
    repo = _CuentasRepo(
        vencimientos=[
            {
                "organization_id": 1,
                "cuenta_id": 101,
                "organo_nombre": "Diputación",
                "id_externo": "C-1",
                "titulo": "Mantenimiento SAP",
                "fecha_fin": "2027-03-20",
            }
        ]
    )
    monkeypatch.setattr(avisos_outbox, "_cuentas", repo)
    monkeypatch.setattr(avisos_outbox, "get_events", lambda *_a, **_k: [])

    assert avisos_outbox.emitir_vencimientos_de_cuentas() == 1

    assert repo.franja == (176, 183)
    evento = eventos[0]
    assert evento["tipo"] == "cuenta.vencimiento_proximo"
    assert evento["aggregate_id"] == "101:C-1"
    assert evento["payload"]["fecha_fin"] == "2027-03-20"
    assert evento["payload"]["aviso_titulo"] == "Vence en seis meses un contrato de Diputación"


def test_vencimiento_ya_avisado_con_la_misma_fecha_no_se_repite(
    monkeypatch: pytest.MonkeyPatch, eventos: list[dict[str, Any]]
) -> None:
    """Idempotente por (cuenta, expediente, fecha_fin): la franja tiene siete
    días de anchura y el cierre corre seis veces al día."""
    fila = {
        "organization_id": 1,
        "cuenta_id": 101,
        "organo_nombre": "Diputación",
        "id_externo": "C-1",
        "fecha_fin": "2027-03-20",
    }
    monkeypatch.setattr(avisos_outbox, "_cuentas", _CuentasRepo(vencimientos=[fila]))
    monkeypatch.setattr(
        avisos_outbox,
        "get_events",
        lambda *_a, **_k: [{"payload": {"fecha_fin": "2027-03-20"}}],
    )

    assert avisos_outbox.emitir_vencimientos_de_cuentas() == 0
    assert eventos == []


def test_una_prorroga_vuelve_a_avisar(
    monkeypatch: pytest.MonkeyPatch, eventos: list[dict[str, Any]]
) -> None:
    fila = {
        "organization_id": 1,
        "cuenta_id": 101,
        "organo_nombre": "Diputación",
        "id_externo": "C-1",
        "fecha_fin": "2027-09-20",
    }
    monkeypatch.setattr(avisos_outbox, "_cuentas", _CuentasRepo(vencimientos=[fila]))
    monkeypatch.setattr(
        avisos_outbox,
        "get_events",
        lambda *_a, **_k: [{"payload": {"fecha_fin": "2027-03-20"}}],
    )

    assert avisos_outbox.emitir_vencimientos_de_cuentas() == 1


# ── Pasada ───────────────────────────────────────────────────────────────────


def test_un_productor_roto_no_para_a_los_demas(monkeypatch: pytest.MonkeyPatch) -> None:
    def _roto() -> int:
        raise RuntimeError("tabla sin migrar")

    monkeypatch.setattr(avisos_outbox, "emitir_documentos_nuevos", _roto)
    monkeypatch.setattr(avisos_outbox, "emitir_recursos", lambda: 2)
    monkeypatch.setattr(avisos_outbox, "emitir_avisos_de_cuentas", lambda: 1)
    monkeypatch.setattr(avisos_outbox, "emitir_vencimientos_de_cuentas", lambda: 0)

    resumen = avisos_outbox.emitir_avisos()

    assert (resumen.documentos, resumen.recursos, resumen.publicaciones) == (0, 2, 1)
    assert resumen.total == 3


def test_el_modulo_no_nombra_la_identidad_heredada() -> None:
    """Ratchet de ``user_key`` (D18): un fichero nuevo no puede usarla. Los
    destinatarios viajan con ``user_id`` y los traduce el despachador."""
    from pathlib import Path

    texto = Path(avisos_outbox.__file__).read_text(encoding="utf-8")
    assert "user" + "_key" not in texto
