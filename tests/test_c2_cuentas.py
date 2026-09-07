"""Cuentas y seguridad: lo que el usuario no podía gobernar (C2).

Cuatro huecos que el plan complementario mide, y que estos tests fijan:

- `db/sessions.py::list_active_sessions` existía y **nadie la llamaba**: el
  usuario solo tenía «cerrar todas» (hecho 7).
- `api_key_tiers` existe desde `v28` con tres tiers sembrados y **ninguna ruta
  ni middleware leía la columna** (hecho 9).
- Los errores de JavaScript terminaban en un `log.warning` (hecho 12).
- Las preferencias de notificación **no las modelaba nada** (hecho 13).
"""

from __future__ import annotations

import inspect

import pytest


class TestSesiones:
    def test_el_id_publico_no_es_el_token_ni_el_hash(self) -> None:
        """Lo que sale a la API no puede abrir la sesión."""
        from db.sessions import SESSION_PUBLIC_ID_LEN, session_public_id

        hash_completo = "a" * 64
        publico = session_public_id(hash_completo)
        assert publico == "a" * SESSION_PUBLIC_ID_LEN
        assert len(publico) < len(hash_completo)

    def test_el_id_publico_es_estable(self) -> None:
        """Revocar exige poder nombrar la misma sesión dos veces."""
        from db.sessions import session_public_id

        assert session_public_id("abc123def456789") == session_public_id("abc123def456789")

    def test_un_id_corto_no_revoca_nada(self) -> None:
        """Un prefijo de dos caracteres casaría con muchas sesiones."""
        from db.sessions import revoke_session_by_public_id

        assert revoke_session_by_public_id(1, "") is False
        assert revoke_session_by_public_id(1, "ab") is False

    def test_la_revocacion_filtra_por_usuario(self) -> None:
        """Sin el `user_id`, un id público enumerable cerraría sesiones ajenas."""
        import db.sessions as mod

        fuente = inspect.getsource(mod.revoke_session_by_public_id)
        assert "user_id = %s" in fuente

    def test_el_listado_no_expone_el_hash(self) -> None:
        from api.routes.me import SessionOut

        campos = set(SessionOut.model_fields)
        assert "token_hash" not in campos
        assert "token" not in campos
        assert "actual" in campos, "sin esto el usuario no sabe cuál es la suya"


class TestPresupuestoPorOrganizacion:
    """C2.9 — dos usuarios de la misma organización comparten cubo."""

    @staticmethod
    def _guard(**kwargs: object):
        from llm.budget import BudgetGuard

        base: dict[str, object] = {
            "daily_limit_usd": 100.0,
            "monthly_limit_usd": 1000.0,
            "daily_limit_usd_per_user": 50.0,
            "daily_limit_usd_per_org": 1.5,
            "mode": "enforce",
        }
        base.update(kwargs)
        return BudgetGuard(**base)  # type: ignore[arg-type]

    def test_dos_usuarios_de_la_misma_organizacion_comparten(self) -> None:
        from llm.budget import LLMBudgetExceeded

        g = self._guard()
        g.record(1.0, "usuario-a", "org-7")
        g.check("usuario-a", "org-7")  # 1.0 < 1.5: pasa

        g.record(1.0, "usuario-b", "org-7")
        with pytest.raises(LLMBudgetExceeded) as exc:
            g.check("usuario-b", "org-7")
        assert exc.value.scope == "org"

    def test_otra_organizacion_no_se_ve_afectada(self) -> None:
        g = self._guard()
        g.record(5.0, "usuario-a", "org-7")
        g.check("usuario-c", "org-9")

    def test_el_429_dice_que_cubo_se_agoto(self) -> None:
        """«Presupuesto agotado» sin ámbito hace creer que el servicio cayó."""
        from llm.budget import LLMBudgetExceeded

        assert "organización" in str(LLMBudgetExceeded("daily", 2.0, 1.0, scope="org"))
        assert "cuenta" in str(LLMBudgetExceeded("daily", 2.0, 1.0, scope="user"))
        assert "global" in str(LLMBudgetExceeded("daily", 2.0, 1.0, scope="global"))

    def test_el_cubo_se_alimenta_ademas_de_comprobarse(self) -> None:
        """Un tope que no acumula no corta nunca: el modo de fallo del ítem."""
        g = self._guard(daily_limit_usd_per_org=1000.0)
        g.record(3.0, None, "org-7")
        assert g.spent("daily", "org:org-7") == pytest.approx(3.0)

    def test_sin_organizacion_se_comporta_como_antes(self) -> None:
        g = self._guard()
        g.record(10.0, "usuario-a")
        g.check("usuario-a")


