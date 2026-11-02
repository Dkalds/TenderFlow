"""Membresías, cuotas y baja de miembros (auditoría 2026-11).

Sin BD: el repositorio se sustituye por un doble en los tests de servicio, y el
SQL de la baja se comprueba por su texto sobre una conexión falsa. La versión
con Postgres está en `tests/test_baja_miembro_integracion.py`.
"""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime
from typing import Any

import pytest
from fastapi import HTTPException

import services.organizations as svc
from shared.dto import OrganizationMembershipUpsert

_AHORA = datetime(2026, 11, 1, tzinfo=UTC)


class _Repo:
    """Doble del repositorio: ``roles`` son las membresías activas por usuario."""

    def __init__(
        self,
        roles: dict[int, str],
        *,
        fuera: dict[int, str] | None = None,
        creadas: int = 0,
        invitaciones: int = 0,
    ) -> None:
        self._roles = roles
        self._fuera = fuera or {}
        self._creadas = creadas
        self._invitaciones = invitaciones
        self.escrito: list[tuple[int, str, str]] = []
        self.invitados: list[str] = []

    def get_active_membership(self, organization_id: int, user_id: int) -> dict[str, Any] | None:
        rol = self._roles.get(user_id)
        return {"role": rol, "user_id": user_id} if rol else None

    def get_membership_role(self, organization_id: int, user_id: int) -> str | None:
        return self._roles.get(user_id) or self._fuera.get(user_id)

    def add_membership(
        self,
        organization_id: int,
        user_id: int,
        role: str,
        *,
        invited_by_user_id: int | None = None,
        status: str = "active",
    ) -> dict[str, Any]:
        self.escrito.append((user_id, role, status))
        return {
            "organization_id": organization_id,
            "user_id": user_id,
            "role": role,
            "status": status,
            "created_at": _AHORA,
            "updated_at": _AHORA,
            "display_name": None,
            "email": None,
        }

    def contar_organizaciones_creadas(self, user_id: int) -> int:
        return self._creadas

    def contar_invitaciones_desde(self, user_id: int, desde: datetime) -> int:
        return self._invitaciones

    def get_for_user(self, organization_id: int, user_id: int) -> dict[str, Any] | None:
        return {"id": organization_id, "name": "Equipo"}

    def create_invitation(self, organization_id: int, email: str, role: str, **_: Any) -> Any:
        self.invitados.append(email)
        return {
            "id": 1,
            "organization_id": organization_id,
            "email": email,
            "role": role,
            "invited_by_user_id": 1,
            "created_at": _AHORA,
            "expires_at": datetime(2099, 1, 1, tzinfo=UTC),
        }

    def create_organization(self, name: str, owner_user_id: int) -> dict[str, Any]:
        return {
            "id": 9,
            "name": name,
            "is_personal": False,
            "role": "owner",
            "created_at": _AHORA,
        }


def _con(monkeypatch: pytest.MonkeyPatch, repo: _Repo) -> _Repo:
    monkeypatch.setattr(svc, "_repo", repo)
    monkeypatch.setattr(svc, "_send_invitation_email", lambda *_a, **_k: True)
    return repo


def _put(user_id: int, role: str, status: str = "active") -> OrganizationMembershipUpsert:
    return OrganizationMembershipUpsert(user_id=user_id, role=role, status=status)


# ── authz-organizaciones-1: el PUT por id ya no da de alta a desconocidos ─────


