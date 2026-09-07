"""S2.1/S2.2 — permisos y persistencia de la identidad fiscal y la capacidad.

Integración: usa ``tmp_db`` porque lo que se comprueba es SQL real —los únicos
parciales de ``v111``, el reemplazo transaccional de ``v112`` y el enlace con el
maestro de empresas—, y eso no se simula.

**Dos niveles a propósito.** Desde que la ruta pasa por ``api/tenancy.py``
(``tests/test_organization_sql_isolation.py``), resolver la organización y
exigir el rol es trabajo del *handler*: las funciones privadas
(``_leer_nifs``, ``_escribir_capacidad``…) reciben una organización ya resuelta
y autorizada, y solo hacen el SQL. Por eso lo que prueba persistencia llama a
las privadas —directo al grano— y lo que prueba permisos llama a la corrutina
del handler, que es donde vive ahora la decisión. Llamar a la privada para
probar un permiso mediría una barrera que ya no está ahí.
"""

from __future__ import annotations

import asyncio
from typing import Any

import pytest
from fastapi import HTTPException

from api.routes.organizations_capacidad import (
    _escribir_capacidad,
    _escribir_nifs,
    _leer_capacidad,
    _leer_nifs,
    get_organization_capabilities,
    get_organization_nifs,
    put_organization_capabilities,
)
from db.repositories.organization_nifs import OrganizationNifRepository
from db.repositories.organizations import OrganizationRepository
from services.pursuit_awards import identidad_fiscal, sugerir_resultado
from shared.dto import (
    OrganizationCapabilities,
    OrganizationCapabilitiesOut,
    OrganizationNif,
    OrganizationNifsIn,
    OrganizationNifsOut,
    PursuitAdjudicatario,
)

# NIF de ejemplo con el formato fiscal español (letra + 8 dígitos). Van como
# constantes y no en línea porque `ruff format` reflujo las expresiones y dejó
# el pragma separado de su literal; detect-secrets los lee como cadenas
# hexadecimales de alta entropía y hay que marcarlos donde estén.
_NIF_AJENO = "A87654321"  # pragma: allowlist secret
_NIF_PROPIO = "B12345678"  # pragma: allowlist secret


def _user(email: str) -> int:
    from db.users import create_user

    return create_user(
        email=email,
        password_hash="test-hash",  # pragma: allowlist secret
    )


def _organizacion(nombre: str, owner: int) -> int:
    return int(OrganizationRepository().create_organization(nombre, owner)["id"])


def _como(user_id: int) -> dict[str, Any]:
    """El ``ctx`` que ``require_any_auth`` inyecta en el handler."""
    return {"user_id": user_id}


def _get_nifs(user_id: int, organization_id: int) -> OrganizationNifsOut:
    """El handler completo: resolución de tenencia, rol y lectura."""
    return asyncio.run(get_organization_nifs(organization_id, _como(user_id)))


def _get_capacidad(user_id: int, organization_id: int) -> OrganizationCapabilitiesOut:
    return asyncio.run(get_organization_capabilities(organization_id, _como(user_id)))


def _put_capacidad(
    user_id: int, organization_id: int, body: OrganizationCapabilities
) -> OrganizationCapabilitiesOut:
    return asyncio.run(put_organization_capabilities(organization_id, body, _como(user_id)))


_CAPACIDAD = OrganizationCapabilities.model_validate(
    {
        "certificaciones": [
            {"nombre": "ISO/IEC 27001", "ambito": "company", "vigente_hasta": "2027-01-01"}
        ],
        "facturacion": [{"ejercicio": 2025, "importe_eur": 1200000}],
        "referencias": [
            {
                "organo": "Ayuntamiento de Vigo",
                "importe_eur": 350000,
                "anio": 2024,
                "tecnologia": "SAP",
            }
        ],
        "perfiles_equipo": [{"rol": "Jefe de proyecto", "anios": 9, "cantidad": 2}],
    }
)


# ── Identidad fiscal ───────────────────────────────────────────────────────