class TestErroresDeCliente:
    def test_la_huella_agrupa_el_mismo_error(self) -> None:
        """Mil ocurrencias son una fila, no mil: eso es lo que el log no daba."""
        from db.repositories.client_errors import fingerprint

        a = fingerprint(
            mensaje="Cannot read x of undefined at line 4211", ruta="/radar", origen="onerror"
        )
        b = fingerprint(
            mensaje="Cannot read x of undefined at line 9873", ruta="/radar", origen="onerror"
        )
        assert a == b, "los números que cambian entre ocurrencias no crean errores nuevos"

    def test_errores_distintos_no_colisionan(self) -> None:
        from db.repositories.client_errors import fingerprint

        a = fingerprint(mensaje="Cannot read x", ruta="/radar", origen="onerror")
        b = fingerprint(mensaje="Network request failed", ruta="/radar", origen="onerror")
        assert a != b

    def test_la_ruta_forma_parte_de_la_huella(self) -> None:
        """El mismo mensaje en dos pantallas son dos problemas distintos."""
        from db.repositories.client_errors import fingerprint

        a = fingerprint(mensaje="boom", ruta="/radar", origen="onerror")
        b = fingerprint(mensaje="boom", ruta="/detalle", origen="onerror")
        assert a != b

    def test_la_fila_no_lleva_identidad(self) -> None:
        from api.routes.security import ClientErrorRow

        campos = set(ClientErrorRow.model_fields)
        for prohibido in ("ip", "email", "user_id", "user_agent", "query"):
            assert prohibido not in campos, f"la tabla no puede guardar {prohibido}"

    def test_la_retencion_purga_por_la_ultima_ocurrencia(self) -> None:
        """Un error que sigue pasando no caduca por haber empezado hace un mes."""
        from scheduler.retention import COLUMNA_FECHA

        assert COLUMNA_FECHA["client_errors"] == "ultima_vez"


class TestPreferenciasDeNotificacion:
    def test_el_defecto_no_es_apagado(self) -> None:
        """Apagar por omisión hace que nadie se entere y nadie sepa por qué."""
        from db.repositories.notification_preferences import DEFECTOS

        assert DEFECTOS["in_app"] == "immediate"
        assert DEFECTOS["email"] == "daily"

    def test_el_webhook_si_nace_apagado(self) -> None:
        """Mandar a un endpoint no configurado no es notificar."""
        from db.repositories.notification_preferences import frecuencia_por_defecto

        assert frecuencia_por_defecto("webhook") == "off"

    def test_un_canal_desconocido_no_notifica(self) -> None:
        from db.repositories.notification_preferences import frecuencia_por_defecto

        assert frecuencia_por_defecto("telepatia") == "off"

    def test_el_vocabulario_es_cerrado(self) -> None:
        from db.repositories.notification_preferences import CANALES, FRECUENCIAS, guardar

        assert set(FRECUENCIAS) == {"immediate", "daily", "off"}
        assert set(CANALES) == {"email", "in_app", "webhook"}
        with pytest.raises(ValueError, match="frecuencia"):
            guardar(1, tipo="pursuit.assigned", canal="email", frecuencia="a-veces")
        with pytest.raises(ValueError, match="canal"):
            guardar(1, tipo="pursuit.assigned", canal="paloma", frecuencia="off")

    def test_el_contrato_publica_los_defectos(self) -> None:
        """Sin ellos el frontend no puede pintar un ajuste que nadie tocó."""
        from api.routes.me import NotificationPreferencesResult

        assert "defaults" in NotificationPreferencesResult.model_fields


