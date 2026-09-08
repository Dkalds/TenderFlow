"""Resolución de identidad de órganos, ejecutada (C1.2, ADR-032, D22).

`test_maestro_organos.py` fija el SQL y la normalización; el árbol de decisión
de `resolver()` —DIR3, nombre, sospecha, alta— entró sin ejecutarse. Es la
función que decide si dos grafías son el mismo organismo, y equivocarse ahí
junta dos historiales de contratación que no son el mismo: el error que ADR-032
describe como invisible durante meses.

Aquí se ejercitan las cuatro salidas y, sobre todo, **el orden**: que el DIR3
gane al nombre y que la sospecha no cree nada por su cuenta.
"""

from __future__ import annotations

from typing import Any

import pytest


class _RepoDoble:
    def __init__(
        self,
        *,
        por_dir3: dict[str, Any] | None = None,
        por_nombre: dict[str, Any] | None = None,
        nuevo_id: int = 99,
    ) -> None:
        self._por_dir3 = por_dir3
        self._por_nombre = por_nombre
        self._nuevo_id = nuevo_id
        self.alias: list[dict[str, Any]] = []
        self.revisiones: list[dict[str, Any]] = []
        self.creados: list[dict[str, Any]] = []

    def get_by_dir3(self, dir3: str) -> dict[str, Any] | None:
        return self._por_dir3

    def get_by_nombre_normalizado(self, nombre: str) -> dict[str, Any] | None:
        return self._por_nombre

    def anadir_alias(self, organo_id: int, **kwargs: Any) -> None:
        self.alias.append({"organo_id": organo_id, **kwargs})

    def encolar_revision(self, **kwargs: Any) -> None:
        self.revisiones.append(kwargs)

    def crear(self, **kwargs: Any) -> int:
        self.creados.append(kwargs)
        return self._nuevo_id


@pytest.fixture
def mod():
    import services.organos as modulo

    return modulo


def _sin_candidatos(monkeypatch: pytest.MonkeyPatch) -> None:
    import db.repositories.organos as repo_mod

    monkeypatch.setattr(repo_mod, "candidatos_por_palabras", lambda palabras: [])


class TestNombreVacio:
    @pytest.mark.parametrize("nombre", [None, "", "   ", "..."])
    def test_lo_que_no_da_para_un_nombre_no_resuelve(self, mod: Any, nombre: Any) -> None:
        assert mod.resolver(nombre) is None