def test_put_nifs_normaliza_y_persiste(tmp_db):
    _db_mod, _ = tmp_db
    owner = _user("owner-nifs@example.test")
    organizacion = _organizacion("Equipo NIF", owner)

    guardado = _escribir_nifs(
        organizacion,
        OrganizationNifsIn(
            nifs=[
                OrganizationNif(nif="b-12.345.678", razon_social="Acme SL", principal=True),
                OrganizationNif(
                    nif=_NIF_AJENO, razon_social="Acme Filial SL"
                ),  # pragma: allowlist secret
            ]
        ),
        actor_user_id=owner,
    )

    # El orden de lectura es «principal primero, luego por NIF».
    assert [fila.nif for fila in guardado.nifs] == [
        _NIF_PROPIO,
        _NIF_AJENO,
    ]  # pragma: allowlist secret
    assert guardado.nifs[0].principal is True
    assert guardado.nifs[0].razon_social == "Acme SL"
    assert set(OrganizationNifRepository().nifs(organizacion)) == {
        _NIF_PROPIO,
        _NIF_AJENO,
    }  # pragma: allowlist secret


def test_put_nifs_rechaza_dos_principales(tmp_db):
    _db_mod, _ = tmp_db
    owner = _user("owner-dos-principales@example.test")
    organizacion = _organizacion("Equipo dos principales", owner)

    with pytest.raises(ValueError):
        _escribir_nifs(
            organizacion,
            OrganizationNifsIn(
                nifs=[
                    OrganizationNif(nif=_NIF_PROPIO, principal=True),  # pragma: allowlist secret
                    OrganizationNif(nif=_NIF_AJENO, principal=True),  # pragma: allowlist secret
                ]
            ),
            actor_user_id=owner,
        )


def test_put_nifs_rechaza_un_nif_con_forma_invalida(tmp_db):
    _db_mod, _ = tmp_db
    owner = _user("owner-nif-invalido@example.test")
    organizacion = _organizacion("Equipo NIF inválido", owner)

    with pytest.raises(ValueError):
        _escribir_nifs(
            organizacion,
            OrganizationNifsIn(nifs=[OrganizationNif(nif="ñ$%&")]),
            actor_user_id=owner,
        )


def test_los_nifs_solo_los_ve_owner_o_admin(tmp_db):
    """Un viewer es miembro de pleno derecho y aun así no ve la identidad fiscal."""
    _db_mod, _ = tmp_db
    owner = _user("owner-nifs-rol@example.test")
    viewer = _user("viewer-nifs-rol@example.test")
    organizacion = _organizacion("Equipo NIF roles", owner)
    OrganizationRepository().add_membership(organizacion, viewer, "viewer")

    with pytest.raises(HTTPException) as rechazo:
        _get_nifs(viewer, organizacion)
    assert rechazo.value.status_code == 403

    # Y el owner de la misma organización sí, para que el 403 anterior sea del
    # rol y no de que la ruta no funcione.
    assert _get_nifs(owner, organizacion).organization_id == organizacion


def test_el_resultado_sugerido_sale_del_nif_declarado(tmp_db):
    """El criterio de S2.1 de punta a punta: NIF propio → won, ajeno → lost."""
    _db_mod, _ = tmp_db
    owner = _user("owner-resultado@example.test")
    organizacion = _organizacion("Equipo resultado", owner)

    # Sin NIFs declarados el sistema no propone nada.
    assert (
        sugerir_resultado(
            [PursuitAdjudicatario(nombre="Acme SL", nif=_NIF_PROPIO)],  # pragma: allowlist secret
            identidad_fiscal(organizacion),
        )
        is None
    )

    _escribir_nifs(
        organizacion,
        OrganizationNifsIn(
            nifs=[OrganizationNif(nif=_NIF_PROPIO, principal=True)]
        ),  # pragma: allowlist secret
        actor_user_id=owner,
    )
    identidad = identidad_fiscal(organizacion)
    assert (
        sugerir_resultado(
            [PursuitAdjudicatario(nombre="Acme SL", nif=_NIF_PROPIO)], identidad
        )  # pragma: allowlist secret
        == "won"
    )
    assert (
        sugerir_resultado(
            [PursuitAdjudicatario(nombre="Otra SL", nif=_NIF_AJENO)], identidad
        )  # pragma: allowlist secret
        == "lost"
    )