def test_el_put_de_quien_no_tiene_membresia_no_escribe_y_es_not_found(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    repo = _con(monkeypatch, _Repo({1: "owner"}))

    with pytest.raises(svc.OrganizationMemberNotFoundError):
        svc.upsert_membership(1, 5, _put(99, "member"))
    assert repo.escrito == []


def test_el_put_si_cambia_a_quien_ya_tiene_fila_aunque_este_retirado(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    repo = _con(monkeypatch, _Repo({1: "owner"}, fuera={7: "viewer"}))

    resultado = svc.upsert_membership(1, 5, _put(7, "member"))

    assert (resultado.user_id, resultado.role) == (7, "member")
    assert repo.escrito == [(7, "member", "active")]


# ── G1-7-2: una cuenta sin verificar no entra por el alta directa ────────────


def test_el_alta_por_correo_solo_mira_cuentas_verificadas(monkeypatch: pytest.MonkeyPatch) -> None:
    repo = _con(monkeypatch, _Repo({1: "owner"}))
    pedidos: list[dict[str, Any]] = []

    def _buscar(email: str, **kw: Any) -> None:
        pedidos.append(kw)

    monkeypatch.setattr(svc, "get_active_user_by_email_ci", _buscar)

    # Sin cuenta (verificada) cae a la invitación, que se canjea al demostrar el buzón.
    resultado = svc.invite_member_by_email(1, 5, "pendiente@example.test", "member")

    assert pedidos == [{"solo_verificadas": True}]
    assert resultado.status == "invited"
    assert repo.escrito == []
    assert repo.invitados == ["pendiente@example.test"]


# ── G2-5-2: solo el owner toca a los admins ──────────────────────────────────


def test_un_admin_no_asciende_a_nadie_a_admin(monkeypatch: pytest.MonkeyPatch) -> None:
    repo = _con(monkeypatch, _Repo({1: "admin", 2: "member"}))

    with pytest.raises(svc.OrganizationPermissionError, match="admin"):
        svc.upsert_membership(1, 5, _put(2, "admin"))
    with pytest.raises(svc.OrganizationPermissionError, match="admin"):
        svc.create_invitation(1, 5, "complice@example.test", "admin")
    assert repo.escrito == [] and repo.invitados == []


@pytest.mark.parametrize("estado", ["revoked", "suspended", "active"])
def test_un_admin_no_degrada_ni_retira_ni_reactiva_a_otro_admin(
    monkeypatch: pytest.MonkeyPatch, estado: str
) -> None:
    repo = _con(monkeypatch, _Repo({1: "admin", 2: "admin"}))

    with pytest.raises(svc.OrganizationPermissionError, match="otro admin"):
        svc.upsert_membership(1, 5, _put(2, "member", estado))
    assert repo.escrito == []


def test_un_admin_si_retira_a_un_member(monkeypatch: pytest.MonkeyPatch) -> None:
    repo = _con(monkeypatch, _Repo({1: "admin", 2: "member"}))

    svc.upsert_membership(1, 5, _put(2, "member", "revoked"))

    assert repo.escrito == [(2, "member", "revoked")]


def test_el_owner_si_cambia_a_un_admin_y_asigna_admin(monkeypatch: pytest.MonkeyPatch) -> None:
    repo = _con(monkeypatch, _Repo({1: "owner", 2: "admin", 3: "member"}))

    svc.upsert_membership(1, 5, _put(2, "member", "revoked"))
    svc.upsert_membership(1, 5, _put(3, "admin"))

    assert repo.escrito == [(2, "member", "revoked"), (3, "admin", "active")]


# ── G1-7-3: cuotas ───────────────────────────────────────────────────────────


def test_no_se_crean_organizaciones_sin_fin(monkeypatch: pytest.MonkeyPatch) -> None:
    _con(monkeypatch, _Repo({}, creadas=svc.MAX_ORGANIZACIONES_CREADAS))

    with pytest.raises(svc.OrganizationQuotaError):
        svc.create_organization(1, "Una más")


def test_bajo_el_tope_la_organizacion_se_crea(monkeypatch: pytest.MonkeyPatch) -> None:
    _con(monkeypatch, _Repo({}, creadas=svc.MAX_ORGANIZACIONES_CREADAS - 1))

    assert svc.create_organization(1, "La última").name == "La última"


def test_no_se_mandan_invitaciones_sin_fin(monkeypatch: pytest.MonkeyPatch) -> None:
    repo = _con(monkeypatch, _Repo({1: "owner"}, invitaciones=svc.MAX_INVITACIONES_POR_DIA))

    with pytest.raises(svc.OrganizationQuotaError):
        svc.create_invitation(1, 5, "otra@example.test", "member")
    assert repo.invitados == []


def test_el_reenvio_tambien_cuenta_para_la_cuota(monkeypatch: pytest.MonkeyPatch) -> None:
    """`resend_invitation` emite un token y un correo nuevos: pasa por `create_invitation`."""
    repo = _con(monkeypatch, _Repo({1: "owner"}, invitaciones=svc.MAX_INVITACIONES_POR_DIA))
    monkeypatch.setattr(
        repo,
        "get_invitation",
        lambda *_a: {
            "email": "x@example.test",
            "role": "member",
            "expires_at": datetime(2099, 1, 1, tzinfo=UTC),
        },
        raising=False,
    )

    with pytest.raises(svc.OrganizationQuotaError):
        svc.resend_invitation(1, 5, 3)


# ── La cuota se traduce a 429 en las rutas ───────────────────────────────────


def test_la_ruta_de_alta_responde_429_si_se_alcanza_la_cuota(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import api.routes.organizations as rutas

    def _revienta(*_a: Any, **_k: Any) -> None:
        raise svc.OrganizationQuotaError("tope")

    monkeypatch.setattr(rutas, "create_organization", _revienta)

    with pytest.raises(HTTPException) as exc:
        asyncio.run(rutas.post_organization(rutas.OrganizationCreate(name="X"), {"user_id": 1}))
    assert exc.value.status_code == 429


# ── G2-5-1, G1-7-1, G1-5-2: lo que deja quien se va ──────────────────────────


class _Conexion:
    def __init__(self, sqls: list[tuple[str, tuple[Any, ...]]], rowcount: int = 1) -> None:
        self._sqls = sqls
        self._rowcount = rowcount

    def __enter__(self) -> _Conexion:
        return self

    def __exit__(self, *_a: object) -> bool:
        return False

    def execute(self, sql: str, params: tuple[Any, ...] = ()) -> _Conexion:
        self._sqls.append((sql, params))
        return self

    @property
    def rowcount(self) -> int:
        return self._rowcount

    def fetchone(self) -> None:
        return None


def _tablas_tocadas(sqls: list[tuple[str, tuple[Any, ...]]]) -> list[str]:
    return [sql.split()[1] for sql, _ in sqls if sql.startswith("UPDATE")]


def test_salir_desactiva_webhooks_revoca_invitaciones_y_retira_el_perfil_compartido(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import db.repositories.organizations as repos

    sqls: list[tuple[str, tuple[Any, ...]]] = []
    monkeypatch.setattr(repos, "connect", lambda: _Conexion(sqls))

    assert repos.OrganizationRepository().salir(5, 42) is True

    assert _tablas_tocadas(sqls) == [
        "organization_memberships",
        "webhooks",
        "organization_invitations",
        "user_profiles",
    ]
    por_tabla = {sql.split()[1]: (sql, params) for sql, params in sqls}
    assert por_tabla["webhooks"][1] == (5, 42)
    assert "created_by = %s" in por_tabla["webhooks"][0]
    assert "invited_by_user_id = %s" in por_tabla["organization_invitations"][0]
    assert "accepted_at IS NULL" in por_tabla["organization_invitations"][0]
    assert "visibility = 'private'" in por_tabla["user_profiles"][0]
    assert por_tabla["user_profiles"][1] == (5, 42)


def test_salir_sin_membresia_activa_no_toca_nada_mas(monkeypatch: pytest.MonkeyPatch) -> None:
    import db.repositories.organizations as repos

    sqls: list[tuple[str, tuple[Any, ...]]] = []
    monkeypatch.setattr(repos, "connect", lambda: _Conexion(sqls, rowcount=0))

    assert repos.OrganizationRepository().salir(5, 42) is False
    assert _tablas_tocadas(sqls) == ["organization_memberships"]


def test_retirar_a_un_miembro_desde_el_put_hace_lo_mismo_que_salir(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import db.repositories.organizations as repos

    sqls: list[tuple[str, tuple[Any, ...]]] = []
    monkeypatch.setattr(repos, "connect", lambda: _Conexion(sqls))
    monkeypatch.setattr(repos, "rows_to_dicts", lambda _cur: [{"user_id": 42}])

    repos.OrganizationRepository().add_membership(5, 42, "member", status="revoked")

    assert {"webhooks", "organization_invitations", "user_profiles"} <= set(_tablas_tocadas(sqls))


def test_dar_de_alta_no_retira_nada(monkeypatch: pytest.MonkeyPatch) -> None:
    import db.repositories.organizations as repos

    sqls: list[tuple[str, tuple[Any, ...]]] = []
    monkeypatch.setattr(repos, "connect", lambda: _Conexion(sqls))
    monkeypatch.setattr(repos, "rows_to_dicts", lambda _cur: [{"user_id": 42}])

    repos.OrganizationRepository().add_membership(5, 42, "member")

    assert "webhooks" not in _tablas_tocadas(sqls)


# ── authz-organizaciones-7: el aviso de la tarea solo va a quien sigue en el equipo ──


def test_la_consulta_de_tareas_que_vencen_anula_al_responsable_que_ya_no_es_miembro(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import db.repositories.pursuit_tasks as repos

    sqls: list[str] = []

    class _Lectura(_Conexion):
        def execute(self, sql: str, params: tuple[Any, ...] = ()) -> _Conexion:
            sqls.append(sql)
            return self

    monkeypatch.setattr(repos, "connect_read", lambda: _Lectura([]))
    monkeypatch.setattr(repos, "rows_to_dicts", lambda cur: [])

    repos.PursuitTasksRepository().vencen_en(fecha="2026-11-01")

    (sql,) = sqls
    assert "organization_memberships" in sql
    assert "m.status = 'active'" in sql
    assert "END AS responsable_user_id" in sql


# ── G2-5-1 / G2-1-1: los webhooks solo los gestionan owner y admin ───────────


@pytest.mark.parametrize("rol", ["member", "viewer"])
def test_member_y_viewer_no_pasan_el_escalon_de_rol(
    monkeypatch: pytest.MonkeyPatch, rol: str
) -> None:
    import api.tenancy as tenancy
    from api.routes.webhooks import _GESTORES

    monkeypatch.setattr(tenancy, "resolve_organization", lambda *_a, **_k: (5, rol))

    with pytest.raises(HTTPException) as exc:
        asyncio.run(tenancy.resolve_organization_ctx({"user_id": 1}, 5, roles=_GESTORES))
    assert exc.value.status_code == 403
    assert "admin" in exc.value.detail and "owner" in exc.value.detail


@pytest.mark.parametrize("rol", ["owner", "admin"])
def test_owner_y_admin_pasan_y_sin_roles_no_hay_escalon(
    monkeypatch: pytest.MonkeyPatch, rol: str
) -> None:
    import api.tenancy as tenancy
    from api.routes.webhooks import _GESTORES

    monkeypatch.setattr(tenancy, "resolve_organization", lambda *_a, **_k: (5, rol))
    monkeypatch.setattr(tenancy, "set_organization", lambda _id: None)

    con_roles = asyncio.run(tenancy.resolve_organization_ctx({"user_id": 1}, 5, roles=_GESTORES))
    sin_roles = asyncio.run(tenancy.resolve_organization_ctx({"user_id": 1}, 5))

    assert con_roles["organization_role"] == rol
    assert sin_roles["organization_id"] == 5


def test_todas_las_rutas_de_webhooks_de_organizacion_exigen_gestor() -> None:
    """Ninguna ruta por organización queda con el escalón de rol sin poner."""
    import inspect

    import api.routes.webhooks as rutas

    fuente = inspect.getsource(rutas)
    assert "Depends(require_organization())" not in fuente
    assert "Depends(require_organization(write=True))" not in fuente
