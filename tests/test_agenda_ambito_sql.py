"""El ámbito de la agenda, ejecutado contra Postgres: pursuits y tareas.

La barra de ámbito de «Mi Pipeline» manda **varios** valores por dimensión
(``tecnologia=SAP,Oracle``) y la agenda los resuelve con un OR dentro de cada
una. Eso lo arma ``db.repositories.base.ambito_agenda_sql``, que
``tests/test_pursuits_agenda.py`` cubre como texto; aquí se ejecuta, que es lo
único que demuestra que el SQL es válido y que las dos consultas —la de
oportunidades y la de tareas— ven **el mismo universo**.

Las dos se comprueban con el mismo cuerpo parametrizado a propósito: el día que
una de ellas cambie de criterio, la otra la delata. Ése era el fallo concreto
que motivó el helper: con ``l.tecnologia = %s`` el filtro por SAP escondía los
expedientes multi-tecnología (``"SAP,Salesforce"``), y el mismo ámbito daba
recuentos distintos según por qué superficie entrara.
"""

from __future__ import annotations

from collections.abc import Callable, Iterator
from dataclasses import dataclass
from typing import Any

import pytest

from db.repositories.organizations import OrganizationRepository
from db.repositories.pursuit_tasks import PursuitTasksRepository
from db.repositories.pursuits import PursuitRepository
from shared.dto import PursuitCreate

_SAP = "LIC-AMB-SAP"
_MULTI = "LIC-AMB-MULTI"
_ORACLE = "LIC-AMB-ORACLE"
_SIN_DATO = "LIC-AMB-SIN-DATO"
_CERRADA = "LIC-AMB-CERRADA"


def _user(email: str) -> int:
    from db.users import create_user

    return create_user(email=email, password_hash="test-hash")  # pragma: allowlist secret


def _licitacion(id_externo: str, *, tecnologia: str | None, ccaa: str | None) -> None:
    from db.database import connect

    with connect() as conn:
        conn.execute(
            "INSERT INTO licitaciones "
            "(id_externo, titulo, organo_contratacion, tecnologia, ccaa, importe, url, "
            " fecha_limite, fecha_extraccion) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)",
            (
                id_externo,
                f"Expediente {id_externo}",
                "Xunta de Galicia",
                tecnologia,
                ccaa,
                120_000.0,
                f"https://example.test/{id_externo}",
                "2026-11-15T10:00:00+00:00",
                "2026-09-01T10:00:00+00:00",
            ),
        )


@dataclass(frozen=True)
class _Escenario:
    owner: int
    otro: int
    organizacion: int


@pytest.fixture()
def escenario(tmp_db: Any) -> Iterator[_Escenario]:
    """Cuatro oportunidades abiertas con una tarea cada una, y una cerrada.

    ``_MULTI`` es la fila que importa: su ``tecnologia`` es ``"SAP,Salesforce"``
    —lo que de verdad guarda la columna— y tiene que aparecer tanto filtrando
    por SAP como por Salesforce.
    """
    from services.pursuits import create_pursuit

    owner = _user("owner-ambito@example.test")
    otro = _user("otro-ambito@example.test")
    repo = OrganizationRepository()
    organizacion = int(repo.create_organization("Equipo ámbito", owner)["id"])
    repo.add_membership(organizacion, otro, "member")

    _licitacion(_SAP, tecnologia="SAP", ccaa="Galicia")
    _licitacion(_MULTI, tecnologia="SAP,Salesforce", ccaa="Madrid")
    _licitacion(_ORACLE, tecnologia="Oracle", ccaa="Galicia")
    _licitacion(_SIN_DATO, tecnologia=None, ccaa=None)
    _licitacion(_CERRADA, tecnologia="SAP", ccaa="Galicia")

    tareas = PursuitTasksRepository()
    for licitacion_id in (_SAP, _MULTI, _ORACLE, _SIN_DATO, _CERRADA):
        # `_ORACLE` es del otro miembro: sirve para el filtro por responsable.
        responsable = otro if licitacion_id == _ORACLE else owner
        creado, _nuevo = create_pursuit(
            owner,
            PursuitCreate(
                licitacion_id=licitacion_id,
                organization_id=organizacion,
                responsible_user_id=responsable,
            ),
        )
        tareas.create(
            pursuit_id=int(creado.id),
            organization_id=organizacion,
            titulo=f"Preparar {licitacion_id}",
            vence="2026-10-01",
        )

    from db.database import connect

    with connect() as conn:
        conn.execute(
            "UPDATE pursuits SET status = 'lost' WHERE organization_id = %s AND licitacion_id = %s",
            (organizacion, _CERRADA),
        )
    yield _Escenario(owner, otro, organizacion)


@pytest.fixture(params=["pursuits", "tareas"])
def consulta(request: pytest.FixtureRequest, escenario: _Escenario) -> Callable[..., list[str]]:
    """Los expedientes que devuelve cada una de las dos consultas de la agenda."""
    repo: Any = PursuitRepository() if request.param == "pursuits" else PursuitTasksRepository()

    def _ids(**ambito: Any) -> list[str]:
        filas, _truncado = repo.agenda_rows(escenario.organizacion, **ambito)
        return sorted(str(fila["licitacion_id"]) for fila in filas)

    return _ids


# ── El mismo universo para oportunidades y tareas ─────────────────────────


def test_sin_ambito_entran_todas_las_abiertas(consulta: Callable[..., list[str]]) -> None:
    """La cerrada no: ni ella ni su tarea son trabajo por hacer."""
    assert consulta() == sorted([_SAP, _MULTI, _ORACLE, _SIN_DATO])