class TestTiersDeApiKey:
    def test_sin_limite_propio_devuelve_none_no_cero(self) -> None:
        """`enterprise` declara `per_minute_limit = 0` = sin tope.

        Confundir «sin tope» con «cero requests» dejaría fuera al tier que más
        paga, y el fallo sería un 429 permanente en el cliente más importante.
        """
        import db.repositories.api_keys as mod

        fuente = inspect.getsource(mod.tier_limit_por_hash)
        assert "return None" in fuente
        assert "limite > 0" in fuente

    def test_el_bucket_va_por_clave_no_por_ip(self) -> None:
        """Dos claves tras el mismo NAT no comparten cuota."""
        import api.middleware as mod

        fuente = inspect.getsource(mod._tier_bucket)
        assert "apikey:" in fuente
        assert "hash_api_key" in fuente

    def test_el_bucket_no_expone_el_token(self) -> None:
        import api.middleware as mod

        fuente = inspect.getsource(mod._tier_bucket)
        assert "key_hash[:16]" in fuente, "ni el token ni el hash entero salen a la clave"

    def test_un_fallo_de_bd_no_tumba_el_rate_limiter(self) -> None:
        import api.middleware as mod

        assert "except Exception" in inspect.getsource(mod._tier_limit)

    def test_los_scopes_reservados_no_se_autoconceden(self) -> None:
        """Crear la clave la pide el usuario: sin esto, es escalada servida."""
        from fastapi import HTTPException

        from api.routes.me import _SCOPES_RESERVADOS, _validar_scopes

        assert {"admin", "*"} <= _SCOPES_RESERVADOS
        with pytest.raises(HTTPException) as exc:
            _validar_scopes("admin,data:read", {"is_admin": False})
        assert exc.value.status_code == 403
        assert _validar_scopes("data:read", {"is_admin": False}) == "data:read"

    def test_un_admin_si_puede(self) -> None:
        from api.routes.me import _validar_scopes

        assert _validar_scopes("admin", {"is_admin": True}) == "admin"


class TestReintentoDeWebhooks:
    """C2.4 — un despliegue del receptor no puede perder eventos."""

    def test_el_backoff_es_exponencial_desde_un_minuto(self) -> None:
        from datetime import timedelta

        from services.webhook_retry import espera_para

        assert espera_para(1) == timedelta(0)
        assert espera_para(2) == timedelta(minutes=1)
        assert espera_para(3) == timedelta(minutes=2)
        assert espera_para(4) == timedelta(minutes=4)
        assert espera_para(5) == timedelta(minutes=8)
        assert espera_para(6) == timedelta(minutes=16)

    def test_agotados_los_intentos_no_hay_espera(self) -> None:
        """`None` y no cero: confundirlas haría un bucle."""
        from services.webhook_retry import MAX_INTENTOS, espera_para

        assert espera_para(MAX_INTENTOS + 1) is None

    def test_el_techo_esta_puesto_antes_de_necesitarlo(self) -> None:
        """Subir MAX_INTENTOS no puede mandar un reintento a dos días vista."""
        from datetime import timedelta

        from services.webhook_retry import ESPERA_MAXIMA, espera_para

        assert timedelta(hours=6) == ESPERA_MAXIMA
        assert espera_para(20) is None  # el tope de intentos manda antes

    def test_tres_fallos_y_un_exito_dejan_la_entrega_entregada(self) -> None:
        """El criterio de aceptación del ítem, literal."""
        from services.webhook_retry import decidir

        intentos = 0
        for _ in range(3):
            intentos += 1
            d = decidir(exito=False, intentos_hechos=intentos)
            assert d.estado == "pending"
            assert d.desactivar is False, "un fallo transitorio no desactiva el webhook"
            assert d.proximo_intento is not None

        intentos += 1
        final = decidir(exito=True, intentos_hechos=intentos)
        assert final.estado == "delivered"
        assert final.proximo_intento is None
        assert final.desactivar is False

    def test_solo_se_desactiva_tras_agotar_los_reintentos(self) -> None:
        from services.webhook_retry import MAX_INTENTOS, decidir

        for intentos in range(1, MAX_INTENTOS):
            assert decidir(exito=False, intentos_hechos=intentos).desactivar is False
        agotado = decidir(exito=False, intentos_hechos=MAX_INTENTOS)
        assert agotado.estado == "failed"
        assert agotado.desactivar is True

    def test_la_reentrega_no_reinicia_el_contador(self) -> None:
        """Si lo reiniciara, el botón sería reintentar un endpoint muerto sin fin."""
        import inspect

        import db.repositories.webhooks as mod

        fuente = inspect.getsource(mod.encolar_reintento)
        assert "intentos = 0" not in fuente
        assert "intentos = 1" not in fuente

    def test_la_reentrega_no_toca_lo_ya_entregado(self) -> None:
        import inspect

        import db.repositories.webhooks as mod

        assert "estado <> 'delivered'" in inspect.getsource(mod.encolar_reintento)


