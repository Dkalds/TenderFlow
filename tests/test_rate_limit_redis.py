"""Tests para services/rate_limit_redis.py — backend Redis + dispatcher."""

from __future__ import annotations

import os
from unittest.mock import MagicMock, patch

#: Contraseña de Redis de mentira para los tests. Una sola aparición del literal:
#: detect-secrets agrupa por valor y fichero, y avisaría en cada uso si no.
_CLAVE_REDIS_FALSA = "s3creta"  # pragma: allowlist secret


class TestRateLimitRedis:
    def setup_method(self):
        import services.rate_limit_redis as mod

        self._mod = mod
        # Cliente y enfriamiento son estado de módulo: sin esto, un test que
        # deja Redis "caído" contaminaría a los siguientes.
        mod.reset_client()

    def teardown_method(self):
        self._mod.reset_client()

    def test_has_redis_no_url(self):
        with patch.dict(os.environ, {}, clear=False):
            os.environ.pop("REDIS_URL", None)
            # Even if redis module available, no URL means False
            assert not self._mod.has_redis()

    @patch.object(
        __import__("services.rate_limit_redis", fromlist=["_REDIS_AVAILABLE"]),
        "_REDIS_AVAILABLE",
        True,
    )
    def test_has_redis_with_url(self):
        with patch.dict(os.environ, {"REDIS_URL": "redis://localhost"}):
            assert self._mod.has_redis()

    def test_get_client_no_redis(self):
        with patch.object(self._mod, "has_redis", return_value=False):
            assert self._mod._get_client() is None

    def test_get_client_success(self):
        mock_redis_mod = MagicMock()
        mock_client = MagicMock()
        mock_redis_mod.Redis.from_url.return_value = mock_client

        with patch.object(self._mod, "has_redis", return_value=True):
            with patch.object(self._mod, "redis", mock_redis_mod):
                with patch.dict(os.environ, {"REDIS_URL": "redis://localhost"}):
                    result = self._mod._get_client()
        assert result is mock_client
        mock_client.ping.assert_called_once()

    def test_get_client_connection_error(self):
        mock_redis_mod = MagicMock()
        mock_redis_mod.Redis.from_url.side_effect = Exception("conn refused")

        with patch.object(self._mod, "has_redis", return_value=True):
            with patch.object(self._mod, "redis", mock_redis_mod):
                with patch.dict(os.environ, {"REDIS_URL": "redis://localhost"}):
                    result = self._mod._get_client()
        assert result is None

    def test_get_client_cached(self):
        sentinel = MagicMock()
        self._mod._client = sentinel
        with patch.object(self._mod, "has_redis", return_value=True):
            result = self._mod._get_client()
        assert result is sentinel

    def test_check_rate_limit_redis_no_client(self):
        with patch.object(self._mod, "_get_client", return_value=None):
            result = self._mod.check_rate_limit_redis("key1")
        assert result is None

    def test_check_rate_limit_redis_allowed(self):
        mock_client = MagicMock()
        mock_pipe = MagicMock()
        mock_client.pipeline.return_value = mock_pipe
        mock_pipe.execute.return_value = [None, None, 5, None]

        with patch.object(self._mod, "_get_client", return_value=mock_client):
            result = self._mod.check_rate_limit_redis("key1", max_calls=10)
        assert result is True
        mock_client.zrem.assert_not_called()

    def test_check_rate_limit_redis_exceeded(self):
        mock_client = MagicMock()
        mock_pipe = MagicMock()
        mock_client.pipeline.return_value = mock_pipe
        mock_pipe.execute.return_value = [None, None, 200, None]

        with patch.object(self._mod, "_get_client", return_value=mock_client):
            result = self._mod.check_rate_limit_redis("key1", max_calls=120)
        assert result is False

    def test_check_rate_limit_redis_pipeline_error(self):
        mock_client = MagicMock()
        mock_pipe = MagicMock()
        mock_client.pipeline.return_value = mock_pipe
        mock_pipe.execute.side_effect = Exception("pipe error")

        with patch.object(self._mod, "_get_client", return_value=mock_client):
            result = self._mod.check_rate_limit_redis("key1")
        assert result is None

    def test_check_rate_limit_dispatcher_redis(self):
        with patch.dict(os.environ, {"RATE_LIMIT_BACKEND": "redis"}):
            with patch.object(self._mod, "check_rate_limit_redis", return_value=True):
                result = self._mod.check_rate_limit("k")
        assert result is True

    def test_check_rate_limit_dispatcher_redis_fallback(self):
        with patch.dict(os.environ, {"RATE_LIMIT_BACKEND": "redis"}):
            with patch.object(self._mod, "check_rate_limit_redis", return_value=None):
                with patch("db.rate_limits.check_rate_limit_db", return_value=True) as mock_db:
                    result = self._mod.check_rate_limit("k")
        assert result is True
        mock_db.assert_called_once()

    def test_check_rate_limit_dispatcher_sqlite(self):
        with patch.dict(os.environ, {"RATE_LIMIT_BACKEND": "sqlite"}):
            with patch("db.rate_limits.check_rate_limit_db", return_value=False) as mock_db:
                result = self._mod.check_rate_limit("k", max_calls=50, window_seconds=30.0)
        assert result is False
        mock_db.assert_called_once_with("k", max_calls=50, window_seconds=30.0)

    def test_check_rate_limit_dispatcher_db_no_toca_redis(self):
        """``db`` explícito es el interruptor para volver a la BD: ni la prueba."""
        with patch.dict(os.environ, {"RATE_LIMIT_BACKEND": "db"}):
            with (
                patch.object(self._mod, "check_rate_limit_redis") as redis_check,
                patch("db.rate_limits.check_rate_limit_db", return_value=True),
            ):
                assert self._mod.check_rate_limit("k") is True
        redis_check.assert_not_called()

    def test_check_rate_limit_dispatcher_default_auto_sin_redis_va_a_bd(self):
        """El default es ``auto``: sin ``REDIS_URL`` resuelve la BD."""
        with patch.dict(os.environ, {}, clear=False):
            os.environ.pop("RATE_LIMIT_BACKEND", None)
            os.environ.pop("REDIS_URL", None)
            with patch("db.rate_limits.check_rate_limit_db", return_value=True) as mock_db:
                result = self._mod.check_rate_limit("k")
        assert result is True
        mock_db.assert_called_once()