def test_el_nif_se_enlaza_con_el_empresa_id_canonico(tmp_db):
    """Sin ese enlace, «contra quién» listaría a la propia organización."""
    db_mod, _ = tmp_db
    with db_mod.connect() as conn:
        conn.execute(
            "INSERT INTO empresas (nombre_canonico, nif_canonico) VALUES (%s, %s)",
            ("ACME SL", _NIF_PROPIO),  # pragma: allowlist secret
        )
    owner = _user("owner-maestro@example.test")
    organizacion = _organizacion("Equipo maestro", owner)
    _escribir_nifs(
        organizacion,
        OrganizationNifsIn(nifs=[OrganizationNif(nif=_NIF_PROPIO)]),  # pragma: allowlist secret
        actor_user_id=owner,
    )

    leido = _leer_nifs(organizacion)
    assert leido.nifs[0].empresa_id is not None

    identidad = identidad_fiscal(organizacion)
    assert identidad.empresa_ids
    # La propia organización se reconoce por el empresa_id con el que la
    # analítica competitiva agrupa, así que puede excluirse de su ranking.
    assert identidad.reconoce(empresa_ids=list(identidad.empresa_ids)) is True


# ── Perfil de capacidad: las tres combinaciones de rol ─────────────────────


def test_owner_escribe_el_perfil_de_capacidad(tmp_db):
    _db_mod, _ = tmp_db
    owner = _user("owner-cap@example.test")
    organizacion = _organizacion("Equipo capacidad owner", owner)

    guardado = _put_capacidad(owner, organizacion, _CAPACIDAD)

    assert [c.nombre for c in guardado.certificaciones] == ["ISO/IEC 27001"]
    assert guardado.facturacion[0].importe_eur == 1200000
    assert guardado.campos_incompletos == []
    assert guardado.updated_at is not None


def test_admin_escribe_el_perfil_de_capacidad(tmp_db):
    _db_mod, _ = tmp_db
    owner = _user("owner-cap-admin@example.test")
    admin = _user("admin-cap@example.test")
    organizacion = _organizacion("Equipo capacidad admin", owner)
    OrganizationRepository().add_membership(organizacion, admin, "admin")

    guardado = _put_capacidad(admin, organizacion, _CAPACIDAD)
    assert len(guardado.referencias) == 1


def test_viewer_lee_pero_no_escribe_el_perfil_de_capacidad(tmp_db):
    _db_mod, _ = tmp_db
    owner = _user("owner-cap-viewer@example.test")
    viewer = _user("viewer-cap@example.test")
    organizacion = _organizacion("Equipo capacidad viewer", owner)
    OrganizationRepository().add_membership(organizacion, viewer, "viewer")
    _escribir_capacidad(organizacion, _CAPACIDAD)

    leido = _get_capacidad(viewer, organizacion)
    assert len(leido.perfiles_equipo) == 1

    with pytest.raises(HTTPException) as rechazo:
        _put_capacidad(viewer, organizacion, _CAPACIDAD)
    assert rechazo.value.status_code == 403


def test_el_perfil_vacio_declara_que_falta_todo(tmp_db):
    """Es lo que la UI marca para que el checklist deje de decir «desconocido»."""
    _db_mod, _ = tmp_db
    owner = _user("owner-cap-vacio@example.test")
    organizacion = _organizacion("Equipo capacidad vacía", owner)

    leido = _leer_capacidad(organizacion)
    assert set(leido.campos_incompletos) == {
        "certificaciones",
        "facturacion",
        "referencias",
        "perfiles_equipo",
    }
    assert leido.updated_at is None


def test_el_put_reemplaza_el_perfil_entero(tmp_db):
    """No acumula: lo que la pantalla manda es lo que queda."""
    _db_mod, _ = tmp_db
    owner = _user("owner-cap-reemplazo@example.test")
    organizacion = _organizacion("Equipo capacidad reemplazo", owner)
    _escribir_capacidad(organizacion, _CAPACIDAD)

    vaciado = _escribir_capacidad(
        organizacion,
        OrganizationCapabilities.model_validate(
            {"facturacion": [{"ejercicio": 2025, "importe_eur": 10}]}
        ),
    )
    assert vaciado.certificaciones == []
    assert len(vaciado.facturacion) == 1
    assert "referencias" in vaciado.campos_incompletos
