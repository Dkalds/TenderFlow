"""Go/no-go: permisos y forma de salida, ejecutados (C6.4, D30).

`test_c6_captura.py` cubre bien `go_no_go_template` —que es aritmética pura— y
deja sin ejecutar el módulo que decide **quién puede qué** y arma la respuesta.
Ahí es donde vive la regla que el ítem pide: puntuar no es decidir, pero mover
los pesos sí es gobernar cómo decide el equipo.
"""

from __future__ import annotations

from typing import Any

import pytest


class _RepoDoble:
    def __init__(
        self,
        *,
        pesos: dict[str, float] | None = None,
        puntuaciones: list[dict[str, Any]] | None = None,
        puntuar: bool = True,
    ) -> None:
        self._pesos = pesos or {}
        self._puntuaciones = puntuaciones or []
        self._puntuar = puntuar
        self.guardados: list[tuple[int, dict[str, float]]] = []
        self.puntuadas: list[dict[str, Any]] = []

    def pesos(self, organization_id: int) -> dict[str, float]:
        return self._pesos

    def guardar_pesos(self, organization_id: int, pesos: dict[str, float]) -> None:
        self.guardados.append((organization_id, pesos))

    def puntuaciones(self, organization_id: int, pursuit_id: int) -> list[dict[str, Any]]:
        return self._puntuaciones

    def puntuar(self, **kwargs: Any) -> bool:
        self.puntuadas.append(kwargs)
        return self._puntuar


class _PursuitsDoble:
    def __init__(self, pursuit: dict[str, Any] | None) -> None:
        self.pursuit = pursuit

    def get(self, organization_id: int, pursuit_id: int) -> dict[str, Any] | None:
        return self.pursuit


@pytest.fixture
def mod(monkeypatch: pytest.MonkeyPatch):
    import services.go_no_go_puntuacion as modulo

    def _hacer(rol: str = "member"):
        def _resolve(user_id: int, organization_id: Any = None, *, write: bool = False):
            return 7, rol

        monkeypatch.setattr(modulo, "resolve_organization", _resolve)
        return modulo

    modulo.con_rol = _hacer  # type: ignore[attr-defined]
    return _hacer()