class TestSemanticaDeLaVentana:
    """Lo que el backend Redis tiene que hacer igual que el de BD."""

    def setup_method(self):
        import services.rate_limit_redis as mod

        self._mod = mod
        mod.reset_client()

    def teardown_method(self):
        self._mod.reset_client()

    def _cliente(self, cuenta: int) -> MagicMock:
        cliente = MagicMock()
        cliente.pipeline.return_value.execute.return_value = [None, None, cuenta, None]
        return cliente

    def test_la_denegada_no_consume_cuota(self):
        """Se retira del set el mismo miembro que se añadió.

        El backend de BD solo inserta cuando permite. Sin el ``ZREM``, con Redis
        cada 429 alargaba la ventana del propio cliente: uno que reintentara por
        encima del límite no volvía a pasar nunca.
        """
        cliente = self._cliente(121)
        with patch.object(self._mod, "_get_client", return_value=cliente):
            assert self._mod.check_rate_limit_redis("ip:1.2.3.4", max_calls=120) is False

        pipe = cliente.pipeline.return_value
        clave, miembros = pipe.zadd.call_args.args
        cliente.zrem.assert_called_once_with(clave, *miembros.keys())

    def test_en_el_limite_exacto_aun_se_permite(self):
        cliente = self._cliente(120)
        with patch.object(self._mod, "_get_client", return_value=cliente):
            assert self._mod.check_rate_limit_redis("k", max_calls=120) is True
        cliente.zrem.assert_not_called()

    def test_las_claves_llevan_prefijo_propio(self):
        """El Redis es el de la caché de respuestas, cuyo namespace es ``api:``."""
        cliente = self._cliente(1)
        with patch.object(self._mod, "_get_client", return_value=cliente):
            self._mod.check_rate_limit_redis("api:ip:1.2.3.4")

        pipe = cliente.pipeline.return_value
        assert pipe.zadd.call_args.args[0] == "rl:api:ip:1.2.3.4"
        assert pipe.zcard.call_args.args[0] == "rl:api:ip:1.2.3.4"

    def test_dos_peticiones_del_mismo_instante_son_miembros_distintos(self):
        """Con el mismo miembro, el segundo ``ZADD`` solo movía el score y esa
        petición no contaba. Ahora las comprobaciones corren en hilos, así que
        dos en el mismo microsegundo ya no son imposibles."""
        cliente = self._cliente(1)
        # Se sustituye la referencia `time` del módulo, no `time.time` global:
        # parchear la función del módulo `time` la cambia para todo el proceso.
        reloj_parado = MagicMock()
        reloj_parado.time.return_value = 1_700_000_000.0
        with (
            patch.object(self._mod, "_get_client", return_value=cliente),
            patch.object(self._mod, "time", reloj_parado),
        ):
            self._mod.check_rate_limit_redis("k")
            self._mod.check_rate_limit_redis("k")

        pipe = cliente.pipeline.return_value
        primero, segundo = (llamada.args[1] for llamada in pipe.zadd.call_args_list)
        assert primero.keys() != segundo.keys()


