"""El despachador del outbox, cableado al cierre (S4.1) — sin base de datos.

Hasta el 2026-09-19 ``event_dispatch.run()`` estaba escrito y probado pero no
lo invocaba ningún plano, así que ningún evento se entregaba. Estos tests fijan
las tres piezas del cableado:

- el paso ``event_dispatch`` del cierre, con su interruptor
  ``EVENT_DISPATCH_ENABLED``;
- la **antigüedad máxima** (``EVENT_DISPATCH_MAX_AGE_HOURS``): la cola que se
  acumuló mientras nadie la repartía no se entrega de golpe;
- lo que el despachador aprendió para los avisos nuevos (F1.5, F3.4, F5.1–F5.3):
  destinatarios sólo con ``user_id``, titulares con nombre y la codificación del
  ``entry_id`` del digest.

Lo que exige Postgres está en ``test_avisos_outbox_integracion.py``.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Any

import pytest

from scheduler.jobs import event_dispatch
from shared.events import especificacion

# ── Interruptor y antigüedad máxima (config) ─────────────────────────────────


def test_el_despachador_esta_encendido_por_defecto(monkeypatch: pytest.MonkeyPatch) -> None:
    from config.settings import event_dispatch_enabled

    monkeypatch.delenv("EVENT_DISPATCH_ENABLED", raising=False)
    assert event_dispatch_enabled() is True


@pytest.mark.parametrize("valor", ["0", "false", "no", "off", "OFF"])
def test_event_dispatch_enabled_se_apaga(monkeypatch: pytest.MonkeyPatch, valor: str) -> None:
    from config.settings import event_dispatch_enabled

    monkeypatch.setenv("EVENT_DISPATCH_ENABLED", valor)
    assert event_dispatch_enabled() is False


@pytest.mark.parametrize(
    ("valor", "esperado"),
    [(None, 48), ("72", 72), ("0", 1), ("no-es-un-numero", 48)],
)
def test_antiguedad_maxima_por_defecto_y_suelo(
    monkeypatch: pytest.MonkeyPatch, valor: str | None, esperado: int
) -> None:
    """Un valor ilegible no tumba el cierre: cae al defecto. Y nunca cero —con
    cero caducaría todo, incluido lo que se acaba de escribir."""
    from config.settings import event_dispatch_max_age_hours

    if valor is None:
        monkeypatch.delenv("EVENT_DISPATCH_MAX_AGE_HOURS", raising=False)
    else:
        monkeypatch.setenv("EVENT_DISPATCH_MAX_AGE_HOURS", valor)
    assert event_dispatch_max_age_hours() == esperado


# ── Caducidad ────────────────────────────────────────────────────────────────


def test_caducar_viejos_pasa_la_marca_de_corte_y_registra_la_metrica(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    llamadas: list[str] = []
    registrados: list[tuple[str, float | None, str | None]] = []

    def _caducar(creados_antes_de: str) -> dict[str, int]:
        llamadas.append(creados_antes_de)
        return {"pursuit.assigned": 3, "licitacion.cambiada": 2}

    def _record(tipo: str, value: float | None = None, detail: str | None = None) -> None:
        registrados.append((tipo, value, detail))

    monkeypatch.setattr("db.events.caducar_pendientes", _caducar)
    monkeypatch.setattr("observability.ops_events.record_event", _record)

    antes = datetime.now(UTC)
    total = event_dispatch.caducar_viejos(48)

    assert total == 5
    corte = datetime.fromisoformat(llamadas[0])
    # El corte es «ahora menos 48 h», no la marca de otra zona horaria.
    assert abs((antes - timedelta(hours=48) - corte).total_seconds()) < 5
    assert registrados[0][0] == "domain_events_caducados"
    assert registrados[0][1] == 5.0
    assert "pursuit.assigned" in (registrados[0][2] or "")


def test_sin_nada_que_caducar_no_se_registra_metrica(monkeypatch: pytest.MonkeyPatch) -> None:
    registrados: list[str] = []
    monkeypatch.setattr("db.events.caducar_pendientes", lambda _corte: {})
    monkeypatch.setattr(
        "observability.ops_events.record_event", lambda tipo, **_: registrados.append(tipo)
    )

    assert event_dispatch.caducar_viejos(48) == 0
    assert registrados == []


def test_dispatch_pending_caduca_antes_de_repartir(monkeypatch: pytest.MonkeyPatch) -> None:
    """El lote de la pasada no se gasta en eventos que no se van a entregar."""
    orden: list[str] = []

    def _caducar(_horas: int | None = None) -> int:
        orden.append("caducar")
        return 7

    def _pendientes(_limit: int) -> list[dict[str, Any]]:
        orden.append("pendientes")
        return []

    monkeypatch.setattr(event_dispatch, "caducar_viejos", _caducar)
    monkeypatch.setattr(event_dispatch, "pending_events", _pendientes)

    resultado = event_dispatch.dispatch_pending()

    assert orden == ["caducar", "pendientes"]
    assert resultado.caducados == 7
    assert resultado.procesados == 0


def test_run_no_hace_nada_con_el_interruptor_apagado(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("EVENT_DISPATCH_ENABLED", "0")

    def _no(*_a: object, **_k: object) -> object:
        raise AssertionError("con el despachador apagado no se reparte ni se emite nada")

    monkeypatch.setattr(event_dispatch, "dispatch_pending", _no)
    monkeypatch.setattr("services.avisos_outbox.emitir_avisos", _no)

    assert event_dispatch.run() == 0


def test_run_emite_los_avisos_antes_de_repartir(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("EVENT_DISPATCH_ENABLED", raising=False)
    orden: list[str] = []
    monkeypatch.setattr(
        "services.pursuit_tasks.emitir_tareas_que_vencen", lambda: orden.append("tareas") or 0
    )
    monkeypatch.setattr("services.avisos_outbox.emitir_avisos", lambda: orden.append("avisos"))

    def _dispatch() -> event_dispatch.ResultadoDespacho:
        orden.append("reparto")
        return event_dispatch.ResultadoDespacho(procesados=4)

    monkeypatch.setattr(event_dispatch, "dispatch_pending", _dispatch)

    assert event_dispatch.run() == 4
    assert orden == ["tareas", "avisos", "reparto"]


# ── Paso del cierre ──────────────────────────────────────────────────────────


def test_event_dispatch_es_un_paso_canonico_entre_notify_y_digests() -> None:
    """Después de quien escribe eventos de reglas y competidores, y antes del
    digest, que así incluye en la misma pasada lo que el despachador encoló."""
    from scheduler.pipeline_runs import CANONICAL_STEPS, STEP_DEPS, step_tier

    i = CANONICAL_STEPS.index("event_dispatch")
    assert CANONICAL_STEPS[i - 1] == "watchlist_notify"
    assert CANONICAL_STEPS[i + 1] == "digests"
    assert step_tier("event_dispatch") == "advisory"
    assert "event_dispatch" not in STEP_DEPS


def test_el_paso_se_salta_con_el_interruptor_apagado(monkeypatch: pytest.MonkeyPatch) -> None:
    from scheduler.pipeline_runs import STEP_SKIPPED, ejecutar_paso

    monkeypatch.setenv("EVENT_DISPATCH_ENABLED", "0")
    monkeypatch.setattr(
        event_dispatch, "run", lambda: (_ for _ in ()).throw(AssertionError("no debe correr"))
    )
    assert ejecutar_paso("event_dispatch") == STEP_SKIPPED


def test_el_paso_invoca_run_del_despachador(monkeypatch: pytest.MonkeyPatch) -> None:
    from scheduler.pipeline_runs import STEP_OK, ejecutar_paso

    monkeypatch.delenv("EVENT_DISPATCH_ENABLED", raising=False)
    llamado: list[bool] = []
    monkeypatch.setattr(event_dispatch, "run", lambda: llamado.append(True) or 0)

    assert ejecutar_paso("event_dispatch") == STEP_OK
    assert llamado == [True]


# ── entry_id del digest ──────────────────────────────────────────────────────


@pytest.mark.parametrize(("event_id", "posicion"), [(1, 0), (1, 1), (4242, 99), (21_000_000, 3)])
def test_entry_id_de_digest_es_negativo_y_reversible(event_id: int, posicion: int) -> None:
    entry = event_dispatch.entry_id_de_digest(event_id, posicion)
    assert entry is not None and entry < 0
    assert event_dispatch.event_id_de_entry(entry) == event_id


def test_dos_seguidores_del_mismo_evento_no_chocan_en_el_unico_del_digest() -> None:
    """El único de ``pending_digests`` es (entry_id, licitacion_id): con un
    entry por evento, el segundo seguidor se perdía en silencio."""
    assert event_dispatch.entry_id_de_digest(10, 0) != event_dispatch.entry_id_de_digest(10, 1)


def test_sin_hueco_no_se_encola_con_un_id_ambiguo() -> None:
    assert event_dispatch.entry_id_de_digest(5, 100) is None
    assert event_dispatch.entry_id_de_digest(30_000_000, 0) is None


def test_las_filas_de_reglas_no_se_confunden_con_eventos() -> None:
    assert event_dispatch.event_id_de_entry(17) is None


# ── Destinatarios y texto de los avisos nuevos ───────────────────────────────


def test_seguidores_solo_con_user_id_se_resuelven_en_el_despachador(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    resueltos: list[tuple[int, int]] = []

    def _resolver(user_id: int, organization_id: int) -> event_dispatch.Destinatario:
        resueltos.append((user_id, organization_id))
        return event_dispatch.Destinatario(
            user_key=f"clave-{user_id}", organization_id=organization_id, user_id=user_id
        )

    monkeypatch.setattr(event_dispatch, "_usuario_a_destinatario", _resolver)
    evento = {
        "id": 1,
        "event_type": "cuenta.publicacion_nueva",
        "organization_id": 9,
        "payload": {
            "seguidores": [
                {"user_id": 3, "organization_id": 9},
                {"user_id": 3, "organization_id": 9},
                {"user_id": 4},
                {"organization_id": 9},
            ]
        },
    }

    destinatarios = event_dispatch._destinatarios(evento)

    assert [(d.user_id, d.organization_id) for d in destinatarios] == [(3, 9), (4, 9)]
    assert (4, 9) in resueltos


def test_el_titular_usa_el_aviso_con_nombre() -> None:
    evento = {
        "payload": {
            "titulo": "Soporte SAP",
            "aviso_titulo": "Plazo ampliado al 12/10/2026",
            "aviso_detalle": "Antes cerraba el 01/10/2026.",
            "valores": {"fecha_limite": {"antes": "2026-10-01", "despues": "2026-10-12"}},
        }
    }
    titulo, cuerpo = event_dispatch._titulo_y_cuerpo(evento, especificacion("licitacion.cambiada"))
    assert titulo == "Plazo ampliado al 12/10/2026: Soporte SAP"
    assert "Antes cerraba el 01/10/2026." in cuerpo
    # Los valores siguen en el cuerpo: el aviso con nombre no esconde el dato.
    assert "2026-10-01" in cuerpo and "2026-10-12" in cuerpo


def test_sin_aviso_el_titular_es_el_del_catalogo() -> None:
    """Los eventos anteriores a F5.3 que queden en la cola salen como siempre."""
    evento = {"payload": {"titulo": "Soporte SAP", "detalle": "algo"}}
    titulo, cuerpo = event_dispatch._titulo_y_cuerpo(evento, especificacion("licitacion.cambiada"))
    assert titulo == "Cambio en un expediente que sigues: Soporte SAP"
    assert cuerpo == "algo"


@pytest.mark.parametrize(
    ("tipo", "payload", "esperado"),
    [
        ("licitacion.documento_nuevo", {"documento_id": 55}, "licitacion_documento_nuevo:55"),
        ("licitacion.recurso", {"resolucion_id": 8}, "licitacion_recurso:8"),
        (
            "competidor.adjudicacion_en_mi_segmento",
            {"empresa_id": 12},
            "competidor_en_mi_segmento:12",
        ),
        (
            "cuenta.vencimiento_proximo",
            {"fecha_fin": "2027-03-01"},
            "cuenta_vencimiento_proximo:2027-03-01",
        ),
        ("cuenta.publicacion_nueva", {}, "cuenta_publicacion_nueva"),
    ],
)
def test_tipo_de_notificacion_discrimina_por_hecho(
    tipo: str, payload: dict[str, Any], esperado: str
) -> None:
    """Dos documentos del mismo expediente son dos avisos; el mismo documento
    reemitido choca con el único de la bandeja y no duplica."""
    evento = {"id": 999, "payload": payload}
    assert event_dispatch._tipo_notificacion(evento, especificacion(tipo)) == esperado