class TestPesos:
    def test_los_pesos_salen_con_los_cinco_criterios_y_su_etiqueta(
        self, mod: Any, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        from services.go_no_go_template import CRITERIOS, UMBRAL_DEFECTO

        monkeypatch.setattr(mod, "_repo", _RepoDoble(pesos={}))

        salida = mod.get_weights(1)
        assert salida["organization_id"] == 7
        assert salida["umbral"] == UMBRAL_DEFECTO
        assert [c["criterio"] for c in salida["criterios"]] == list(CRITERIOS)
        assert all(c["etiqueta"] for c in salida["criterios"])

    def test_solo_el_riesgo_viaja_como_invertido(
        self, mod: Any, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setattr(mod, "_repo", _RepoDoble(pesos={}))

        invertidos = [c["criterio"] for c in mod.get_weights(1)["criterios"] if c["invertido"]]
        assert invertidos == ["riesgo"]

    def test_un_miembro_raso_no_mueve_los_pesos(
        self, mod: Any, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Los pesos son de quien responde de cómo decide el equipo."""
        from services.organizations import OrganizationPermissionError

        repo = _RepoDoble(pesos={})
        monkeypatch.setattr(mod, "_repo", repo)

        with pytest.raises(OrganizationPermissionError):
            mod.set_weights(1, {"encaje": 3.0})
        assert repo.guardados == []

    @pytest.mark.parametrize("rol", ["owner", "admin"])
    def test_owner_y_admin_si_los_mueven_y_queda_auditado(
        self, rol: str, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        import services.go_no_go_puntuacion as mod

        monkeypatch.setattr(mod, "resolve_organization", lambda u, o=None, *, write=False: (7, rol))
        repo = _RepoDoble(pesos={})
        monkeypatch.setattr(mod, "_repo", repo)

        eventos: list[dict[str, Any]] = []
        import db.audit

        monkeypatch.setattr(db.audit, "log_event", lambda **kw: eventos.append(kw))

        salida = mod.set_weights(1, {"encaje": 3.0, "ruido": 9.0})

        assert repo.guardados == [(7, {"encaje": 3.0, "ruido": 9.0})]
        assert salida["organization_id"] == 7
        assert eventos[0]["event_type"] == "go_no_go.weights_updated"
        # Lo que no es criterio no entra en la auditoría.
        assert eventos[0]["detail"]["pesos"] == {"encaje": 3.0}


class TestPuntuacion:
    def test_una_oportunidad_ajena_no_existe(
        self, mod: Any, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        from services.pursuits import PursuitNotFoundError

        monkeypatch.setattr(mod, "_repo", _RepoDoble())
        monkeypatch.setattr(mod, "_pursuits", _PursuitsDoble(None))

        with pytest.raises(PursuitNotFoundError):
            mod.get_score(1, 3)

    def test_un_criterio_sin_puntuar_sale_en_blanco_y_no_ausente(
        self, mod: Any, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """La UI necesita las cinco filas para poder pedir la que falta."""
        from services.go_no_go_template import CRITERIOS

        monkeypatch.setattr(
            mod,
            "_repo",
            _RepoDoble(
                puntuaciones=[
                    {
                        "criterio": "encaje",
                        "puntuacion": 5,
                        "motivo": "encaja",
                        "author_name": "Ana",
                    }
                ]
            ),
        )
        monkeypatch.setattr(mod, "_pursuits", _PursuitsDoble({"id": 3, "decision": None}))

        criterios = mod.get_score(1, 3)["criterios"]
        assert len(criterios) == len(CRITERIOS)
        encaje = next(c for c in criterios if c["criterio"] == "encaje")
        assert (encaje["puntuacion"], encaje["motivo"], encaje["author_name"]) == (
            5,
            "encaja",
            "Ana",
        )
        riesgo = next(c for c in criterios if c["criterio"] == "riesgo")
        assert (riesgo["puntuacion"], riesgo["motivo"], riesgo["author_name"]) == (
            None,
            None,
            None,
        )

    def test_la_discrepancia_viaja_con_la_decision_ya_tomada(
        self, mod: Any, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Para que la UI la señale sin una segunda petición."""
        monkeypatch.setattr(
            mod,
            "_repo",
            _RepoDoble(puntuaciones=[{"criterio": "encaje", "puntuacion": 5}]),
        )
        monkeypatch.setattr(mod, "_pursuits", _PursuitsDoble({"id": 3, "decision": "no_go"}))

        salida = mod.get_score(1, 3)
        assert salida["decision"] == "no_go"
        assert salida["recomendacion"] == "go"
        assert salida["discrepa"] is True

    def test_sin_decision_no_hay_nada_que_discrepar(
        self, mod: Any, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setattr(
            mod,
            "_repo",
            _RepoDoble(puntuaciones=[{"criterio": "encaje", "puntuacion": 5}]),
        )
        monkeypatch.setattr(mod, "_pursuits", _PursuitsDoble({"id": 3, "decision": None}))

        assert mod.get_score(1, 3)["discrepa"] is False


class TestPuntuar:
    def test_puntuar_no_es_decidir(self, mod: Any, monkeypatch: pytest.MonkeyPatch) -> None:
        """Cualquier miembro con escritura puntúa: es deliberación, no trámite."""
        repo = _RepoDoble(puntuaciones=[{"criterio": "encaje", "puntuacion": 4}])
        monkeypatch.setattr(mod, "_repo", repo)
        monkeypatch.setattr(mod, "_pursuits", _PursuitsDoble({"id": 3, "decision": None}))

        mod.set_score(1, 3, criterio="encaje", puntuacion=4, motivo="encaja")

        assert repo.puntuadas[0]["criterio"] == "encaje"
        assert repo.puntuadas[0]["author_user_id"] == 1

    def test_puntuar_una_oportunidad_ajena_no_encuentra_nada(
        self, mod: Any, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        from services.pursuits import PursuitNotFoundError

        monkeypatch.setattr(mod, "_repo", _RepoDoble(puntuar=False))
        monkeypatch.setattr(mod, "_pursuits", _PursuitsDoble({"id": 3}))

        with pytest.raises(PursuitNotFoundError):
            mod.set_score(1, 3, criterio="encaje", puntuacion=4)

    def test_puntuar_devuelve_la_ficha_completa(
        self, mod: Any, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setattr(
            mod,
            "_repo",
            _RepoDoble(puntuaciones=[{"criterio": "encaje", "puntuacion": 4}]),
        )
        monkeypatch.setattr(mod, "_pursuits", _PursuitsDoble({"id": 3, "decision": None}))

        salida = mod.set_score(1, 3, criterio="encaje", puntuacion=4)
        assert salida["pursuit_id"] == 3
        assert len(salida["criterios"]) == 5