class TestEnfriamiento:
    """Un Redis caído no se reintenta en cada petición."""

    def setup_method(self):
        import services.rate_limit_redis as mod

        self._mod = mod
        mod.reset_client()

    def teardown_method(self):
        self._mod.reset_client()

    def _con_redis(self, redis_mod: MagicMock):
        return (
            patch.object(self._mod, "has_redis", return_value=True),
            patch.object(self._mod, "redis", redis_mod),
            patch.dict(os.environ, {"REDIS_URL": "redis://cache:6379/0"}),
        )

    def test_tras_un_fallo_de_conexion_no_se_reintenta_hasta_el_fin_del_enfriamiento(self):
        """Era el fallo: cada request volvía a intentar conectar, con 1 s de timeout."""
        redis_mod = MagicMock()
        redis_mod.Redis.from_url.return_value.ping.side_effect = ConnectionError("refused")

        a, b, c = self._con_redis(redis_mod)
        with a, b, c:
            for _ in range(5):
                assert self._mod._get_client() is None
            assert redis_mod.Redis.from_url.call_count == 1

            # Vencido el enfriamiento, un solo intento más.
            self._mod._sin_redis_hasta = 0.0
            assert self._mod._get_client() is None
            assert redis_mod.Redis.from_url.call_count == 2

    def test_el_cliente_que_fallo_al_conectar_se_cierra(self):
        """Un ``ping`` que falla tras conectar (AUTH) dejaba un socket abierto."""
        redis_mod = MagicMock()
        candidato = redis_mod.Redis.from_url.return_value
        candidato.ping.side_effect = Exception("NOAUTH")

        a, b, c = self._con_redis(redis_mod)
        with a, b, c:
            assert self._mod._get_client() is None
        candidato.close.assert_called_once()

    def test_se_recupera_cuando_redis_vuelve(self):
        redis_mod = MagicMock()
        caido, sano = MagicMock(), MagicMock()
        caido.ping.side_effect = ConnectionError("refused")
        redis_mod.Redis.from_url.side_effect = [caido, sano]

        a, b, c = self._con_redis(redis_mod)
        with a, b, c:
            assert self._mod._get_client() is None
            self._mod._sin_redis_hasta = 0.0
            assert self._mod._get_client() is sano
            # Y queda cacheado: no se reconecta en cada petición.
            assert self._mod._get_client() is sano
        assert redis_mod.Redis.from_url.call_count == 2

    def test_un_fallo_en_plena_operacion_tambien_enfria_y_suelta_el_cliente(self):
        """Un Redis colgado no puede costar un timeout por petición."""
        redis_mod = MagicMock()
        cliente = redis_mod.Redis.from_url.return_value
        cliente.pipeline.return_value.execute.side_effect = TimeoutError("timeout")

        a, b, c = self._con_redis(redis_mod)
        with a, b, c:
            assert self._mod.check_rate_limit_redis("k") is None
            cliente.close.assert_called_once()
            # En enfriamiento: ni operación ni reconexión.
            assert self._mod.check_rate_limit_redis("k") is None
        assert redis_mod.Redis.from_url.call_count == 1
        assert cliente.pipeline.call_count == 1

    def test_mientras_otro_hilo_conecta_no_se_espera(self):
        """La petición que llega durante un intento de conexión va a la BD en
        vez de esperar el timeout del otro hilo."""
        redis_mod = MagicMock()

        a, b, c = self._con_redis(redis_mod)
        with a, b, c:
            assert self._mod._lock.acquire(blocking=False)
            try:
                assert self._mod._get_client() is None
            finally:
                self._mod._lock.release()
        redis_mod.Redis.from_url.assert_not_called()

    def test_el_cliente_no_encadena_reintentos_con_backoff(self):
        """redis-py ≥ 6 reintenta tres veces con backoff exponencial por
        defecto: con un Redis colgado, ~10 s por comprobación. Se fija uno."""
        from redis.retry import Retry

        redis_mod = MagicMock()
        a, b, c = self._con_redis(redis_mod)
        with a, b, c:
            self._mod._get_client()

        kwargs = redis_mod.Redis.from_url.call_args.kwargs
        assert isinstance(kwargs["retry"], Retry)
        assert kwargs["socket_timeout"] <= 1.0
        assert kwargs["socket_connect_timeout"] <= 1.0

    def test_la_contrasena_puede_venir_aparte_de_la_url(self):
        """``REDIS_PASSWORD`` es obligatoria en prod y no tiene por qué ir en la URL."""
        redis_mod = MagicMock()
        a, b, c = self._con_redis(redis_mod)
        with (
            a,
            b,
            c,
            patch.dict(os.environ, {"REDIS_PASSWORD": _CLAVE_REDIS_FALSA}),
        ):
            self._mod._get_client()

        assert redis_mod.Redis.from_url.call_args.kwargs["password"] == _CLAVE_REDIS_FALSA