class TestCspEstilosInline:
    """C2.8 — el bloqueo medido, y por qué la corrección parcial es peor."""

    def test_el_ratchet_solo_baja(self) -> None:
        from scripts.check_inline_styles import MAX_ESTILOS_INLINE, contar

        total = sum(contar().values())
        assert total <= MAX_ESTILOS_INLINE, (
            f"{total - MAX_ESTILOS_INLINE} estilo/s inline nuevo/s: cada uno aleja "
            "el momento en que `style-src` puede dejar de llevar `'unsafe-inline'`"
        )

    def test_el_csp_explica_por_que_sigue_unsafe_inline(self) -> None:
        """Un relajamiento sin motivo escrito se hereda sin revisarse."""
        from pathlib import Path

        proxy = (Path(__file__).resolve().parent.parent / "web" / "src" / "proxy.ts").read_text(
            encoding="utf-8"
        )
        assert "C2.8" in proxy
        assert "check_inline_styles" in proxy


class TestCicloDeVidaDeLaOrganizacion:
    """C2.2 — traspaso, salida y borrado (ADR-030 §D)."""

    def test_la_confirmacion_es_literal(self) -> None:
        """Un botón no basta: la acción no tiene deshacer y borra trabajo ajeno."""
        from services.organizations import CONFIRMACION_BORRADO, OrganizationLifecycleError
        from services.organizations import borrar_organizacion as borrar

        with pytest.raises(OrganizationLifecycleError, match="BORRAR"):
            borrar(organization_id=1, actor_user_id=1, confirmacion="si")
        assert CONFIRMACION_BORRADO == "BORRAR"

    def test_no_se_puede_traspasar_a_uno_mismo(self) -> None:
        from services.organizations import (
            OrganizationLifecycleError,
            transferir_propiedad,
        )

        with pytest.raises(OrganizationLifecycleError):
            transferir_propiedad(organization_id=1, actor_user_id=7, nuevo_owner_user_id=7)

    def test_el_traspaso_es_atomico(self) -> None:
        """Dos owners es un estado que ningún flujo sabe leer; cero, tampoco."""
        import db.repositories.organizations as mod

        fuente = inspect.getsource(mod.OrganizationRepository.traspasar_propiedad)
        # Las dos escrituras dentro del mismo `with connect()`.
        assert fuente.count("with connect()") == 1
        assert fuente.count("UPDATE organization_members") == 2

    def test_el_traspaso_exige_miembro_activo(self) -> None:
        """Invitar y traspasar son cosas distintas."""
        import db.repositories.organizations as mod

        fuente = inspect.getsource(mod.OrganizationRepository.traspasar_propiedad)
        assert "status = 'active'" in fuente
        assert "return False" in fuente

    def test_el_owner_saliente_queda_como_admin(self) -> None:
        """Quien monta un equipo no debería perder el acceso al traspasarlo."""
        import db.repositories.organizations as mod

        fuente = inspect.getsource(mod.OrganizationRepository.traspasar_propiedad)
        assert "role = 'admin'" in fuente

    def test_salir_no_borra_la_membresia(self) -> None:
        """Un comentario firmado por alguien que ya no está sigue siendo suyo."""
        import db.repositories.organizations as mod

        fuente = inspect.getsource(mod.OrganizationRepository.salir)
        assert "status = 'revoked'" in fuente
        assert "DELETE" not in fuente.upper()

    def test_el_recuento_precede_a_la_confirmacion(self) -> None:
        """«14 oportunidades y 37 comentarios» es una advertencia; «¿seguro?» no."""
        from api.routes.pursuits import OrganizationDeletionSummary

        assert {"oportunidades", "comentarios", "miembros"} <= set(
            OrganizationDeletionSummary.model_fields
        )

    def test_las_rutas_existen(self) -> None:
        from api.app import app

        rutas = {r.path for r in app.routes if hasattr(r, "path")}
        for ruta in (
            "/api/v1/organizations/{organization_id}/transfer-ownership",
            "/api/v1/organizations/{organization_id}/leave",
            "/api/v1/organizations/{organization_id}/delete",
            "/api/v1/organizations/{organization_id}/deletion-preview",
        ):
            assert ruta in rutas, f"falta {ruta}"

    def test_el_borrado_exige_sesion_reciente(self) -> None:
        """Se lleva trabajo de otras personas y no tiene deshacer."""
        import api.routes.pursuits as mod

        fuente = inspect.getsource(mod.post_delete_organization)
        assert "require_recent_session" in fuente