def test_la_tecnologia_encuentra_los_expedientes_multi_tecnologia(
    consulta: Callable[..., list[str]],
) -> None:
    """El caso que la igualdad escondía: ``"SAP,Salesforce"`` es también SAP."""
    assert consulta(tecnologias=["SAP"]) == sorted([_SAP, _MULTI])
    assert consulta(tecnologias=["Salesforce"]) == [_MULTI]


def test_varias_tecnologias_son_un_or(consulta: Callable[..., list[str]]) -> None:
    assert consulta(tecnologias=["Oracle", "Salesforce"]) == sorted([_ORACLE, _MULTI])


def test_una_sola_tecnologia_sigue_funcionando(consulta: Callable[..., list[str]]) -> None:
    """La barra manda un valor mucho más a menudo que cinco."""
    assert consulta(tecnologias=["Oracle"]) == [_ORACLE]


def test_varias_ccaa_son_un_or(consulta: Callable[..., list[str]]) -> None:
    assert consulta(ccaas=["Galicia"]) == sorted([_SAP, _ORACLE])
    assert consulta(ccaas=["Galicia", "Madrid"]) == sorted([_SAP, _MULTI, _ORACLE])


def test_las_dos_dimensiones_se_cruzan(consulta: Callable[..., list[str]]) -> None:
    """OR dentro de cada dimensión, AND entre ellas."""
    assert consulta(tecnologias=["SAP"], ccaas=["Madrid"]) == [_MULTI]


def test_el_expediente_sin_el_dato_queda_fuera_del_filtro(
    consulta: Callable[..., list[str]],
) -> None:
    """Aquí el universo es el mercado: sin tecnología declarada no se afirma
    que sea SAP. (Los contratos propios de la cartera siguen otra regla, y la
    fija ``tests/test_pursuits_agenda.py``.)"""
    assert _SIN_DATO not in consulta(tecnologias=["SAP"])
    assert _SIN_DATO not in consulta(ccaas=["Galicia"])


def test_el_responsable_acota_las_dos_consultas(
    consulta: Callable[..., list[str]], escenario: _Escenario
) -> None:
    """«Solo mías» se mide por el responsable de la **oportunidad**."""
    assert consulta(responsible_user_id=escenario.otro) == [_ORACLE]
    assert _ORACLE not in consulta(responsible_user_id=escenario.owner)


def test_el_tope_se_declara_en_vez_de_presentarse_como_el_total(escenario: _Escenario) -> None:
    """``(filas, truncado)``: un corte silencioso daría KPIs bajos sin avisar."""
    repo: Any = PursuitRepository()
    filas, truncado = repo.agenda_rows(escenario.organizacion, limit=2)
    assert (len(filas), truncado) == (2, True)

    completas, sin_cortar = repo.agenda_rows(escenario.organizacion, limit=50)
    assert (len(completas), sin_cortar) == (4, False)


# ── Lo que sólo mira la consulta de tareas ────────────────────────────────


def test_la_fila_de_una_tarea_trae_los_campos_de_su_oportunidad(
    escenario: _Escenario,
) -> None:
    """Con los **mismos alias** que la consulta de pursuits: el servicio
    construye las dos filas de agenda con el mismo constructor, y un alias
    distinto sería un campo vacío sin que nada avisara."""
    filas, _truncado = PursuitTasksRepository().agenda_rows(escenario.organizacion)
    fila = next(f for f in filas if str(f["licitacion_id"]) == _MULTI)

    assert fila["tarea_texto"] == f"Preparar {_MULTI}"
    assert str(fila["tarea_vence"])[:10] == "2026-10-01"
    assert fila["tarea_estado"] == "pendiente"
    assert fila["titulo"] == f"Expediente {_MULTI}"
    assert fila["organo"] == "Xunta de Galicia"
    assert (fila["ccaa"], fila["tecnologia"]) == ("Madrid", "SAP,Salesforce")
    assert fila["importe_eur"] == 120_000.0
    assert fila["url"] == f"https://example.test/{_MULTI}"
    assert int(fila["version"]) >= 1
    assert fila["responsible_user_id"] == escenario.owner


def test_una_tarea_cerrada_o_borrada_deja_de_ser_trabajo_pendiente(
    escenario: _Escenario,
) -> None:
    repo = PursuitTasksRepository()
    filas, _t = repo.agenda_rows(escenario.organizacion)
    por_expediente = {str(f["licitacion_id"]): int(f["tarea_id"]) for f in filas}

    repo.update(escenario.organizacion, por_expediente[_SAP], estado="hecha")
    repo.delete(escenario.organizacion, por_expediente[_ORACLE])

    quedan, _t2 = repo.agenda_rows(escenario.organizacion)
    assert sorted(str(f["licitacion_id"]) for f in quedan) == sorted([_MULTI, _SIN_DATO])


def test_las_tareas_sin_fecha_van_al_final(escenario: _Escenario) -> None:
    """Mismo criterio que la agenda: sin vencimiento no es «hoy»."""
    repo = PursuitTasksRepository()
    filas, _t = repo.agenda_rows(escenario.organizacion)
    sin_fecha = next(int(f["tarea_id"]) for f in filas if str(f["licitacion_id"]) == _SAP)
    repo.update(escenario.organizacion, sin_fecha, limpiar_vence=True)

    ordenadas, _t2 = repo.agenda_rows(escenario.organizacion)

    assert int(ordenadas[-1]["tarea_id"]) == sin_fecha
    assert ordenadas[-1]["tarea_vence"] is None
