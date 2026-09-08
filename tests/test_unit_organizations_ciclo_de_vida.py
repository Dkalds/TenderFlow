"""Ciclo de vida de la organización, ejecutado (C2.2, ADR-030 §D).

Es el código donde el fuzzing encontró uno de los dos 5xx de esta ola: seis
sentencias escribían `organization_members` cuando la tabla se llama
`organization_memberships` desde `v61`, y `transfer-ownership` y `leave`
devolvían 500 **solo** cuando quien llamaba era realmente el owner —los demás
recibían 403 antes de llegar al SQL—. El guardarraíl estructural
(`test_tablas_citadas_existen.py`) evita que vuelva a pasar; esto cubre la otra
mitad, que es que las reglas de decisión se ejecuten.

Cada regla de aquí responde a un modo de fallo concreto, y el test dice cuál.
"""

from __future__ import annotations

from typing import Any

import pytest


class _RepoDoble:
    def __init__(
        self,
        *,
        membresia: dict[str, Any] | None = None,
        personal: bool = False,
        traspaso_ok: bool = True,
        borrado_ok: bool = True,
        conteos: dict[str, int] | None = None,
    ) -> None:
        self._membresia = membresia
        self._personal = personal
        self._traspaso_ok = traspaso_ok
        self._borrado_ok = borrado_ok
        self._conteos = conteos if conteos is not None else {"pursuits": 14, "comentarios": 37}
        self.salidas: list[tuple[int, int]] = []
        self.traspasos: list[dict[str, Any]] = []
        self.borrados: list[int] = []

    def get_active_membership(self, organization_id: int, user_id: int) -> dict[str, Any] | None:
        return self._membresia

    def es_personal(self, organization_id: int) -> bool:
        return self._personal

    def traspasar_propiedad(self, organization_id: int, *, de_user_id: int, a_user_id: int) -> bool:
        self.traspasos.append({"de": de_user_id, "a": a_user_id})
        return self._traspaso_ok

    def salir(self, organization_id: int, user_id: int) -> None:
        self.salidas.append((organization_id, user_id))

    def contar_dato_corporativo(self, organization_id: int) -> dict[str, int]:
        return dict(self._conteos)

    def borrar(self, organization_id: int) -> bool:
        self.borrados.append(organization_id)
        return self._borrado_ok


@pytest.fixture
def mod():
    import services.organizations as modulo

    return modulo


def _repo(monkeypatch: pytest.MonkeyPatch, mod: Any, doble: _RepoDoble) -> _RepoDoble:
    monkeypatch.setattr(mod, "_repo", doble)
    return doble


