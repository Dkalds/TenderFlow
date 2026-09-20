"""F5.3 y F3.4 sin BD: avisos con nombre en el payload, en el digest y en el
evento de competidor.

- ``licitacion.cambiada`` sale con ``subtipo`` y titular (``clasificar_cambio``).
- El digest agrupa las filas de eventos por subtipo, con el orden «terminal
  primero», y cuenta los avisos aparte de las licitaciones nuevas.
- La alerta de competidor escribe un evento por (organización, empresa,
  expediente) sólo cuando la adjudicación cae en el terreno de la organización.
"""

from __future__ import annotations

import json
from typing import Any

import pytest

from services.email_digest import (
    BloqueDigest,
    asunto_digest,
    bloques_de_avisos,
    clave_de_aviso,
    render_digest,
)
from shared.events import CATALOGO, FAMILIAS, especificacion, suscripciones_validas

# ── Catálogo ─────────────────────────────────────────────────────────────────


@pytest.mark.parametrize(
    "tipo",
    [
        "licitacion.documento_nuevo",
        "licitacion.recurso",
        "competidor.adjudicacion_en_mi_segmento",
        "cuenta.publicacion_nueva",
        "cuenta.vencimiento_proximo",
    ],
)
def test_los_eventos_nuevos_estan_en_el_catalogo_y_se_pueden_suscribir(tipo: str) -> None:
    assert tipo in CATALOGO
    assert tipo.split(".", 1)[0] in FAMILIAS
    validas = set(suscripciones_validas())
    assert tipo in validas
    assert f"{tipo.split('.', 1)[0]}.*" in validas
    spec = especificacion(tipo)
    assert "in_app" in spec.canales and "webhook" in spec.canales


def test_los_avisos_de_lo_seguido_van_al_digest_con_preferencia() -> None:
    for tipo in ("licitacion.cambiada", "licitacion.documento_nuevo", "licitacion.recurso"):
        spec = especificacion(tipo)
        assert "digest" in spec.canales
        assert spec.preferencia_email


def test_competidor_y_cuentas_no_mandan_correo_por_el_despachador() -> None:
    """El correo de competidores ya sale agrupado por su camino; las cuentas
    avisan a toda la organización, y un correo por publicación sería spam."""
    for tipo in (
        "competidor.adjudicacion_en_mi_segmento",
        "cuenta.publicacion_nueva",
        "cuenta.vencimiento_proximo",
    ):
        assert "digest" not in especificacion(tipo).canales


# ── F5.3: el productor de cambios pone nombre ────────────────────────────────


def test_licitacion_cambiada_sale_con_subtipo_y_titular(monkeypatch: pytest.MonkeyPatch) -> None:
    from services import contract_events

    escritos: list[dict[str, Any]] = []
    monkeypatch.setattr(
        contract_events,
        "seguidores_de_licitacion",
        lambda _id: [{"user_key": "k", "organization_id": 1, "user_id": 5}],
    )
    monkeypatch.setattr(
        contract_events,
        "append_domain_event",
        lambda tipo, _agg, _t, payload, **_k: escritos.append(payload) or 1,
    )

    emitido = contract_events._emitir_cambio_seguido(
        None,
        id_externo="EXP-9",
        history_id=77,
        antes={"fecha_limite": "2026-10-01", "estado": "PUB"},
        despues={"fecha_limite": "2026-10-12", "estado": "PUB", "titulo": "SAP"},
        changed=["fecha_limite"],
    )

    assert emitido is True
    payload = escritos[0]
    assert payload["subtipo"] == "plazo_ampliado"
    assert payload["aviso_titulo"] == "Plazo ampliado al 12/10/2026"
    assert payload["aviso_detalle"] == "Antes cerraba el 01/10/2026."
    # Lo que ya llevaba el evento sigue igual: el webhook no cambia de forma.
    assert payload["changed_fields"] == ["fecha_limite"]
    assert payload["history_id"] == 77


