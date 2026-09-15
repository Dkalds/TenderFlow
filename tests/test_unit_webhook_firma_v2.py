"""Firma v2 con sello de tiempo y material de rotación (Ola 1 · Webhooks).

Unitarios de verdad: sin Postgres. Lo que fijan es el **contrato con el
receptor** —los bytes exactos que se firman y la cabecera en que viaja cada
cosa—, porque la receta de ``docs/integraciones/webhooks.md`` la copian
integraciones ajenas y un cambio de un carácter en el separador las rompería a
todas en silencio. Y que el reintento reutilice el sello original: con uno
regenerado, el mismo evento llegaría con dos firmas v2 distintas y un
reintento tardío quedaría siempre fuera de la ventana de replay.
"""

from __future__ import annotations

import hashlib
import hmac
import json
from datetime import UTC, datetime
from typing import Any

import pytest

from shared import crypto

# Vector fijo. Si cambia, cambia el contrato con los receptores: no se «arregla»
# el test, se abre un RFC (política de AGENTS.md §5, contrato público).
_SECRET = "whsec_test_0123456789"  # pragma: allowlist secret
_CUERPO = b'{"event":"watchlist_match","data":{"id":1},"timestamp":"2026-09-14T10:00:00+00:00"}'
_SELLO = 1789380000
_FIRMA_V1 = (
    "4050ceacee47716349fef0cce53d2ecd6eb22b28b41901a58bae21f1ab42aae5"  # pragma: allowlist secret
)
_FIRMA_V2 = (
    "99da46ec8f21db95b672e6add98f2e0a8ff301fbc51f480f905122d47417dbcd"  # pragma: allowlist secret
)


def _verificar_como_el_doc(
    secret: str, cabeceras: dict[str, str], cuerpo: bytes, *, ahora: float
) -> bool:
    """La receta Python de ``docs/integraciones/webhooks.md``, con el reloj inyectado."""
    try:
        timestamp = int(cabeceras["X-Webhook-Timestamp"])
    except (KeyError, ValueError):
        return False
    if abs(ahora - timestamp) > crypto.VENTANA_REPLAY_S:
        return False
    esperada = hmac.new(
        secret.encode("utf-8"), f"{timestamp}.".encode("ascii") + cuerpo, hashlib.sha256
    ).hexdigest()
    recibida = cabeceras.get("X-Webhook-Signature-V2", "").removeprefix("v2=")
    return hmac.compare_digest(esperada, recibida)


class TestVectorDeFirma:
    def test_el_sello_sale_de_la_marca_iso(self) -> None:
        assert crypto.segundos_unix("2026-09-14T10:00:00+00:00") == _SELLO

    def test_la_firma_v1_no_cambia(self) -> None:
        """Compatibilidad: los receptores que ya verifican v1 no se enteran."""
        assert crypto.firmar_webhook(_SECRET, _CUERPO) == _FIRMA_V1

    def test_la_firma_v2_es_hmac_de_sello_punto_cuerpo(self) -> None:
        assert crypto.firmar_webhook_v2(_SECRET, _SELLO, _CUERPO) == _FIRMA_V2

    def test_la_receta_del_doc_reproduce_la_firma(self) -> None:
        manual = hmac.new(
            _SECRET.encode(), f"{_SELLO}.".encode() + _CUERPO, hashlib.sha256
        ).hexdigest()
        assert manual == _FIRMA_V2

    def test_las_tres_cabeceras(self) -> None:
        assert crypto.cabeceras_de_firma(secret=_SECRET, body=_CUERPO, timestamp=_SELLO) == {
            "X-Webhook-Signature": f"sha256={_FIRMA_V1}",
            "X-Webhook-Timestamp": str(_SELLO),
            "X-Webhook-Signature-V2": f"v2={_FIRMA_V2}",
        }

    def test_otro_sello_cambia_la_v2_y_no_la_v1(self) -> None:
        """Es lo que distingue una firma con replay de una sin él."""
        otras = crypto.cabeceras_de_firma(secret=_SECRET, body=_CUERPO, timestamp=_SELLO + 1)
        assert otras["X-Webhook-Signature"] == f"sha256={_FIRMA_V1}"
        assert otras["X-Webhook-Signature-V2"] != f"v2={_FIRMA_V2}"

    def test_la_firma_va_sobre_los_bytes_crudos(self) -> None:
        """Re-serializar el JSON (espacios, orden) daría otra firma: el doc lo avisa."""
        reserializado = json.dumps(json.loads(_CUERPO)).encode()
        assert reserializado != _CUERPO
        assert crypto.firmar_webhook_v2(_SECRET, _SELLO, reserializado) != _FIRMA_V2


