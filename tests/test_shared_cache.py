"""Tests para shared/cache.py — cache unificado con backends Memory y Redis."""

from __future__ import annotations

import asyncio
import json
import threading
import time
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

#: Contraseña de Redis de mentira para los tests. Una sola aparición del literal:
#: detect-secrets agrupa por valor y fichero, y avisaría en cada uso si no.
_CLAVE_REDIS_FALSA = "s3creta"  # pragma: allowlist secret

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _fresh_import():
    """Importa shared.cache y resetea su estado global."""
    import shared.cache as mod

    mod.reset_cache()
    return mod


# ---------------------------------------------------------------------------
# _MemoryBackend
# ---------------------------------------------------------------------------


class TestMemoryBackend:
    """Tests unitarios para _MemoryBackend."""

    def _make(self, max_size: int = 256):
        from shared.cache import _MemoryBackend

        return _MemoryBackend(max_size=max_size)

    # -- get / set básico ---------------------------------------------------

    def test_get_miss_returns_none(self):
        c = self._make()
        assert c.get("nonexistent") is None

    def test_set_and_get_roundtrip(self):
        c = self._make()
        c.set("k", {"a": 1}, ttl=60)
        assert c.get("k") == {"a": 1}

    def test_set_overwrites_existing(self):
        c = self._make()
        c.set("k", "v1", ttl=60)
        c.set("k", "v2", ttl=60)
        assert c.get("k") == "v2"

    # -- TTL ----------------------------------------------------------------

    def test_expired_entry_returns_none(self):
        c = self._make()
        c.set("k", "v", ttl=0.001)
        time.sleep(0.05)
        assert c.get("k") is None

    def test_negative_ttl_means_no_expiry(self):
        c = self._make()
        c.set("k", "v", ttl=-1)
        assert c.get("k") == "v"

    def test_zero_ttl_means_no_expiry(self):
        c = self._make()
        c.set("k", "v", ttl=0)
        assert c.get("k") == "v"

    # -- LRU eviction -------------------------------------------------------

    def test_lru_evicts_oldest_when_full(self):
        c = self._make(max_size=3)
        c.set("a", 1, ttl=60)
        c.set("b", 2, ttl=60)
        c.set("c", 3, ttl=60)
        # "a" es el más antiguo, debe ser evictado
        c.set("d", 4, ttl=60)
        assert c.get("a") is None
        assert c.get("d") == 4

    def test_lru_access_refreshes_position(self):
        c = self._make(max_size=3)
        c.set("a", 1, ttl=60)
        c.set("b", 2, ttl=60)
        c.set("c", 3, ttl=60)
        # Acceder a "a" lo mueve al final, "b" es el más antiguo ahora
        c.get("a")
        c.set("d", 4, ttl=60)
        assert c.get("b") is None
        assert c.get("a") == 1

    def test_evicts_expired_before_lru(self):
        c = self._make(max_size=3)
        c.set("expired", "x", ttl=0.001)
        c.set("b", 2, ttl=60)
        c.set("c", 3, ttl=60)
        time.sleep(0.05)
        c.set("d", 4, ttl=60)
        assert c.get("b") == 2  # "b" no se evictó
        assert c.get("d") == 4

    # -- delete -------------------------------------------------------------

    def test_delete_existing_key(self):
        c = self._make()
        c.set("k", "v", ttl=60)
        c.delete("k")
        assert c.get("k") is None

    def test_delete_nonexistent_key_no_error(self):
        c = self._make()
        c.delete("nonexistent")  # no debe lanzar

    # -- clear --------------------------------------------------------------

    def test_clear_removes_all(self):
        c = self._make()
        c.set("a", 1, ttl=60)
        c.set("b", 2, ttl=60)
        c.clear()
        assert len(c) == 0
        assert c.get("a") is None

    # -- keys ---------------------------------------------------------------

    def test_keys_returns_all_non_expired(self):
        c = self._make()
        c.set("a", 1, ttl=60)
        c.set("b", 2, ttl=60)
        c.set("expired", 0, ttl=0.001)
        time.sleep(0.05)
        assert sorted(c.keys()) == ["a", "b"]

    def test_keys_with_prefix_pattern(self):
        c = self._make()
        c.set("api:x", 1, ttl=60)
        c.set("api:y", 2, ttl=60)
        c.set("dash:z", 3, ttl=60)
        assert sorted(c.keys("api:*")) == ["api:x", "api:y"]

    def test_keys_with_exact_pattern(self):
        c = self._make()
        c.set("a", 1, ttl=60)
        c.set("b", 2, ttl=60)
        assert c.keys("a") == ["a"]

    # -- __len__ ------------------------------------------------------------

    def test_len_counts_entries(self):
        c = self._make()
        assert len(c) == 0
        c.set("k", 1, ttl=60)
        assert len(c) == 1

    # -- thread safety ------------------------------------------------------

    def test_concurrent_access_no_crash(self):
        c = self._make(max_size=50)
        errors: list[Exception] = []

        def worker(start: int) -> None:
            try:
                for i in range(100):
                    c.set(f"k{start + i}", i, ttl=60)
                    c.get(f"k{start + i}")
                    c.delete(f"k{start}")
            except Exception as exc:
                errors.append(exc)

        threads = [threading.Thread(target=worker, args=(i * 100,)) for i in range(4)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()
        assert errors == []


# ---------------------------------------------------------------------------
# _RedisBackend (con mocks)
# ---------------------------------------------------------------------------


class TestRedisBackend:
    """Tests para _RedisBackend con Redis mockeado."""

    def _make_mocked(self):
        """Crea un _RedisBackend con redis.from_url mockeado."""
        mock_redis = MagicMock()
        mock_redis.ping.return_value = True

        with patch.dict("sys.modules", {"redis": MagicMock()}):
            import sys

            redis_mod = sys.modules["redis"]
            redis_mod.from_url.return_value = mock_redis

            from shared.cache import _RedisBackend

            backend = _RedisBackend.__new__(_RedisBackend)
            backend._ns = "test:"
            backend._r = mock_redis

        return backend, mock_redis

    def test_get_miss(self):
        b, mock_r = self._make_mocked()
        mock_r.get.return_value = None
        assert b.get("k") is None
        mock_r.get.assert_called_once_with("test:k")

    def test_get_hit(self):
        b, mock_r = self._make_mocked()
        mock_r.get.return_value = json.dumps({"a": 1})
        assert b.get("k") == {"a": 1}

    def test_get_redis_error_returns_none(self):
        b, mock_r = self._make_mocked()
        mock_r.get.side_effect = ConnectionError("down")
        assert b.get("k") is None

    def test_set_with_ttl(self):
        b, mock_r = self._make_mocked()
        b.set("k", {"x": 1}, ttl=30)
        mock_r.setex.assert_called_once()
        args = mock_r.setex.call_args
        assert args[0][0] == "test:k"
        assert args[0][1] == 30

    def test_set_without_ttl(self):
        b, mock_r = self._make_mocked()
        b.set("k", "v", ttl=-1)
        mock_r.set.assert_called_once()

    def test_set_redis_error_no_raise(self):
        b, mock_r = self._make_mocked()
        mock_r.setex.side_effect = ConnectionError("down")
        b.set("k", "v", ttl=10)  # no debe lanzar

    def test_delete(self):
        b, mock_r = self._make_mocked()
        b.delete("k")
        mock_r.delete.assert_called_once_with("test:k")

    def test_delete_error_no_raise(self):
        b, mock_r = self._make_mocked()
        mock_r.delete.side_effect = ConnectionError("down")
        b.delete("k")  # no debe lanzar

    def test_clear_scans_and_deletes(self):
        b, mock_r = self._make_mocked()
        # scan retorna (cursor, keys) — una iteración
        mock_r.scan.return_value = (0, ["test:a", "test:b"])
        b.clear()
        mock_r.delete.assert_called_once_with("test:a", "test:b")

    def test_clear_empty_no_delete(self):
        b, mock_r = self._make_mocked()
        mock_r.scan.return_value = (0, [])
        b.clear()
        mock_r.delete.assert_not_called()

    def test_clear_error_no_raise(self):
        b, mock_r = self._make_mocked()
        mock_r.scan.side_effect = ConnectionError("down")
        b.clear()  # no debe lanzar

    def test_keys_returns_stripped_namespace(self):
        b, mock_r = self._make_mocked()
        mock_r.scan.return_value = (0, ["test:x", "test:y"])
        assert sorted(b.keys()) == ["x", "y"]

    def test_keys_error_returns_empty(self):
        b, mock_r = self._make_mocked()
        mock_r.scan.side_effect = ConnectionError("down")
        assert b.keys() == []


# ---------------------------------------------------------------------------
# get_cache / _try_redis / reset_cache
# ---------------------------------------------------------------------------


class TestGetCache:
    """Tests para la factory singleton get_cache."""

    @staticmethod
    def _patch_no_redis():
        """Mock settings con REDIS_URL vacío para forzar MemoryBackend."""
        import config as config_mod

        mock_s = MagicMock()
        mock_s.REDIS_URL = ""
        return patch.object(config_mod, "settings", mock_s)

    def setup_method(self):
        mod = _fresh_import()
        self.mod = mod

    def test_returns_memory_backend_when_no_redis_url(self):
        with self._patch_no_redis():
            self.mod.reset_cache()
            c = self.mod.get_cache("test_ns")
            from shared.cache import _MemoryBackend

            assert isinstance(c, _MemoryBackend)

    def test_same_namespace_returns_same_instance(self):
        with self._patch_no_redis():
            self.mod.reset_cache()
            c1 = self.mod.get_cache("ns1")
            c2 = self.mod.get_cache("ns1")
            assert c1 is c2

    def test_different_namespace_returns_different_instance(self):
        with self._patch_no_redis():
            self.mod.reset_cache()
            c1 = self.mod.get_cache("ns1")
            c2 = self.mod.get_cache("ns2")
            assert c1 is not c2


class TestResetCache:
    """Tests para reset_cache."""

    @staticmethod
    def _patch_no_redis():
        import config as config_mod

        mock_s = MagicMock()
        mock_s.REDIS_URL = ""
        return patch.object(config_mod, "settings", mock_s)

    def setup_method(self):
        self.mod = _fresh_import()

    def test_reset_all(self):
        with self._patch_no_redis():
            c1 = self.mod.get_cache("a")
            self.mod.reset_cache()
            c2 = self.mod.get_cache("a")
            assert c1 is not c2

    def test_reset_single_namespace(self):
        with self._patch_no_redis():
            c_a = self.mod.get_cache("a")
            c_b = self.mod.get_cache("b")
            self.mod.reset_cache("a")
            c_a2 = self.mod.get_cache("a")
            c_b2 = self.mod.get_cache("b")
            assert c_a is not c_a2
            assert c_b is c_b2


class TestTryRedis:
    """Tests para _try_redis — lógica de fallback y fail-fast en prod."""

    @staticmethod
    def _patch_settings(redis_url: str = ""):
        """Mock ``from config import settings`` dentro de ``_try_redis``.

        ``_try_redis`` hace ``from config import settings`` (el singleton real),
        por lo que necesitamos parchear el atributo ``settings`` del módulo
        ``config`` directamente.
        """
        import config as config_mod

        mock_s = MagicMock()
        mock_s.REDIS_URL = redis_url
        return patch.object(config_mod, "settings", mock_s)

    def test_no_redis_url_returns_memory(self):
        mod = _fresh_import()
        with self._patch_settings(redis_url=""):
            result = mod._try_redis("ns")
            from shared.cache import _MemoryBackend

            assert isinstance(result, _MemoryBackend)

    def test_redis_connection_failure_returns_memory_in_dev(self):
        mod = _fresh_import()
        with (
            self._patch_settings(redis_url="redis://bad:6379/0"),
            patch("shared.cache._RedisBackend", side_effect=ConnectionError("down")),
            patch.dict("os.environ", {"ENV": "dev"}, clear=False),
        ):
            result = mod._try_redis("ns")
            from shared.cache import _MemoryBackend

            assert isinstance(result, _MemoryBackend)

    def test_redis_connection_failure_returns_memory_even_in_prod(self):
        mod = _fresh_import()
        with (
            self._patch_settings(redis_url="redis://bad:6379/0"),
            patch("shared.cache._RedisBackend", side_effect=ConnectionError("down")),
            patch.dict("os.environ", {"ENV": "prod"}, clear=False),
        ):
            result = mod._try_redis("ns")
            from shared.cache import _MemoryBackend

            assert isinstance(result, _MemoryBackend)

    def test_settings_import_failure_returns_memory_in_dev(self):
        mod = _fresh_import()
        with (
            patch.dict("os.environ", {"ENV": "dev"}, clear=False),
            patch.dict("sys.modules", {"config": None}),
        ):
            result = mod._try_redis("ns")
            from shared.cache import _MemoryBackend

            assert isinstance(result, _MemoryBackend)


class TestInvalidateUserScoped:
    """Invalidación dirigida cuando el propio usuario cambia el resultado."""

    def test_borra_solo_las_entradas_de_ese_usuario_y_esa_funcion(self):
        """Descartar una señal no puede tirar la caché de los demás.

        El Radar sirve el ranking cacheado 300 s y ya excluye los descartes del
        usuario; sin esta invalidación, la señal descartada seguiría en pantalla
        hasta que expirase el TTL y el hueco no lo ocuparía la siguiente.
        """
        mod = _fresh_import()

        @mod.cache_response(ttl=60, namespace="invalidate-ns")
        def scoring(*, limit, _user):
            return {"limit": limit, "principal": _user["user_key"]}

        @mod.cache_response(ttl=60, namespace="invalidate-ns")
        def otra_funcion(*, _user):
            return {"principal": _user["user_key"]}

        async def invoke():
            await scoring(limit=24, _user={"user_key": "user-a"})
            await scoring(limit=50, _user={"user_key": "user-a"})
            await scoring(limit=24, _user={"user_key": "user-b"})
            await otra_funcion(_user={"user_key": "user-a"})

        asyncio.run(invoke())
        cache = mod.get_cache("invalidate-ns")
        assert len(cache.keys("*")) == 4

        borradas = mod.invalidate_user_scoped("invalidate-ns", "scoring", "user-a")

        assert borradas == 2
        restantes = cache.keys("*")
        assert len(restantes) == 2
        assert all(
            '"principal":"user-a"' not in k or not k.startswith("scoring|") for k in restantes
        )

    def test_invalidar_a_un_usuario_no_toca_a_otro_que_empieza_igual(self):
        """``u1`` no es un prefijo de la marca de ``u10``: la marca lleva sus comillas."""
        mod = _fresh_import()

        @mod.cache_response(ttl=60, namespace="invalidate-prefijo")
        def scoring(*, _user):
            return {"principal": _user["user_key"]}

        async def invoke():
            await scoring(_user={"user_key": "u1"})
            await scoring(_user={"user_key": "u10"})

        asyncio.run(invoke())

        assert mod.invalidate_user_scoped("invalidate-prefijo", "scoring", "u1") == 1
        (restante,) = mod.get_cache("invalidate-prefijo").keys("*")
        assert '"principal":"u10"' in restante

    def test_un_parametro_no_puede_hacerse_pasar_por_un_usuario(self):
        """El texto de la marca dentro de un parámetro va escapado: no casa."""
        mod = _fresh_import()

        @mod.cache_response(ttl=60, namespace="invalidate-suplantacion", user_scoped=False)
        def scoring(*, q, _user):
            return {"q": q}

        async def invoke():
            await scoring(q='x","principal":"victima', _user={"user_key": "atacante"})

        asyncio.run(invoke())

        assert mod.invalidate_user_scoped("invalidate-suplantacion", "scoring", "victima") == 0

    def test_no_falla_cuando_no_hay_nada_que_invalidar(self):
        mod = _fresh_import()

        assert mod.invalidate_user_scoped("invalidate-vacio", "scoring", "user-a") == 0

    def test_organization_invalidation_reaches_all_members_only_in_that_organization(self):
        mod = _fresh_import()

        @mod.cache_response(ttl=60, namespace="invalidate-org")
        def scoring(*, _user):
            return dict(_user)

        async def invoke():
            await scoring(_user={"user_key": "user-a", "organization_id": 7})
            await scoring(_user={"user_key": "user-b", "organization_id": 7})
            await scoring(_user={"user_key": "user-c", "organization_id": 8})

        asyncio.run(invoke())
        assert mod.invalidate_organization_scoped("invalidate-org", "scoring", 7) == 2
        restantes = mod.get_cache("invalidate-org").keys("*")
        assert len(restantes) == 1
        assert '"organization":"8"' in restantes[0]


class TestCacheResponseIdentity:
    """Las respuestas personalizadas nunca comparten entrada entre usuarios."""

    def test_private_principal_is_part_of_cache_key(self):
        mod = _fresh_import()
        calls = 0

        @mod.cache_response(ttl=60, namespace="identity-regression")
        def personalized(*, _user):
            nonlocal calls
            calls += 1
            return {"principal": _user["user_key"], "call": calls}

        async def invoke():
            first = await personalized(_user={"user_key": "user-a"})
            second = await personalized(_user={"user_key": "user-b"})
            repeat = await personalized(_user={"user_key": "user-a"})
            return first, second, repeat

        first, second, repeat = asyncio.run(invoke())
        assert first["principal"] == "user-a"
        assert second["principal"] == "user-b"
        assert first == repeat
        assert calls == 2

    def test_same_user_does_not_share_cache_between_organizations(self):
        mod = _fresh_import()
        calls = 0

        @mod.cache_response(ttl=60, namespace="organization-regression")
        def personalized(*, _user):
            nonlocal calls
            calls += 1
            return {"organization_id": _user["organization_id"], "call": calls}

        async def invoke():
            personal = await personalized(_user={"user_key": "user-a", "organization_id": 1})
            team = await personalized(_user={"user_key": "user-a", "organization_id": 2})
            repeat = await personalized(_user={"user_key": "user-a", "organization_id": 1})
            return personal, team, repeat

        personal, team, repeat = asyncio.run(invoke())
        assert personal["organization_id"] == 1
        assert team["organization_id"] == 2
        assert personal == repeat
        assert calls == 2

    def test_user_scoped_false_comparte_entrada_entre_identidades(self):
        """Los datos globales se calculan una vez para todos los usuarios.

        La analítica agregada no depende de quién pregunta, pero la clave
        llevaba el ``user_key`` igual: N usuarios pagaban N veces la misma
        agregación de decenas de segundos y ninguno aprovechaba el caché del
        anterior. Con ``user_scoped=False`` la identidad sale de la clave.
        """
        mod = _fresh_import()
        calls = 0

        @mod.cache_response(ttl=60, namespace="global-regression", user_scoped=False)
        def global_data(*, _user):
            nonlocal calls
            calls += 1
            return {"call": calls}

        async def invoke():
            first = await global_data(_user={"user_key": "user-a"})
            second = await global_data(_user={"user_key": "user-b"})
            return first, second

        first, second = asyncio.run(invoke())
        assert first == second
        assert calls == 1, "la segunda identidad debe reutilizar el cálculo de la primera"

    def test_user_scoped_false_no_mezcla_parametros_distintos(self):
        """Compartir entre identidades no significa compartir entre consultas."""
        mod = _fresh_import()

        @mod.cache_response(ttl=60, namespace="global-params", user_scoped=False)
        def global_data(*, ccaa, _user):
            return {"ccaa": ccaa}

        async def invoke():
            madrid = await global_data(ccaa="Madrid", _user={"user_key": "user-a"})
            galicia = await global_data(ccaa="Galicia", _user={"user_key": "user-b"})
            return madrid, galicia

        madrid, galicia = asyncio.run(invoke())
        assert madrid["ccaa"] == "Madrid"
        assert galicia["ccaa"] == "Galicia"

    def test_un_valor_con_separadores_no_ocupa_la_entrada_de_otra_consulta(self):
        """``?ccaa=Madrid|cpv:72`` fabricaba la clave de ``?ccaa=Madrid&cpv=72``.

        Con la clave ``k:v`` unida por ``|``, cualquier usuario autenticado
        podía sembrar una respuesta en la entrada de otra consulta, y en un
        endpoint ``user_scoped=False`` esa respuesta la recibían todos durante
        el TTL. La clave es JSON canónico: los separadores de un valor van
        dentro de su cadena y no pueden partirla.
        """
        mod = _fresh_import()
        calls = 0

        @mod.cache_response(ttl=60, namespace="global-colision", user_scoped=False)
        def global_data(*, ccaa, cpv=None, _user):
            nonlocal calls
            calls += 1
            return {"ccaa": ccaa, "cpv": cpv}

        async def invoke():
            sembrada = await global_data(ccaa="Madrid|cpv:72", _user={"user_key": "atacante"})
            legitima = await global_data(ccaa="Madrid", cpv="72", _user={"user_key": "victima"})
            return sembrada, legitima

        sembrada, legitima = asyncio.run(invoke())

        assert legitima == {"ccaa": "Madrid", "cpv": "72"}, "servida la respuesta sembrada"
        assert sembrada == {"ccaa": "Madrid|cpv:72", "cpv": None}
        assert calls == 2
        assert len(mod.get_cache("global-colision").keys("*")) == 2

    def test_la_clave_distingue_ninguno_de_los_separadores_clasicos(self):
        """Pares que con la clave antigua colisionaban: aquí dan claves distintas."""
        from shared.cache import _clave_de_peticion

        pares = [
            ({"ccaa": "Madrid|cpv:72"}, {"ccaa": "Madrid", "cpv": "72"}),
            ({"a": "1|b:2"}, {"a": "1", "b": "2"}),
            ({"q": 'x","y":"z'}, {"q": "x", "y": "z"}),
            ({"q": "None"}, {"q": None}),
        ]
        for uno, otro in pares:
            assert _clave_de_peticion(
                "f", uno, user_scoped=False, huella="h"
            ) != _clave_de_peticion("f", otro, user_scoped=False, huella="h"), (uno, otro)

    def test_un_dto_distinto_no_sirve_las_entradas_del_anterior(self):
        """Tras un despliegue que cambia el DTO, lo guardado antes no se sirve.

        Antes el acierto pasaba por la validación de FastAPI contra el
        ``response_model``; ahora el cuerpo sale tal cual, así que la forma de
        la respuesta va en la clave.
        """
        from pydantic import BaseModel

        mod = _fresh_import()

        class Antes(BaseModel):
            total: int

        class Despues(BaseModel):
            total: int
            nuevo: str = "x"

        llamadas: list[str] = []

        def _version(modelo, etiqueta):
            def resumen(*, _user):
                llamadas.append(etiqueta)
                return modelo(total=1)

            # Anotación real y no texto: con `from __future__ import annotations`
            # un tipo local no se podría resolver, y ahí la huella cae a un
            # valor fijo (el caso de un handler sin tipo). Las rutas de verdad
            # anotan clases de módulo: ver tests/test_cache_response_http.py.
            resumen.__annotations__ = {"return": modelo}
            return mod.cache_response(ttl=60, namespace="huella-dto", user_scoped=False)(resumen)

        async def invoke():
            await _version(Antes, "antes")(_user={})
            await _version(Despues, "despues")(_user={})
            await _version(Despues, "despues")(_user={})

        asyncio.run(invoke())

        assert llamadas == ["antes", "despues"], "el despliegue nuevo calcula una vez y reutiliza"
        claves = mod.get_cache("huella-dto").keys("resumen|*")
        assert len(claves) == 2


# ---------------------------------------------------------------------------
# single_flight
# ---------------------------------------------------------------------------


class TestSingleFlight:
    """El lock por clave que usan los handlers con caché propio."""

    def test_deduplica_corrutinas_concurrentes(self):
        """N corrutinas simultáneas sobre la misma clave calculan una sola vez.

        Es la garantía que justifica el helper: sin él, las N que llegan con el
        caché frío fallan la comprobación previa a la vez y las N ejecutan la
        consulta cara. El ``await`` dentro del bloque es lo que da a las otras
        cuatro la oportunidad de entrar si el lock no funcionara.
        """
        mod = _fresh_import()
        ejecuciones = 0
        store: dict[str, str] = {}

        async def calcular():
            nonlocal ejecuciones
            if "k" in store:
                return store["k"]
            async with mod.single_flight("single-flight:dedup"):
                if "k" in store:
                    return store["k"]
                ejecuciones += 1
                await asyncio.sleep(0.02)
                store["k"] = "valor"
                return store["k"]

        async def invoke():
            return await asyncio.gather(*(calcular() for _ in range(5)))

        resultados = asyncio.run(invoke())
        assert resultados == ["valor"] * 5
        assert ejecuciones == 1

    def test_claves_distintas_no_se_bloquean(self):
        """Dos claves distintas usan locks distintos y progresan en paralelo."""
        mod = _fresh_import()
        ejecuciones = 0

        async def calcular(clave: str):
            nonlocal ejecuciones
            async with mod.single_flight(clave):
                ejecuciones += 1
                await asyncio.sleep(0.02)
                return clave

        async def invoke():
            return await asyncio.gather(
                calcular("single-flight:a"),
                calcular("single-flight:b"),
            )

        resultados = asyncio.run(invoke())
        assert sorted(resultados) == ["single-flight:a", "single-flight:b"]
        assert ejecuciones == 2

    def test_libera_el_lock_si_el_bloque_lanza(self):
        """Una excepción dentro del bloque no deja la clave bloqueada."""
        mod = _fresh_import()

        async def invoke():
            try:
                async with mod.single_flight("single-flight:error"):
                    raise RuntimeError("boom")
            except RuntimeError:
                pass
            # Si el lock hubiera quedado tomado, este bloque colgaría.
            async with mod.single_flight("single-flight:error"):
                return "ok"

        async def con_limite():
            # `wait_for` para que un lock filtrado falle el test en vez de
            # colgar el job de CI.
            return await asyncio.wait_for(invoke(), timeout=5)

        assert asyncio.run(con_limite()) == "ok"


# ---------------------------------------------------------------------------
# Redis: timeouts, cortacircuitos y formato de las respuestas cacheadas
# ---------------------------------------------------------------------------


class _RedisFalso:
    """Doble del cliente redis-py: un dict, y la opción de fallar o contar."""

    def __init__(self) -> None:
        self.datos: dict[str, str] = {}
        self.llamadas = 0
        self.error: Exception | None = None

    def _uso(self) -> None:
        self.llamadas += 1
        if self.error is not None:
            raise self.error

    def get(self, key: str) -> str | None:
        self._uso()
        return self.datos.get(key)

    def setex(self, key: str, ttl: int, value: str) -> None:
        self._uso()
        assert ttl >= 1, "Redis rechaza un SETEX con plazo 0"
        self.datos[key] = value

    def set(self, key: str, value: str) -> None:
        self._uso()
        self.datos[key] = value

    def delete(self, *keys: str) -> None:
        self._uso()
        for key in keys:
            self.datos.pop(key, None)

    def scan(self, cursor: int = 0, match: str = "*", count: int = 100) -> tuple[int, list[str]]:
        self._uso()
        prefijo = match.rstrip("*")
        return 0, [k for k in self.datos if k.startswith(prefijo)]


def _backend_con(cliente: _RedisFalso):
    from shared.cache import _RedisBackend

    backend = _RedisBackend.__new__(_RedisBackend)
    backend._ns = "ns:"
    backend._r = cliente
    return backend


class TestRedisTimeoutsYCortacircuitos:
    """Un Redis colgado no puede costar un timeout por petición, ni parar el proceso."""

    def test_el_cliente_se_crea_con_timeouts_y_un_solo_reintento(self):
        """Sin ``socket_timeout`` un Redis que no responde bloqueaba para siempre."""
        import redis
        from redis.retry import Retry

        import shared.cache as mod

        capturado: dict = {}

        class _Cliente:
            def ping(self):
                return True

        def _from_url(url, **kwargs):
            capturado.update(kwargs)
            return _Cliente()

        with patch.object(redis.Redis, "from_url", side_effect=_from_url):
            mod._RedisBackend(
                "redis://localhost:6379/0",
                namespace="x",
                password=_CLAVE_REDIS_FALSA,
            )

        assert capturado["password"] == _CLAVE_REDIS_FALSA
        assert capturado["socket_timeout"] == mod._REDIS_SOCKET_TIMEOUT_S <= 1.0
        assert capturado["socket_connect_timeout"] == mod._REDIS_CONNECT_TIMEOUT_S
        retry = capturado["retry"]
        assert isinstance(retry, Retry)
        # Un reintento como mucho: el tiempo máximo de una operación queda acotado.
        # (`get_retries` en redis-py reciente; `_retries` en la 5.x.)
        reintentos = retry.get_retries() if hasattr(retry, "get_retries") else retry._retries
        assert reintentos == 1

    def test_try_redis_pasa_redis_password(self):
        """Como ``llm/budget.py`` y el rate limiter: sin la contraseña, contra un
        Redis con ``requirepass`` el PING fallaba y el namespace se quedaba en
        memoria para siempre."""
        from pydantic import SecretStr

        import config as config_mod

        mod = _fresh_import()
        mock_s = MagicMock()
        mock_s.REDIS_URL = "redis://redis:6379/0"
        mock_s.REDIS_PASSWORD = SecretStr(_CLAVE_REDIS_FALSA)
        with (
            patch.object(config_mod, "settings", mock_s),
            patch("shared.cache._RedisBackend") as backend,
        ):
            mod._try_redis("ns")

        backend.assert_called_once_with(
            "redis://redis:6379/0", namespace="ns", password=_CLAVE_REDIS_FALSA
        )

    def test_sin_redis_password_no_se_manda_ninguna(self):
        from pydantic import SecretStr

        import shared.cache as mod

        assert mod._contrasena_redis(SimpleNamespace(REDIS_PASSWORD=SecretStr(""))) is None
        assert mod._contrasena_redis(SimpleNamespace()) is None
        assert mod._contrasena_redis(MagicMock()) is None

    def test_tras_un_fallo_se_salta_redis_y_se_usa_la_memoria(self):
        cliente = _RedisFalso()
        backend = _backend_con(cliente)
        cliente.error = TimeoutError("redis colgado")

        backend.set("k", {"v": 1}, ttl=60)  # falla: abre el circuito y guarda en memoria
        llamadas_tras_el_fallo = cliente.llamadas

        assert backend.get("k") == {"v": 1}, "el respaldo en memoria sirve lo guardado"
        backend.set("otra", 2, ttl=60)
        assert backend.get("otra") == 2
        assert sorted(backend.keys("*")) == ["k", "otra"]
        assert cliente.llamadas == llamadas_tras_el_fallo, (
            "con el circuito abierto no se toca Redis"
        )

    def test_pasado_el_plazo_vuelve_a_probar_redis_y_vacia_el_respaldo(self):
        cliente = _RedisFalso()
        backend = _backend_con(cliente)
        cliente.error = ConnectionError("caído")
        backend.set("k", "durante la caída", ttl=60)

        cliente.error = None
        backend._saltar_hasta = 0.0  # plazo cumplido
        assert backend.get("k") is None, "Redis responde: lo del respaldo no se sirve"
        assert cliente.llamadas >= 2
        # Recuperado Redis, el respaldo se vacía: sus entradas eran de la caída.
        assert backend._memoria().keys("*") == []

    def test_el_plazo_del_cortacircuitos_es_corto(self):
        import shared.cache as mod

        cliente = _RedisFalso()
        backend = _backend_con(cliente)
        cliente.error = ConnectionError("caído")
        antes = time.monotonic()
        backend.get("k")

        assert 0 < backend._saltar_hasta - antes <= mod._REDIS_BREAKER_S + 1
        assert mod._REDIS_BREAKER_S <= 60

    def test_un_valor_ilegible_no_abre_el_circuito(self):
        cliente = _RedisFalso()
        backend = _backend_con(cliente)
        cliente.datos["ns:k"] = "{no es json"

        assert backend.get("k") is None
        assert backend._redis_activo()

    def test_ttl_menor_de_un_segundo_no_manda_setex_0(self):
        cliente = _RedisFalso()
        backend = _backend_con(cliente)

        backend.set("k", 1, ttl=0.5)

        assert backend._redis_activo(), "SETEX 0 es un error de Redis y abriría el circuito"
        assert "ns:k" in cliente.datos


class TestRespuestaCacheadaEnRedis:
    """``cache_response`` guarda en Redis el JSON ya serializado, sin reparsearlo."""

    def test_ida_y_vuelta(self):
        from shared.cache import _RespuestaCacheada

        cliente = _RedisFalso()
        backend = _backend_con(cliente)
        entrada = _RespuestaCacheada(cuerpo='{"a":"ñ"}'.encode(), etag='W/"abc"')

        backend.set_respuesta("k", entrada, ttl=60)

        assert cliente.datos["ns:k"].startswith("tf-respuesta-v1\n")
        assert backend.get_respuesta("k") == entrada

    def test_una_entrada_del_formato_anterior_es_un_fallo(self):
        """Lo que escribió la versión anterior (un dict en JSON) se recalcula."""
        cliente = _RedisFalso()
        backend = _backend_con(cliente)
        cliente.datos["ns:k"] = json.dumps({"total": 3})

        assert backend.get_respuesta("k") is None

    def test_con_el_circuito_abierto_la_respuesta_va_a_memoria(self):
        from shared.cache import _RespuestaCacheada

        cliente = _RedisFalso()
        backend = _backend_con(cliente)
        cliente.error = TimeoutError("colgado")
        entrada = _RespuestaCacheada(cuerpo=b"{}", etag='W/"x"')

        backend.set_respuesta("k", entrada, ttl=60)

        assert backend.get_respuesta("k") == entrada

    def test_las_variantes_async_no_hacen_la_e_s_en_el_loop(self):
        from shared.cache import _RespuestaCacheada

        hilos: list[int] = []
        cliente = _RedisFalso()
        get_original = cliente.get

        def _get_espia(key):
            hilos.append(threading.get_ident())
            return get_original(key)

        cliente.get = _get_espia
        backend = _backend_con(cliente)
        backend.set_respuesta("k", _RespuestaCacheada(cuerpo=b"{}", etag='W/"x"'), ttl=60)

        async def _leer():
            entrada = await backend.aget_respuesta("k")
            valor = await backend.aget("k")
            return entrada, valor, threading.get_ident()

        entrada, _valor, hilo_del_loop = asyncio.run(_leer())

        assert entrada is not None
        assert hilos
        assert all(h != hilo_del_loop for h in hilos)

    def test_cache_response_con_redis_no_llama_al_cliente_desde_el_loop(self):
        """El wrapper de extremo a extremo con un backend Redis simulado."""
        from starlette.responses import Response

        import shared.cache as mod

        mod.reset_cache()
        hilos: list[int] = []
        cliente = _RedisFalso()
        for nombre in ("get", "setex"):
            original = getattr(cliente, nombre)

            def _espia(*args, _original=original, **kwargs):
                hilos.append(threading.get_ident())
                return _original(*args, **kwargs)

            setattr(cliente, nombre, _espia)
        mod._instances["redis-e2e"] = _backend_con(cliente)

        @mod.cache_response(ttl=60, namespace="redis-e2e")
        def handler(*, _user):
            return {"ok": True}

        async def _dos():
            primera = await handler(_user={}, _cache_response_temporal=Response())
            segunda = await handler(_user={}, _cache_response_temporal=Response())
            return primera, segunda, threading.get_ident()

        try:
            primera, segunda, hilo_del_loop = asyncio.run(_dos())
        finally:
            mod.reset_cache()

        assert primera.body == segunda.body == b'{"ok":true}'
        assert segunda.headers["etag"] == primera.headers["etag"]
        assert hilos
        assert all(h != hilo_del_loop for h in hilos)