def test_una_anulacion_gana_el_titular_aunque_cambie_el_importe(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from services import contract_events

    escritos: list[dict[str, Any]] = []
    monkeypatch.setattr(
        contract_events,
        "seguidores_de_licitacion",
        lambda _id: [{"user_key": "k", "organization_id": 1, "user_id": 5}],
    )
    monkeypatch.setattr(
        contract_events,
        "append_domain_event",
        lambda tipo, _agg, _t, payload, **_k: escritos.append(payload) or 1,
    )

    contract_events._emitir_cambio_seguido(
        None,
        id_externo="EXP-9",
        history_id=78,
        antes={"estado": "PUB", "importe": 1000.0},
        despues={"estado": "ANUL", "importe": 1200.0},
        changed=["estado", "importe"],
    )

    assert escritos[0]["subtipo"] == "anulado"


# ── F5.3: el digest agrupa por subtipo ───────────────────────────────────────


def _fila(evento_tipo: str, payload: dict[str, Any], licitacion_id: str) -> dict[str, Any]:
    return {
        "licitacion_id": licitacion_id,
        "titulo": f"Expediente {licitacion_id}",
        "evento_tipo": evento_tipo,
        "evento_payload": json.dumps(payload),
    }


def test_clave_de_aviso_usa_el_subtipo_y_si_no_el_catalogo() -> None:
    assert clave_de_aviso("licitacion.cambiada", {"subtipo": "plazo_ampliado"}) == (
        "plazo_ampliado",
        "Plazo ampliado",
    )
    assert clave_de_aviso("pursuit.commented", {}) == (
        "pursuit.commented",
        "Comentario en una oportunidad",
    )
    # Un subtipo desconocido no se pinta en crudo: cae al título del evento.
    assert clave_de_aviso("licitacion.cambiada", {"subtipo": "inventado"})[1] == (
        "Cambio en un expediente que sigues"
    )


def test_el_digest_agrupa_por_subtipo_con_lo_terminal_primero() -> None:
    filas = [
        _fila(
            "licitacion.cambiada",
            {"subtipo": "plazo_ampliado", "aviso_titulo": "Plazo ampliado al 12/10/2026"},
            "A",
        ),
        _fila("licitacion.documento_nuevo", {"subtipo": "documento_nuevo"}, "B"),
        _fila("licitacion.cambiada", {"subtipo": "anulado", "aviso_titulo": "Anulado"}, "C"),
        _fila(
            "licitacion.cambiada",
            {"subtipo": "plazo_ampliado", "aviso_titulo": "Plazo ampliado al 20/10/2026"},
            "D",
        ),
        _fila("pursuit.commented", {}, "E"),
    ]

    bloques = bloques_de_avisos(filas)

    assert [b.etiqueta for b in bloques] == [
        "Expediente anulado",
        "Plazo ampliado",
        "Documento nuevo",
        "Comentario en una oportunidad",
    ]
    assert all(b.es_aviso for b in bloques)
    plazos = bloques[1].licitaciones
    assert [lic["id_externo"] for lic in plazos] == ["A", "D"]
    assert plazos[0]["aviso"] == "Plazo ampliado al 12/10/2026"


def test_el_digest_con_avisos_no_los_cuenta_como_licitaciones_nuevas() -> None:
    bloques = [
        BloqueDigest(etiqueta="Regla SAP", licitaciones=[{"id_externo": "N1", "titulo": "X"}]),
        *bloques_de_avisos(
            [
                _fila(
                    "licitacion.cambiada",
                    {
                        "subtipo": "plazo_ampliado",
                        "aviso_titulo": "Plazo ampliado al 12/10/2026",
                        "aviso_detalle": "Antes cerraba el 01/10/2026.",
                    },
                    "A",
                )
            ]
        ),
    ]

    texto, html = render_digest(bloques=bloques, frecuencia="daily", base_url=None, baja_url=None)

    primera = texto.splitlines()[0]
    assert primera.startswith("1 licitación(es) nueva(s) de hoy")
    assert "1 novedad en los expedientes que sigues" in primera
    assert "Plazo ampliado al 12/10/2026 — Antes cerraba el 01/10/2026." in texto
    assert "== Plazo ampliado (1) ==" in texto
    assert "Plazo ampliado al 12/10/2026" in html


def test_un_digest_solo_de_avisos_no_habla_de_licitaciones_nuevas() -> None:
    bloques = bloques_de_avisos([_fila("licitacion.recurso", {"subtipo": "recurso"}, "A")])
    texto, _ = render_digest(bloques=bloques, frecuencia="daily", base_url=None, baja_url=None)
    assert texto.splitlines()[0] == "1 novedad en los expedientes que sigues."


@pytest.mark.parametrize(
    ("total", "avisos", "esperado"),
    [
        (3, 0, "TenderFlow · 3 licitaciones nuevas de hoy"),
        (0, 2, "TenderFlow · 2 novedades en lo que sigues"),
        (1, 1, "TenderFlow · 1 licitación nueva de hoy y 1 novedad"),
    ],
)
def test_asunto_del_digest_separa_novedades(total: int, avisos: int, esperado: str) -> None:
    assert asunto_digest("daily", total, avisos=avisos) == esperado


# ── F3.4: evento de competidor en mi segmento ────────────────────────────────


def test_competidor_en_mi_segmento_un_evento_por_organizacion_con_sus_vigilantes(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from scheduler import competitor_alerts

    escritos: list[dict[str, Any]] = []

    def _append(tipo: str, agg: str, _t: str, payload: dict[str, Any], **k: Any) -> int:
        from shared.events import validar_payload

        validar_payload(tipo, payload)
        escritos.append({"tipo": tipo, "payload": payload, **k})
        return 1

    monkeypatch.setattr("db.events.append_domain_event", _append)

    adj_en_segmento = {
        "licitacion_id": "EXP-1",
        "titulo": "SAP S/4",
        "organo_contratacion": "Ayuntamiento de Alcalá",
        "_motivo_segmento": {"motivo": "cuenta", "referencia": "Ayuntamiento de Alcalá"},
    }
    adj_fuera = {"licitacion_id": "EXP-2", "titulo": "Otra cosa"}
    acumulado: dict[tuple[int, int, str], dict[str, Any]] = {}
    base = {"empresa_id": 7, "nombre_canonico": "Rival SA", "organization_id": 3}
    competitor_alerts._acumular_en_segmento(
        acumulado, {**base, "user_id": 10}, [adj_en_segmento, adj_fuera]
    )
    competitor_alerts._acumular_en_segmento(acumulado, {**base, "user_id": 11}, [adj_en_segmento])
    # Entrada legada sin user_id: no añade destinatario pero no rompe.
    competitor_alerts._acumular_en_segmento(acumulado, {**base, "user_id": None}, [adj_en_segmento])

    assert competitor_alerts._emitir_en_segmento(acumulado) == 1

    evento = escritos[0]
    assert evento["tipo"] == "competidor.adjudicacion_en_mi_segmento"
    assert evento["organization_id"] == 3
    payload = evento["payload"]
    assert payload["empresa_id"] == 7
    assert payload["motivo"] == "cuenta"
    assert payload["aviso_titulo"] == "Rival SA gana en tu terreno"
    assert "que sigues" in payload["aviso_detalle"]
    assert [s["user_id"] for s in payload["seguidores"]] == [10, 11]


def test_competidor_sin_organizacion_no_emite(monkeypatch: pytest.MonkeyPatch) -> None:
    from scheduler import competitor_alerts

    acumulado: dict[tuple[int, int, str], dict[str, Any]] = {}
    competitor_alerts._acumular_en_segmento(
        acumulado,
        {"empresa_id": 7, "organization_id": None, "user_id": 10},
        [{"licitacion_id": "X", "_motivo_segmento": {"motivo": "cuenta"}}],
    )
    assert acumulado == {}


def test_un_fallo_al_escribir_un_evento_no_para_los_demas(monkeypatch: pytest.MonkeyPatch) -> None:
    from scheduler import competitor_alerts

    llamadas: list[str] = []

    def _append(_tipo: str, agg: str, *_a: Any, **_k: Any) -> int:
        llamadas.append(agg)
        if agg == "EXP-1":
            raise RuntimeError("bd caída")
        return 1

    monkeypatch.setattr("db.events.append_domain_event", _append)
    motivo = {"motivo": "oportunidad_abierta", "referencia": "SAP"}
    acumulado = {
        (1, 7, "EXP-1"): {
            "empresa": "R",
            "adjudicacion": {"licitacion_id": "EXP-1"},
            "motivo": motivo,
            "seguidores": [],
        },
        (1, 7, "EXP-2"): {
            "empresa": "R",
            "adjudicacion": {"licitacion_id": "EXP-2"},
            "motivo": motivo,
            "seguidores": [],
        },
    }

    assert competitor_alerts._emitir_en_segmento(acumulado) == 1
    assert llamadas == ["EXP-1", "EXP-2"]