class TestRecetaDelReceptor:
    _CABECERAS = crypto.cabeceras_de_firma(secret=_SECRET, body=_CUERPO, timestamp=_SELLO)

    def test_acepta_dentro_de_la_ventana(self) -> None:
        assert _verificar_como_el_doc(_SECRET, self._CABECERAS, _CUERPO, ahora=_SELLO + 299)

    def test_rechaza_un_replay_fuera_de_la_ventana(self) -> None:
        assert not _verificar_como_el_doc(_SECRET, self._CABECERAS, _CUERPO, ahora=_SELLO + 301)
        assert not _verificar_como_el_doc(_SECRET, self._CABECERAS, _CUERPO, ahora=_SELLO - 301)

    def test_rechaza_otro_secret_u_otro_cuerpo(self) -> None:
        assert not _verificar_como_el_doc("otro", self._CABECERAS, _CUERPO, ahora=_SELLO)
        assert not _verificar_como_el_doc(_SECRET, self._CABECERAS, _CUERPO + b" ", ahora=_SELLO)

    def test_rechaza_un_sello_manipulado_aunque_la_v1_cuadre(self) -> None:
        """El ataque que la v1 no ve: mismo cuerpo, sello «fresco» inventado."""
        manipuladas = {**self._CABECERAS, "X-Webhook-Timestamp": str(_SELLO + 600)}
        assert not _verificar_como_el_doc(_SECRET, manipuladas, _CUERPO, ahora=_SELLO + 600)


class TestSegundosUnix:
    @pytest.mark.parametrize(
        "marca",
        [
            "2026-09-14T10:00:00+00:00",
            "2026-09-14T10:00:00Z",
            "2026-09-14T10:00:00.999999+00:00",
            "2026-09-14 10:00:00+00",  # offset corto de Postgres
            "2026-09-14T10:00:00",  # sin zona: UTC, como escribe now_utc_iso
            "2026-09-14T12:00:00+02:00",
        ],
    )
    def test_formatos_equivalentes(self, marca: str) -> None:
        assert crypto.segundos_unix(marca) == _SELLO

    def test_acepta_un_datetime(self) -> None:
        assert crypto.segundos_unix(datetime(2026, 9, 14, 10, 0, tzinfo=UTC)) == _SELLO

    def test_una_marca_que_no_es_fecha_lanza(self) -> None:
        with pytest.raises(ValueError):
            crypto.segundos_unix("ayer por la tarde")


