"""Plantillas de organización (F6.4): ``services.cuentas.aplicar_plantillas``.

No tiene ruta HTTP y, a 2026-09, tampoco ningún llamador en producción: ni la
activación de membresías ni la aceptación de invitaciones la invocan todavía.
Se prueba contra el servicio y Postgres para que, cuando se conecte, lo que
F6.4 promete ya esté fijado:

- se copian **contenidos, no referencias**, en los dos sentidos: la copia es
  del miembro, privada, y sobrevive a que la plantilla se borre; y el miembro
  puede borrar su copia sin tocar la plantilla, que es el criterio de
  aceptación de F6.4;
- aplicar dos veces al mismo miembro no duplica;
- una plantilla rota no deja al miembro sin las demás;
- las plantillas de otra organización no se cuelan.

Lo que **no** fija: que la idempotencia salga de la clave única de
``plantillas_aplicadas`` y no de un ``SELECT`` previo, como promete
``aplicar_plantillas``. Las dos variantes dan lo mismo en secuencia y sólo se
distinguen con dos activaciones simultáneas, que estos tests no lanzan.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any

from db.repositories.cartera import PlantillasRepository
from db.repositories.organizations import OrganizationRepository
from db.saved_filters import delete_saved_filter, list_saved_filters
from services.cuentas import aplicar_plantillas
from services.watchlist_rules import delete_rule, list_rules
from shared.identity import user_key_from_email


@dataclass(frozen=True)
class Equipo:
    owner: int
    owner_email: str
    miembro: int
    miembro_email: str
    org: int


def _user(email: str) -> int:
    from db.users import create_user

    return create_user(email=email, password_hash="test-hash")  # pragma: allowlist secret


def _equipo(sufijo: str) -> Equipo:
    owner_email = f"plantillas-owner-{sufijo}@example.test"
    miembro_email = f"plantillas-miembro-{sufijo}@example.test"
    owner = _user(owner_email)
    miembro = _user(miembro_email)
    organizations = OrganizationRepository()
    org = int(organizations.create_organization(f"Equipo {sufijo}", owner)["id"])
    organizations.add_membership(org, miembro, "member")
    return Equipo(owner, owner_email, miembro, miembro_email, org)


def _plantilla(org: int, tipo: str, nombre: str, contenido: dict[str, Any], autor: int) -> int:
    return PlantillasRepository().create(
        organization_id=org, tipo=tipo, nombre=nombre, contenido=contenido, user_id=autor
    )


def _reglas(email: str, user_id: int, org: int) -> list[tuple[Any, ...]]:
    return [
        (r.nombre, r.keyword, r.ccaa, r.visibility, r.organization_id)
        for r in list_rules(user_key_from_email(email, user_id), org)
    ]


def _vistas(email: str, user_id: int, org: int) -> list[tuple[Any, ...]]:
    return [
        (v["name"], json.loads(v["filters_json"]), v["visibility"])
        for v in list_saved_filters(user_key_from_email(email, user_id), org)
    ]


def _copias_registradas(org: int, user_id: int) -> list[int]:
    from db.database import connect

    with connect() as conn:
        filas = conn.execute(
            "SELECT copias FROM plantillas_aplicadas WHERE organization_id = %s AND user_id = %s",
            (org, user_id),
        ).fetchall()
    return [int(f[0]) for f in filas]


def test_copia_reglas_y_vistas_como_objetos_privados_del_miembro(tmp_db: object) -> None:
    """La plantilla dice «del equipo»; la copia tiene que ser del miembro.

    La regla plantilla lleva ``visibility: organization`` a propósito: si la
    copia la respetara, todo el equipo vería la regla del recién llegado y
    editarla se la cambiaría a los demás.
    """
    e = _equipo("copia")
    _plantilla(
        e.org,
        "regla",
        "SAP en Madrid",
        {
            "nombre": "SAP en Madrid",
            "keyword": "sap",
            "ccaa": "Madrid",
            "visibility": "organization",
        },
        e.owner,
    )
    _plantilla(
        e.org,
        "vista",
        "Radar SAP",
        {"nombre": "Radar SAP", "criterio": {"q": "sap", "ccaa": "Madrid"}},
        e.owner,
    )
    _plantilla(e.org, "etiqueta", "Q4", {"nombre": "Q4"}, e.owner)

    copias = aplicar_plantillas(e.org, e.miembro)

    # La etiqueta cuenta aunque no se duplica: ya es de la organización.
    assert copias == 3
    assert _copias_registradas(e.org, e.miembro) == [3]
    assert _reglas(e.miembro_email, e.miembro, e.org) == [
        ("SAP en Madrid", "sap", "Madrid", "private", e.org)
    ]
    assert _vistas(e.miembro_email, e.miembro, e.org) == [
        ("Radar SAP", {"q": "sap", "ccaa": "Madrid"}, "private")
    ]
    # Privadas de verdad: el owner, que creó las plantillas, no ve las copias.
    assert _reglas(e.owner_email, e.owner, e.org) == []
    assert _vistas(e.owner_email, e.owner, e.org) == []

    # Contenidos, no referencias: borrar las plantillas no toca las copias.
    plantillas = PlantillasRepository()
    for plantilla in plantillas.list_for_organization(e.org):
        assert plantillas.delete(e.org, int(plantilla["id"]))
    assert plantillas.list_for_organization(e.org) == []
    assert [r[0] for r in _reglas(e.miembro_email, e.miembro, e.org)] == ["SAP en Madrid"]
    assert [v[0] for v in _vistas(e.miembro_email, e.miembro, e.org)] == ["Radar SAP"]


def test_el_miembro_borra_sus_copias_y_la_plantilla_sigue_intacta(tmp_db: object) -> None:
    """La otra mitad de «copias, no referencias» (aceptación de F6.4).

    Borrar la regla y la vista copiadas no puede llevarse la plantilla ni
    cambiar su contenido, y quien se active después tiene que recibirla igual.
    """
    e = _equipo("borra")
    regla = {"nombre": "ERP en Galicia", "keyword": "erp", "ccaa": "Galicia"}
    vista = {"nombre": "Radar ERP", "criterio": {"q": "erp"}}
    _plantilla(e.org, "regla", "ERP en Galicia", regla, e.owner)
    _plantilla(e.org, "vista", "Radar ERP", vista, e.owner)
    antes = PlantillasRepository().list_for_organization(e.org)
    assert aplicar_plantillas(e.org, e.miembro) == 2

    user_key = user_key_from_email(e.miembro_email, e.miembro)
    [regla_copiada] = list_rules(user_key, e.org)
    [vista_copiada] = list_saved_filters(user_key, e.org)
    assert regla_copiada.id is not None
    assert delete_rule(user_key, regla_copiada.id, e.org)
    assert delete_saved_filter(int(vista_copiada["id"]), user_key=user_key, organization_id=e.org)
    assert _reglas(e.miembro_email, e.miembro, e.org) == []
    assert _vistas(e.miembro_email, e.miembro, e.org) == []

    assert PlantillasRepository().list_for_organization(e.org) == antes
    recien_llegado_email = "plantillas-nuevo-borra@example.test"
    recien_llegado = _user(recien_llegado_email)
    OrganizationRepository().add_membership(e.org, recien_llegado, "member")
    assert aplicar_plantillas(e.org, recien_llegado) == 2
    assert [r[0] for r in _reglas(recien_llegado_email, recien_llegado, e.org)] == [
        "ERP en Galicia"
    ]
    assert [v[0] for v in _vistas(recien_llegado_email, recien_llegado, e.org)] == ["Radar ERP"]


def test_aplicar_dos_veces_al_mismo_miembro_no_duplica(tmp_db: object) -> None:
    e = _equipo("idem")
    _plantilla(e.org, "regla", "ERP", {"nombre": "ERP", "keyword": "erp"}, e.owner)

    assert aplicar_plantillas(e.org, e.miembro) == 1
    assert aplicar_plantillas(e.org, e.miembro) == 0

    assert len(_reglas(e.miembro_email, e.miembro, e.org)) == 1
    # El segundo intento no pisa el recuento del primero con su cero.
    assert _copias_registradas(e.org, e.miembro) == [1]


def test_una_plantilla_rota_no_deja_al_miembro_sin_las_demas(tmp_db: object) -> None:
    e = _equipo("rota")
    _plantilla(e.org, "regla", "Rota", {"nombre": "Rota", "frequency": "cada-hora"}, e.owner)
    _plantilla(e.org, "regla", "Buena", {"nombre": "Buena", "keyword": "hana"}, e.owner)
    # Un tipo que este build no conoce se ignora sin romper ni contar.
    _plantilla(e.org, "informe", "Futuro", {"nombre": "Futuro"}, e.owner)

    copias = aplicar_plantillas(e.org, e.miembro)

    assert copias == 1
    assert _copias_registradas(e.org, e.miembro) == [1]
    assert [r[0] for r in _reglas(e.miembro_email, e.miembro, e.org)] == ["Buena"]


def test_sin_plantillas_se_registra_la_aplicacion_con_cero_copias(tmp_db: object) -> None:
    """Registrar el cero es lo que impide reaplicar cuando luego haya plantillas.

    F6.4 habla de un miembro **recién activado**: quien ya estaba cuando el
    equipo creó sus plantillas no las recibe a posteriori por este camino.
    """
    e = _equipo("vacio")

    assert aplicar_plantillas(e.org, e.miembro) == 0
    assert _copias_registradas(e.org, e.miembro) == [0]

    _plantilla(e.org, "regla", "Tardía", {"nombre": "Tardía"}, e.owner)
    assert aplicar_plantillas(e.org, e.miembro) == 0
    assert _reglas(e.miembro_email, e.miembro, e.org) == []


def test_las_plantillas_de_otra_organizacion_no_se_copian(tmp_db: object) -> None:
    e = _equipo("propio")
    ajeno = _equipo("ajeno")
    _plantilla(e.org, "regla", "Propia", {"nombre": "Propia", "keyword": "sap"}, e.owner)
    _plantilla(ajeno.org, "regla", "Ajena", {"nombre": "Ajena", "keyword": "oracle"}, ajeno.owner)
    _plantilla(ajeno.org, "vista", "Ajena", {"nombre": "Ajena", "criterio": {}}, ajeno.owner)

    assert aplicar_plantillas(e.org, e.miembro) == 1

    assert [r[0] for r in _reglas(e.miembro_email, e.miembro, e.org)] == ["Propia"]
    assert _vistas(e.miembro_email, e.miembro, e.org) == []


def test_la_idempotencia_es_por_organizacion_y_miembro(tmp_db: object) -> None:
    """Haber recibido las plantillas de un equipo no bloquea las de otro."""
    e = _equipo("primero")
    otro = _equipo("segundo")
    OrganizationRepository().add_membership(otro.org, e.miembro, "member")
    _plantilla(e.org, "regla", "Del primero", {"nombre": "Del primero"}, e.owner)
    _plantilla(otro.org, "regla", "Del segundo", {"nombre": "Del segundo"}, otro.owner)

    assert aplicar_plantillas(e.org, e.miembro) == 1
    assert aplicar_plantillas(otro.org, e.miembro) == 1

    assert [r[0] for r in _reglas(e.miembro_email, e.miembro, e.org)] == ["Del primero"]
    assert [r[0] for r in _reglas(e.miembro_email, e.miembro, otro.org)] == ["Del segundo"]