class TestDir3Manda:
    def test_el_dir3_conocido_resuelve_sin_mirar_el_nombre(
        self, mod: Any, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        repo = _RepoDoble(
            por_dir3={"organo_id": 5, "nombre_normalizado": "ayuntamiento de leon"},
            por_nombre={"organo_id": 404},
        )
        monkeypatch.setattr(mod, "repo", repo)

        r = mod.resolver("Ayuntamiento de León", dir3="L01240891")
        assert (r.organo_id, r.via) == (5, "dir3")

    def test_una_grafia_nueva_con_dir3_conocido_se_registra_como_alias(
        self, mod: Any, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Así la próxima vez resuelve por nombre aunque la fuente omita el DIR3."""
        repo = _RepoDoble(por_dir3={"organo_id": 5, "nombre_normalizado": "ayuntamiento de leon"})
        monkeypatch.setattr(mod, "repo", repo)

        mod.resolver("Excmo. Ayuntamiento de León (Servicios)", dir3="L01240891")
        assert len(repo.alias) == 1
        assert repo.alias[0]["organo_id"] == 5
        assert repo.alias[0]["fuente"] == "dir3"

    def test_la_misma_grafia_no_se_vuelve_a_registrar(
        self, mod: Any, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        repo = _RepoDoble(por_dir3={"organo_id": 5, "nombre_normalizado": "ayuntamiento de leon"})
        monkeypatch.setattr(mod, "repo", repo)

        mod.resolver("Ayuntamiento de León", dir3="L01240891")
        assert repo.alias == []

    def test_un_dir3_desconocido_no_impide_seguir_por_nombre(
        self, mod: Any, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        repo = _RepoDoble(por_dir3=None, por_nombre={"organo_id": 8})
        monkeypatch.setattr(mod, "repo", repo)

        r = mod.resolver("Ayuntamiento de León", dir3="NO-EXISTE")
        assert (r.organo_id, r.via) == (8, "nombre")


class TestNombreExacto:
    def test_el_nombre_normalizado_resuelve(
        self, mod: Any, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setattr(mod, "repo", _RepoDoble(por_nombre={"organo_id": 8}))

        r = mod.resolver("Excmo. Ayuntamiento de León")
        assert (r.organo_id, r.via) == (8, "nombre")


class TestSospecha:
    def test_un_parecido_alto_va_a_revision_y_no_crea_nada(
        self, mod: Any, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Fusionar exige evidencia; separar, no. Por eso la asimetría."""
        import db.repositories.organos as repo_mod

        repo = _RepoDoble()
        monkeypatch.setattr(mod, "repo", repo)
        monkeypatch.setattr(
            repo_mod,
            "candidatos_por_palabras",
            lambda palabras: [{"organo_id": 12, "nombre_normalizado": "ayuntamiento de leon"}],
        )

        r = mod.resolver("Ayuntamiento de Leon")
        assert (r.organo_id, r.via, r.candidato_id) == (None, "revision", 12)
        assert r.score >= mod.UMBRAL_SOSPECHA
        assert len(repo.revisiones) == 1
        assert repo.creados == []

    def test_un_parecido_bajo_no_va_a_revision_sino_a_alta(
        self, mod: Any, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Dos ayuntamientos distintos no se fusionan por compartir la mitad."""
        import db.repositories.organos as repo_mod

        repo = _RepoDoble()
        monkeypatch.setattr(mod, "repo", repo)
        monkeypatch.setattr(
            repo_mod,
            "candidatos_por_palabras",
            lambda palabras: [
                {"organo_id": 12, "nombre_normalizado": "ayuntamiento de alcala de guadaira"}
            ],
        )

        r = mod.resolver("Ayuntamiento de Alcalá de Henares")
        assert r.via == "nuevo"
        assert repo.revisiones == []


class TestAlta:
    def test_un_nombre_desconocido_crea_organo(
        self, mod: Any, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        repo = _RepoDoble(nuevo_id=77)
        monkeypatch.setattr(mod, "repo", repo)
        _sin_candidatos(monkeypatch)

        r = mod.resolver("  Consorcio de Aguas de Bilbao  ", ccaa="pais-vasco")
        assert (r.organo_id, r.via) == (77, "nuevo")
        assert repo.creados[0]["nombre_canonico"] == "Consorcio de Aguas de Bilbao"
        assert repo.creados[0]["ccaa"] == "pais-vasco"

    def test_sin_permiso_de_alta_lo_dice_y_no_escribe(
        self, mod: Any, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """El backfill necesita poder preguntar sin crear filas."""
        repo = _RepoDoble()
        monkeypatch.setattr(mod, "repo", repo)
        _sin_candidatos(monkeypatch)

        r = mod.resolver("Consorcio de Aguas de Bilbao", crear_si_falta=False)
        assert (r.organo_id, r.via) == (None, "nuevo")
        assert repo.creados == []


class TestCandidatos:
    def test_un_nombre_sin_palabras_largas_no_busca_candidatos(
        self, mod: Any, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Comparar contra el maestro entero haría el backfill interminable."""
        import db.repositories.organos as repo_mod

        def _explota(palabras: list[str]) -> list[dict[str, Any]]:
            raise AssertionError("no debería consultar el maestro")

        monkeypatch.setattr(repo_mod, "candidatos_por_palabras", _explota)
        assert mod._candidato_mas_parecido("casa mar sol") == (None, 0.0)

    def test_se_queda_con_el_mas_parecido_de_varios(
        self, mod: Any, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        import db.repositories.organos as repo_mod

        monkeypatch.setattr(
            repo_mod,
            "candidatos_por_palabras",
            lambda palabras: [
                {"organo_id": 1, "nombre_normalizado": "ayuntamiento de sevilla capital"},
                {"organo_id": 2, "nombre_normalizado": "ayuntamiento de sevilla"},
            ],
        )

        assert mod._candidato_mas_parecido("ayuntamiento de sevilla")[0] == 2

    def test_la_similitud_de_lo_vacio_es_cero(self, mod: Any) -> None:
        assert mod.similitud("", "ayuntamiento") == 0.0
