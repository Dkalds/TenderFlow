"""Dos piezas que fallan hacia el lado seguro, y por eso nadie las ve fallar.

`_resolver_menciones` (C6.2) y `_tier_de_clave` (C2.3) comparten forma: las dos
capturan una excepción amplia y devuelven un valor neutro. Eso es correcto —un
fallo al resolver una mención no puede perder el comentario, y un fallo de BD no
puede tumbar el rate limiter— pero también significa que si la rama buena se
rompiera, **el sistema seguiría respondiendo** y nadie se enteraría.

Un `except Exception` sin test es una rama que solo se ejecuta el día que algo
va mal, que es el peor día para descubrir que además estaba rota.
"""

from __future__ import annotations

from typing import Any, ClassVar

import pytest


class TestResolucionDeMenciones:
    """C6.2 — se guardan ids, y solo de miembros activos."""

    MIEMBROS: ClassVar[list[dict[str, Any]]] = [
        {"user_id": 1, "display_name": "Ana Ruiz", "status": "active"},
        {"user_id": 2, "display_name": "Marta Sanz", "status": "revoked"},
        {"user_id": 3, "display_name": "Luis Gomez", "status": "active"},
    ]

    def _montar(
        self, monkeypatch: pytest.MonkeyPatch, miembros: Any
    ) -> tuple[Any, list[tuple[int, list[int]]]]:
        import services.pursuit_comments as mod

        guardadas: list[tuple[int, list[int]]] = []

        class _Orgs:
            def list_members(self, organization_id: int) -> Any:
                if isinstance(miembros, Exception):
                    raise miembros
                return miembros

        class _Repo:
            def guardar_menciones(self, comment_id: int, user_ids: list[int]) -> int:
                guardadas.append((comment_id, user_ids))
                return len(user_ids)

        monkeypatch.setattr(mod, "_organizations", _Orgs())
        monkeypatch.setattr(mod, "_repo", _Repo())
        return mod, guardadas

    def test_a_quien_ya_salio_del_equipo_no_se_le_menciona(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Notificaría a una cuenta que no debería recibirlo."""
        mod, guardadas = self._montar(monkeypatch, self.MIEMBROS)

        assert mod._resolver_menciones(7, 1, "aviso a @{Marta Sanz}") == []
        assert guardadas == []

    def test_un_miembro_activo_si_se_menciona_y_se_persiste(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        mod, guardadas = self._montar(monkeypatch, self.MIEMBROS)

        assert mod._resolver_menciones(7, 1, "@{Ana Ruiz} ¿lo miras?") == [1]
        assert guardadas == [(1, [1])]

    def test_sin_status_se_asume_activo(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """`list_members` no siempre lo trae; tratarlo como inactivo silenciaría
        menciones legítimas."""
        mod, _ = self._montar(monkeypatch, [{"user_id": 9, "display_name": "Sin Estado"}])

        assert mod._resolver_menciones(7, 1, "@{Sin Estado}") == [9]

    def test_sin_display_name_se_cae_al_email(self, monkeypatch: pytest.MonkeyPatch) -> None:
        mod, _ = self._montar(
            monkeypatch, [{"user_id": 9, "display_name": None, "email": "ana@ejemplo.es"}]
        )

        assert mod._resolver_menciones(7, 1, "@{ana@ejemplo.es}") == [9]

    def test_un_fallo_al_pedir_los_miembros_no_pierde_el_comentario(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """El comentario ya está escrito: perderlo por no poder resolver una
        mención sería el peor intercambio posible."""
        mod, guardadas = self._montar(monkeypatch, RuntimeError("BD caída"))

        assert mod._resolver_menciones(7, 1, "@{Ana Ruiz}") == []
        assert guardadas == []

    def test_un_nombre_ambiguo_no_resuelve_a_nadie_y_no_se_persiste(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Elegir una de las dos «Ana» notificaría a la equivocada."""
        mod, guardadas = self._montar(
            monkeypatch,
            [
                {"user_id": 1, "display_name": "Ana Ruiz", "status": "active"},
                {"user_id": 4, "display_name": "Ana Prieto", "status": "active"},
            ],
        )

        assert mod._resolver_menciones(7, 1, "@Ana ¿lo miras?") == []
        assert guardadas == []


class TestCacheDeTier:
    """C2.3 — el tier de la clave, cacheado, sin poder tumbar el limitador."""

    @pytest.fixture(autouse=True)
    def _limpia(self) -> Any:
        from api.middleware import reset_tier_cache

        reset_tier_cache()
        yield
        reset_tier_cache()

    def test_el_limite_se_consulta_una_vez_y_se_cachea(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        import db.repositories.api_keys as repo
        from api.middleware import _tier_de_clave

        llamadas: list[str] = []

        def _lookup(key_hash: str) -> tuple[bool, int | None]:
            llamadas.append(key_hash)
            return True, 120

        monkeypatch.setattr(repo, "tier_de_clave_por_hash", _lookup)

        assert _tier_de_clave("h1") == (True, 120)
        assert _tier_de_clave("h1") == (True, 120)
        assert llamadas == ["h1"], "la segunda llamada tenía que salir de la caché"

    def test_un_fallo_de_bd_no_tumba_el_rate_limiter(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """No se propaga (la API seguiría respondiendo) y la clave no estrena
        cubo propio: sin poder comprobarla, se cuenta por IP."""
        import db.repositories.api_keys as repo
        from api.middleware import _tier_de_clave

        def _explota(key_hash: str) -> tuple[bool, int | None]:
            raise RuntimeError("BD caída")

        monkeypatch.setattr(repo, "tier_de_clave_por_hash", _explota)

        assert _tier_de_clave("h2") == (False, None)

    def test_un_fallo_se_recuerda_poco_y_luego_se_vuelve_a_preguntar(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Con la BD saturada cada clave nueva esperaba su turno al pool dentro de
        los hilos de la cuota; recordar el fallo unos segundos lo evita, y el TTL
        corto deja a la clave legítima recuperar su tier en cuanto la BD vuelve."""
        import api.middleware as mw
        import db.repositories.api_keys as repo

        estado = {"falla": True, "ahora": 1_000.0}
        llamadas: list[str] = []

        def _intermitente(key_hash: str) -> tuple[bool, int | None]:
            llamadas.append(key_hash)
            if estado["falla"]:
                raise RuntimeError("BD caída")
            return True, 300

        monkeypatch.setattr(repo, "tier_de_clave_por_hash", _intermitente)
        monkeypatch.setattr(mw.time, "time", lambda: estado["ahora"])

        assert mw._tier_de_clave("h3") == (False, None)
        assert mw._tier_de_clave("h3") == (False, None)
        assert llamadas == ["h3"], "el segundo fallo tenía que salir de la caché"

        estado["falla"] = False
        estado["ahora"] += mw._TIER_FALLO_TTL_S + 0.1
        assert mw._tier_de_clave("h3") == (True, 300)

    def test_una_clave_sin_tope_propio_tambien_se_cachea(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """`None` es una respuesta, no una ausencia: sin cachearla, cada
        petición de una clave sin tier consultaría la BD."""
        import db.repositories.api_keys as repo
        from api.middleware import _tier_de_clave

        llamadas: list[str] = []
        monkeypatch.setattr(
            repo, "tier_de_clave_por_hash", lambda h: llamadas.append(h) or (True, None)
        )

        assert _tier_de_clave("h4") == (True, None)
        assert _tier_de_clave("h4") == (True, None)
        assert llamadas == ["h4"]

    def test_una_clave_inventada_tambien_se_cachea(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Quien repite una clave inexistente no vuelve a costar una lectura."""
        import db.repositories.api_keys as repo
        from api.middleware import _tier_de_clave

        llamadas: list[str] = []
        monkeypatch.setattr(
            repo, "tier_de_clave_por_hash", lambda h: llamadas.append(h) or (False, None)
        )

        assert _tier_de_clave("falsa") == (False, None)
        assert _tier_de_clave("falsa") == (False, None)
        assert llamadas == ["falsa"]

    def test_la_cache_tiene_tope_y_expulsa_la_mas_antigua(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Rotando claves el diccionario crecía sin tope durante el TTL."""
        import api.middleware as mw
        import db.repositories.api_keys as repo

        monkeypatch.setattr(repo, "tier_de_clave_por_hash", lambda h: (False, None))
        monkeypatch.setattr(mw, "_TIER_CACHE_MAX", 3)

        for i in range(10):
            mw._tier_de_clave(f"k{i}")

        assert list(mw._tier_cache) == ["k7", "k8", "k9"]
