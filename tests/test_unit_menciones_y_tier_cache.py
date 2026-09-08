"""Dos piezas que fallan hacia el lado seguro, y por eso nadie las ve fallar.

`_resolver_menciones` (C6.2) y `_tier_limit` (C2.3) comparten forma: las dos
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
        from api.middleware import _tier_limit

        llamadas: list[str] = []

        def _lookup(key_hash: str) -> int:
            llamadas.append(key_hash)
            return 120

        monkeypatch.setattr(repo, "tier_limit_por_hash", _lookup)

        assert _tier_limit("h1") == 120
        assert _tier_limit("h1") == 120
        assert llamadas == ["h1"], "la segunda llamada tenía que salir de la caché"

    def test_un_fallo_de_bd_no_tumba_el_rate_limiter(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Errar hacia el default deja la API respondiendo; propagar la
        excepción la dejaría devolviendo 500 a todo el mundo."""
        import db.repositories.api_keys as repo
        from api.middleware import _tier_limit

        def _explota(key_hash: str) -> int:
            raise RuntimeError("BD caída")

        monkeypatch.setattr(repo, "tier_limit_por_hash", _explota)

        assert _tier_limit("h2") is None

    def test_un_fallo_no_se_cachea(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Si se cacheara, una caída momentánea dejaría la clave sin su tier
        durante todo el TTL."""
        import db.repositories.api_keys as repo
        from api.middleware import _tier_limit

        estado = {"falla": True}

        def _intermitente(key_hash: str) -> int:
            if estado["falla"]:
                raise RuntimeError("BD caída")
            return 300

        monkeypatch.setattr(repo, "tier_limit_por_hash", _intermitente)

        assert _tier_limit("h3") is None
        estado["falla"] = False
        assert _tier_limit("h3") == 300

    def test_una_clave_sin_tope_propio_tambien_se_cachea(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """`None` es una respuesta, no una ausencia: sin cachearla, cada
        petición de una clave sin tier consultaría la BD."""
        import db.repositories.api_keys as repo
        from api.middleware import _tier_limit

        llamadas: list[str] = []
        monkeypatch.setattr(repo, "tier_limit_por_hash", lambda h: llamadas.append(h) or None)

        assert _tier_limit("h4") is None
        assert _tier_limit("h4") is None
        assert llamadas == ["h4"]