class TestMaterialDeRotacion:
    _CLAVE = "clave-maestra-de-prueba-32-caracteres!!"  # pragma: allowlist secret

    def test_el_sentinel_v1_no_lleva_material(self) -> None:
        assert crypto.material_de_secreto(crypto.DERIVED_SECRET_SENTINEL) is None
        assert crypto.material_de_secreto("derived:v2:") is None
        assert crypto.material_de_secreto("secreto-legacy-en-claro") is None

    def test_el_sentinel_rotado_lleva_el_material_y_sigue_siendo_derivado(self) -> None:
        sentinel = crypto.sentinel_rotado("abc")
        assert sentinel == "derived:v2:abc"
        assert crypto.is_derived_secret(sentinel)
        assert crypto.material_de_secreto(sentinel) == "abc"

    def test_un_material_vacio_no_es_una_rotacion(self) -> None:
        with pytest.raises(ValueError):
            crypto.sentinel_rotado("")

    def test_v1_resuelve_igual_que_antes(self) -> None:
        """Los webhooks creados antes de la rotación siguen firmando igual."""
        assert crypto.resolve_derived_secret(
            self._CLAVE, 7, crypto.DERIVED_SECRET_SENTINEL
        ) == crypto.derive_webhook_secret(self._CLAVE, 7)

    def test_el_material_cambia_el_secreto(self) -> None:
        v1 = crypto.derive_webhook_secret(self._CLAVE, 7)
        rotado = crypto.resolve_derived_secret(self._CLAVE, 7, crypto.sentinel_rotado("m1"))
        assert rotado == crypto.derive_webhook_secret(self._CLAVE, 7, "m1")
        assert rotado != v1
        assert rotado != crypto.resolve_derived_secret(self._CLAVE, 7, crypto.sentinel_rotado("m2"))
        assert rotado != crypto.derive_webhook_secret(self._CLAVE, 8, "m1")

    def test_el_material_nuevo_es_aleatorio_y_url_safe(self) -> None:
        a, b = crypto.nuevo_material_de_secreto(), crypto.nuevo_material_de_secreto()
        assert a != b
        assert len(a) == 22 and a.replace("-", "").replace("_", "").isalnum()


class TestScopeDeLaRuta:
    def test_rotar_exige_admin_con_api_key(self) -> None:
        from api.scopes import required_scope_for_request

        assert required_scope_for_request("POST", "/api/v1/webhooks/1/rotate-secret") == "admin"


# ── Entrega y reintento (db/webhooks.py aislado de Postgres, como test_c2_cuentas) ──


class _Cursor:
    """Sustituye ``connect()``: una fila de webhook para el abanico y para el reintento."""

    def execute(self, *_a: Any, **_k: Any) -> _Cursor:
        return self

    def fetchall(self) -> list[tuple[Any, ...]]:
        return [(7, "https://hook.example.com/x", "s3cret", "*")]

    def fetchone(self) -> tuple[Any, ...]:
        return ("https://hook.example.com/x", "s3cret")

    def __enter__(self) -> _Cursor:
        return self

    def __exit__(self, *_a: Any) -> bool:
        return False


def _aislar(monkeypatch: pytest.MonkeyPatch, respuestas: list[int]) -> tuple[dict, list[dict]]:
    """Devuelve lo escrito por ``crear_entrega`` y las peticiones «enviadas»."""
    import db.webhooks as wh

    escrito: dict[str, Any] = {}
    enviado: list[dict[str, Any]] = []
    monkeypatch.setattr(wh, "connect", lambda: _Cursor())
    monkeypatch.setattr(wh, "validate_outbound_url", lambda *_a, **_k: None)
    monkeypatch.setattr(wh, "_allowed_webhook_hosts", frozenset)
    monkeypatch.setattr(wh, "_resolve_secret", lambda _wid, s: s)
    monkeypatch.setattr(wh, "_record_delivery", lambda *_a, **_k: None)
    monkeypatch.setattr(wh, "marcar_webhook_tras_intento", lambda *_a, **_k: None)
    monkeypatch.setattr(wh, "marcar_para_reintento", lambda _id, **_kw: True)
    monkeypatch.setattr(wh, "crear_entrega", lambda **kw: escrito.update(kw) or 1)

    def _fake_send(*, url: str, headers: dict[str, str], body: bytes, allowed_hosts: Any):
        enviado.append({"headers": headers, "body": body})
        return respuestas.pop(0), None

    monkeypatch.setattr(wh, "_intentar_entrega", _fake_send)
    return escrito, enviado