class TestEntregaReintentable:
    """C2.4 — la parte que faltaba: que el reintento *ocurra*.

    `decidir()` sabía cuándo tocaba el siguiente intento y `pendientes_de_reintento`
    sabía leerlos, pero `trigger_event` no dejaba nada `pending` y ningún job
    miraba la cola: la capacidad estaba escrita y no tenía puerta.
    """

    @staticmethod
    def _webhook_falso(monkeypatch, status_code: int):
        """Aísla `trigger_event` de la red y de Postgres, y devuelve lo escrito."""
        import db.webhooks as wh

        escrito: dict[str, object] = {}
        enviado: list[dict[str, object]] = []

        class _Cursor:
            def execute(self, *_a, **_k):
                return self

            def fetchall(self):
                return [(7, "https://hook.example.com/x", "s3cret", "*")]

            def fetchone(self):
                return None

            def __enter__(self):
                return self

            def __exit__(self, *_a):
                return False

        monkeypatch.setattr(wh, "connect", lambda: _Cursor())
        monkeypatch.setattr(wh, "validate_outbound_url", lambda *_a, **_k: None)
        monkeypatch.setattr(wh, "_allowed_webhook_hosts", frozenset)
        monkeypatch.setattr(wh, "_resolve_secret", lambda _wid, s: s)
        monkeypatch.setattr(wh, "_record_delivery", lambda *_a, **_k: None)
        monkeypatch.setattr(wh, "marcar_webhook_tras_intento", lambda *_a, **_k: None)
        monkeypatch.setattr(wh, "crear_entrega", lambda **kw: escrito.update(kw) or 1)

        def _fake_send(*, url, headers, body, allowed_hosts):
            enviado.append({"url": url, "headers": headers, "body": body})
            return status_code, None

        monkeypatch.setattr(wh, "_intentar_entrega", _fake_send)
        return escrito, enviado

    def test_una_entrega_fallida_queda_pendiente_con_fecha(self, monkeypatch) -> None:
        import db.webhooks as wh

        escrito, _ = self._webhook_falso(monkeypatch, 503)
        assert wh.trigger_event("watchlist_match", {"id": 1}) == 0
        assert escrito["estado"] == "pending"
        assert escrito["proximo_intento"] is not None, (
            "sin fecha de reintento la fila es un registro histórico, no una cola"
        )

    def test_una_entrega_correcta_no_deja_cola(self, monkeypatch) -> None:
        import db.webhooks as wh

        escrito, _ = self._webhook_falso(monkeypatch, 200)
        assert wh.trigger_event("watchlist_match", {"id": 1}) == 1
        assert escrito["estado"] == "delivered"
        assert escrito["proximo_intento"] is None

    def test_la_entrega_guarda_el_cuerpo_que_firmó(self, monkeypatch) -> None:
        """Reconstruirlo en el reintento cambiaría el `timestamp`, y con él la firma."""
        import db.webhooks as wh

        escrito, enviado = self._webhook_falso(monkeypatch, 500)
        wh.trigger_event("watchlist_match", {"id": 1})
        assert escrito["payload_json"].encode("utf-8") == enviado[0]["body"]

    def test_el_identificador_de_entrega_viaja_en_la_cabecera(self, monkeypatch) -> None:
        import db.webhooks as wh

        escrito, enviado = self._webhook_falso(monkeypatch, 500)
        wh.trigger_event("watchlist_match", {"id": 1})
        assert enviado[0]["headers"]["X-Webhook-Delivery"] == escrito["delivery_uid"]

    def test_el_reenvío_repite_cuerpo_firma_e_identificador(self, monkeypatch) -> None:
        """El criterio del ítem: la firma se recalcula sobre el **mismo** cuerpo."""
        import db.webhooks as wh

        intentos: list[dict[str, object]] = []
        estados: list[dict[str, object]] = []

        class _Cursor:
            def execute(self, *_a, **_k):
                return self

            def fetchone(self):
                return ("https://hook.example.com/x", "s3cret")

            def __enter__(self):
                return self

            def __exit__(self, *_a):
                return False

        monkeypatch.setattr(wh, "connect", lambda: _Cursor())
        monkeypatch.setattr(wh, "validate_outbound_url", lambda *_a, **_k: None)
        monkeypatch.setattr(wh, "_allowed_webhook_hosts", frozenset)
        monkeypatch.setattr(wh, "_resolve_secret", lambda _wid, s: s)
        monkeypatch.setattr(wh, "_record_delivery", lambda *_a, **_k: None)
        monkeypatch.setattr(wh, "marcar_webhook_tras_intento", lambda *_a, **_k: None)
        monkeypatch.setattr(
            wh, "marcar_para_reintento", lambda _id, **kw: estados.append(kw) or True
        )

        def _fake_send(*, url, headers, body, allowed_hosts):
            intentos.append({"headers": headers, "body": body})
            return (200 if len(intentos) == 4 else 503), None

        monkeypatch.setattr(wh, "_intentar_entrega", _fake_send)

        entrega = {
            "id": 42,
            "webhook_id": 7,
            "event_type": "watchlist_match",
            "payload_json": '{"event":"watchlist_match","data":{},"timestamp":"2026-09-06T00:00:00Z"}',
            "delivery_uid": "abc123",
            "intentos": 1,
        }
        for n in (1, 2, 3):
            assert wh.reenviar(entrega) is False
            entrega["intentos"] = n + 1
            assert estados[-1]["estado"] == "pending"

        assert wh.reenviar(entrega) is True
        assert estados[-1]["estado"] == "delivered"
        assert estados[-1]["proximo_intento"] is None

        firmas = {i["headers"]["X-Webhook-Signature"] for i in intentos}
        cuerpos = {i["body"] for i in intentos}
        uids = {i["headers"]["X-Webhook-Delivery"] for i in intentos}
        assert len(cuerpos) == 1, "el reintento cambió el cuerpo"
        assert len(firmas) == 1, "la firma dejó de cuadrar con el cuerpo original"
        assert uids == {"abc123"}, "el receptor no podría deduplicar"

    def test_el_bloqueo_ssrf_no_entra_en_la_cola(self, monkeypatch) -> None:
        """Reintentar una IP privada seis veces no la vuelve pública."""
        import db.webhooks as wh

        estados: list[dict[str, object]] = []
        monkeypatch.setattr(
            wh,
            "validate_outbound_url",
            lambda *_a, **_k: (_ for _ in ()).throw(ValueError("ip privada")),
        )
        monkeypatch.setattr(wh, "_allowed_webhook_hosts", frozenset)
        monkeypatch.setattr(
            wh, "marcar_para_reintento", lambda _id, **kw: estados.append(kw) or True
        )

        class _Cursor:
            def execute(self, *_a, **_k):
                return self

            def fetchone(self):
                return ("https://10.0.0.1/x", "s")

            def __enter__(self):
                return self

            def __exit__(self, *_a):
                return False

        monkeypatch.setattr(wh, "connect", lambda: _Cursor())
        entrega = {
            "id": 42,
            "webhook_id": 7,
            "event_type": "e",
            "payload_json": "{}",
            "delivery_uid": "u",
            "intentos": 1,
        }
        assert wh.reenviar(entrega) is False
        assert estados[-1]["estado"] == "failed"
        assert estados[-1]["proximo_intento"] is None

    def test_el_job_está_en_el_plano_de_ejecución(self) -> None:
        """Un job fuera de `CANONICAL_STEPS` es código que en producción no corre."""
        from scheduler.jobs import build_default_registry
        from scheduler.pipeline_runs import CANONICAL_STEPS, STEP_TIER

        job = next(j for j in build_default_registry() if j.name == "webhook_reintentos")
        assert job.plane == "pipeline"
        assert "webhook_reintentos" in CANONICAL_STEPS
        assert STEP_TIER["webhook_reintentos"] == "advisory", (
            "un receptor externo caído no puede sacar la pasada en rojo"
        )

    def test_el_job_tolera_la_tabla_sin_migrar(self, monkeypatch) -> None:
        import db.repositories.webhooks as repo
        import scheduler.jobs.webhook_reintentos as job

        def _boom(**_kw):
            raise RuntimeError("column proximo_intento does not exist")

        monkeypatch.setattr(repo, "pendientes_de_reintento", _boom)
        assert job.run() == {"pendientes": 0, "entregadas": 0, "fallidas": 0}