class TestTraspaso:
    def test_traspasarse_a_uno_mismo_no_es_una_transicion(
        self, mod: Any, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        doble = _repo(monkeypatch, mod, _RepoDoble(membresia={"role": "owner"}))

        with pytest.raises(mod.OrganizationLifecycleError, match="ya eres tú"):
            mod.transferir_propiedad(organization_id=1, actor_user_id=5, nuevo_owner_user_id=5)
        assert doble.traspasos == []

    def test_un_admin_no_se_autoasciende(self, mod: Any, monkeypatch: pytest.MonkeyPatch) -> None:
        """Si un admin pudiera traspasar, se traspasaría a sí mismo."""
        doble = _repo(monkeypatch, mod, _RepoDoble(membresia={"role": "admin"}))

        with pytest.raises(mod.OrganizationPermissionError):
            mod.transferir_propiedad(organization_id=1, actor_user_id=5, nuevo_owner_user_id=9)
        assert doble.traspasos == []

    def test_quien_no_es_miembro_tampoco_traspasa(
        self, mod: Any, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        _repo(monkeypatch, mod, _RepoDoble(membresia=None))

        with pytest.raises(mod.OrganizationPermissionError):
            mod.transferir_propiedad(organization_id=1, actor_user_id=5, nuevo_owner_user_id=9)

    def test_la_personal_no_se_regala(self, mod: Any, monkeypatch: pytest.MonkeyPatch) -> None:
        """Es el contenedor por defecto de la cuenta: sin ella no hay dónde escribir."""
        doble = _repo(monkeypatch, mod, _RepoDoble(membresia={"role": "owner"}, personal=True))

        with pytest.raises(mod.OrganizationLifecycleError, match="personal"):
            mod.transferir_propiedad(organization_id=1, actor_user_id=5, nuevo_owner_user_id=9)
        assert doble.traspasos == []

    def test_el_destino_tiene_que_ser_miembro_activo(
        self, mod: Any, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Invitar y traspasar son cosas distintas: juntarlas convierte un typo
        en el email en una organización cuyo owner no existe."""
        _repo(
            monkeypatch,
            mod,
            _RepoDoble(membresia={"role": "owner"}, traspaso_ok=False),
        )

        with pytest.raises(mod.OrganizationMemberNotFoundError, match="Invitalo primero"):
            mod.transferir_propiedad(organization_id=1, actor_user_id=5, nuevo_owner_user_id=9)

    def test_el_owner_traspasa(self, mod: Any, monkeypatch: pytest.MonkeyPatch) -> None:
        doble = _repo(monkeypatch, mod, _RepoDoble(membresia={"role": "owner"}))

        mod.transferir_propiedad(organization_id=1, actor_user_id=5, nuevo_owner_user_id=9)
        assert doble.traspasos == [{"de": 5, "a": 9}]


class TestSalida:
    def test_quien_no_es_miembro_no_puede_salir(
        self, mod: Any, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        _repo(monkeypatch, mod, _RepoDoble(membresia=None))

        with pytest.raises(mod.OrganizationMemberNotFoundError):
            mod.salir_de_organizacion(organization_id=1, user_id=5)

    def test_el_owner_no_se_va_sin_traspasar(
        self, mod: Any, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Una organización sin owner queda sin nadie que la administre, y ese
        estado no tiene salida desde el producto."""
        doble = _repo(monkeypatch, mod, _RepoDoble(membresia={"role": "owner"}))

        with pytest.raises(mod.OrganizationLifecycleError, match="traspas"):
            mod.salir_de_organizacion(organization_id=1, user_id=5)
        assert doble.salidas == []

    def test_de_la_personal_no_se_sale(self, mod: Any, monkeypatch: pytest.MonkeyPatch) -> None:
        doble = _repo(monkeypatch, mod, _RepoDoble(membresia={"role": "member"}, personal=True))

        with pytest.raises(mod.OrganizationLifecycleError, match="personal"):
            mod.salir_de_organizacion(organization_id=1, user_id=5)
        assert doble.salidas == []

    def test_un_miembro_raso_si_se_va(self, mod: Any, monkeypatch: pytest.MonkeyPatch) -> None:
        doble = _repo(monkeypatch, mod, _RepoDoble(membresia={"role": "member"}))

        mod.salir_de_organizacion(organization_id=1, user_id=5)
        assert doble.salidas == [(1, 5)]


class TestResumenDeBorrado:
    def test_solo_el_owner_ve_el_resumen(self, mod: Any, monkeypatch: pytest.MonkeyPatch) -> None:
        _repo(monkeypatch, mod, _RepoDoble(membresia={"role": "admin"}))

        with pytest.raises(mod.OrganizationPermissionError):
            mod.resumen_de_borrado(organization_id=1, actor_user_id=5)

    def test_el_resumen_cuenta_lo_que_se_va_a_perder(
        self, mod: Any, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """«Vas a borrar 14 oportunidades» es una advertencia; «¿seguro?» no."""
        _repo(monkeypatch, mod, _RepoDoble(membresia={"role": "owner"}))

        assert mod.resumen_de_borrado(organization_id=1, actor_user_id=5) == {
            "pursuits": 14,
            "comentarios": 37,
        }


class TestBorrado:
    def _sin_adjuntos(self, monkeypatch: pytest.MonkeyPatch, purgados: int = 0) -> None:
        import services.pursuit_attachments as adjuntos

        monkeypatch.setattr(adjuntos, "purgar_organizacion", lambda org: purgados)

    def test_sin_la_palabra_literal_no_se_borra_nada(
        self, mod: Any, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """No tiene deshacer y se lleva trabajo de otras personas."""
        doble = _repo(monkeypatch, mod, _RepoDoble(membresia={"role": "owner"}))

        with pytest.raises(mod.OrganizationLifecycleError, match="BORRAR"):
            mod.borrar_organizacion(organization_id=1, actor_user_id=5, confirmacion="si")
        assert doble.borrados == []

    def test_la_confirmacion_admite_espacios_alrededor(
        self, mod: Any, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        doble = _repo(monkeypatch, mod, _RepoDoble(membresia={"role": "owner"}))
        self._sin_adjuntos(monkeypatch)

        mod.borrar_organizacion(organization_id=1, actor_user_id=5, confirmacion="  BORRAR  ")
        assert doble.borrados == [1]

    def test_un_admin_no_borra_aunque_escriba_la_palabra(
        self, mod: Any, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        doble = _repo(monkeypatch, mod, _RepoDoble(membresia={"role": "admin"}))

        with pytest.raises(mod.OrganizationPermissionError):
            mod.borrar_organizacion(organization_id=1, actor_user_id=5, confirmacion="BORRAR")
        assert doble.borrados == []

    def test_la_personal_no_se_borra_por_aqui(
        self, mod: Any, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        doble = _repo(monkeypatch, mod, _RepoDoble(membresia={"role": "owner"}, personal=True))

        with pytest.raises(mod.OrganizationLifecycleError, match="DELETE /me"):
            mod.borrar_organizacion(organization_id=1, actor_user_id=5, confirmacion="BORRAR")
        assert doble.borrados == []

    def test_los_binarios_se_purgan_antes_de_borrar_la_fila(
        self, mod: Any, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """El `ON DELETE CASCADE` se lleva las filas, y sin ellas no habría forma
        de saber qué objetos quedaron huérfanos en el almacén."""
        doble = _repo(monkeypatch, mod, _RepoDoble(membresia={"role": "owner"}))
        orden: list[str] = []

        import services.pursuit_attachments as adjuntos

        def _purgar(org: int) -> int:
            orden.append("purga")
            return 3

        monkeypatch.setattr(adjuntos, "purgar_organizacion", _purgar)
        borrar_original = doble.borrar

        def _borrar(org: int) -> bool:
            orden.append("borrado")
            return borrar_original(org)

        monkeypatch.setattr(doble, "borrar", _borrar)

        conteos = mod.borrar_organizacion(organization_id=1, actor_user_id=5, confirmacion="BORRAR")
        assert orden == ["purga", "borrado"]
        assert conteos["adjuntos_purgados"] == 3

    def test_un_fallo_del_bucket_no_bloquea_la_supresion(
        self, mod: Any, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """El derecho de supresión no puede depender de que S3 responda; lo que
        no se pudo purgar queda marcado con -1 para repasarlo."""
        doble = _repo(monkeypatch, mod, _RepoDoble(membresia={"role": "owner"}))

        import services.pursuit_attachments as adjuntos

        def _explota(org: int) -> int:
            raise RuntimeError("bucket no responde")

        monkeypatch.setattr(adjuntos, "purgar_organizacion", _explota)

        conteos = mod.borrar_organizacion(organization_id=1, actor_user_id=5, confirmacion="BORRAR")
        assert conteos["adjuntos_purgados"] == -1
        assert doble.borrados == [1]

    def test_una_organizacion_que_ya_no_esta_lo_dice(
        self, mod: Any, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        _repo(
            monkeypatch,
            mod,
            _RepoDoble(membresia={"role": "owner"}, borrado_ok=False),
        )
        self._sin_adjuntos(monkeypatch)

        with pytest.raises(mod.OrganizationMemberNotFoundError):
            mod.borrar_organizacion(organization_id=1, actor_user_id=5, confirmacion="BORRAR")