class TestEntregaConSello:
    def test_la_entrega_lleva_las_tres_cabeceras_y_el_sello_es_el_del_cuerpo(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        import db.webhooks as wh

        escrito, enviado = _aislar(monkeypatch, [200])
        wh.trigger_event("watchlist_match", {"id": 1})

        cabeceras, cuerpo = enviado[0]["headers"], enviado[0]["body"]
        sello = int(cabeceras["X-Webhook-Timestamp"])
        assert (
            cabeceras["X-Webhook-Signature"] == f"sha256={crypto.firmar_webhook('s3cret', cuerpo)}"
        )
        assert cabeceras["X-Webhook-Signature-V2"] == (
            f"v2={crypto.firmar_webhook_v2('s3cret', sello, cuerpo)}"
        )
        # Un solo instante: cuerpo, cabecera y fila de la entrega.
        assert sello == crypto.segundos_unix(json.loads(cuerpo)["timestamp"])
        assert sello == crypto.segundos_unix(escrito["created_at"])
        assert cabeceras["X-Webhook-Delivery"] == escrito["delivery_uid"]

    def test_el_reintento_reutiliza_el_sello_original(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Con el sello regenerado, el mismo evento tendría dos firmas v2 y el
        reintento tardío quedaría siempre fuera de la ventana del receptor."""
        import db.webhooks as wh

        escrito, enviado = _aislar(monkeypatch, [503, 200])
        wh.trigger_event("watchlist_match", {"id": 1})
        primera = enviado[0]["headers"]

        # El reloj avanza un día entre el primer intento y el reintento.
        despues = datetime.fromtimestamp(int(primera["X-Webhook-Timestamp"]) + 86_400, tz=UTC)
        monkeypatch.setattr(wh, "now_utc", lambda: despues)

        entrega = {
            "id": 42,
            "webhook_id": 7,
            "event_type": escrito["event_type"],
            "payload_json": escrito["payload_json"],
            "delivery_uid": escrito["delivery_uid"],
            "intentos": 1,
            "created_at": escrito["created_at"],
        }
        assert wh.reenviar(entrega) is True
        segunda = enviado[1]["headers"]

        assert segunda["X-Webhook-Timestamp"] == primera["X-Webhook-Timestamp"]
        assert segunda["X-Webhook-Signature-V2"] == primera["X-Webhook-Signature-V2"]
        assert segunda["X-Webhook-Signature"] == primera["X-Webhook-Signature"]
        assert segunda["X-Webhook-Delivery"] == primera["X-Webhook-Delivery"]
        assert enviado[1]["body"] == enviado[0]["body"]


class TestSelloDeLaEntrega:
    """``_timestamp_de_entrega``: de dónde sale el sello cuando la fila no lo trae."""

    _CUERPO_JSON = '{"event":"watchlist_match","data":{},"timestamp":"2026-09-14T10:00:00+00:00"}'

    def test_prefiere_created_at(self) -> None:
        import db.webhooks as wh

        entrega = {"created_at": "2026-09-14T10:00:05+00:00", "payload_json": self._CUERPO_JSON}
        assert wh._timestamp_de_entrega(entrega) == _SELLO + 5

    def test_sin_created_at_usa_el_timestamp_del_cuerpo(self) -> None:
        """Filas anteriores a esta cabecera y llamantes que no lo traen."""
        import db.webhooks as wh

        assert wh._timestamp_de_entrega({"payload_json": self._CUERPO_JSON}) == _SELLO

    def test_un_created_at_ilegible_cae_al_cuerpo(self) -> None:
        import db.webhooks as wh

        entrega = {"created_at": "??", "payload_json": self._CUERPO_JSON}
        assert wh._timestamp_de_entrega(entrega) == _SELLO

    def test_sin_nada_sella_con_ahora(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Peor que el sello original, mejor que no reenviar."""
        import db.webhooks as wh

        ahora = datetime(2026, 9, 14, 11, 0, tzinfo=UTC)
        monkeypatch.setattr(wh, "now_utc", lambda: ahora)
        assert wh._timestamp_de_entrega({"payload_json": '{"text":"slack"}'}) == _SELLO + 3600
        assert wh._timestamp_de_entrega({"payload_json": "no es json"}) == _SELLO + 3600
