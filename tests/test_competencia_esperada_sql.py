"""Competencia esperada de la ficha contra Postgres: segmentos, ventanas y paridad.

La muestra está pensada para que cada regla del repositorio tenga una fila que
la rompería si faltara:

- ``OBJ`` es el expediente consultado y **ya está adjudicado** (doce ofertas,
  a OMEGA): si se colara, la competencia «esperada» incluiría su propio
  resultado.
- ``H5`` es del mismo órgano con otra grafía y sin ``organo_id``: la lectura
  dual tiene que contarlo.
- ``DUP`` es un duplicado confirmado: no cuenta en la cuota (métrica de
  mercado), pero sí en las ofertas, que siguen la definición del score.
- ``X1`` es de otro universo, ``X2`` de otro CPV, ``X3`` cae fuera de las dos
  ventanas y ``X4`` solo fuera de la de ofertas (24 meses frente a 36).
- ``H4`` lo ganó la propia organización; ``H0`` es el contrato anterior del
  mismo objeto, que ganó ALFA: el incumbente.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

import pytest

AHORA = datetime(2026, 10, 1, 12, 0, tzinfo=UTC)
ORGANO = "Ayuntamiento de Pruebas"
ORGANO_ID = 900
NIF_PROPIO = "B99999999"  # pragma: allowlist secret


@dataclass(frozen=True)
class _Lic:
    """Una licitación de la muestra; por defecto, del órgano y del CPV-4 7226."""

    id_externo: str
    titulo: str
    publicacion: str
    importe: float
    organo: str = ORGANO
    organo_id: int | None = ORGANO_ID
    cpv: str = "72267000"
    ccaa: str = "Madrid"
    universo: str | None = None


_LICITACIONES = [
    _Lic(
        "OBJ", "Mantenimiento de la plataforma SAP S/4HANA", "2026-09-15", 400_000.0, cpv="72267100"
    ),
    _Lic(
        "H0",
        "Mantenimiento de la plataforma SAP S/4HANA del Ayuntamiento",
        "2022-01-10",
        380_000.0,
        cpv="72267100",
    ),
    _Lic("H1", "Desarrollo de aplicación móvil turística", "2025-01-10", 100_000.0),
    _Lic("H2", "Licencias de ofimática y correo", "2025-04-10", 200_000.0),
    _Lic("H3", "Auditoría de seguridad informática", "2025-07-10", 50_000.0),
    _Lic("H4", "Migración de servidores a la nube", "2025-11-10", 300_000.0),
    _Lic(
        "H5",
        "Portal de transparencia web",
        "2026-01-10",
        80_000.0,
        organo="AYUNTAMIENTO DE PRUEBAS",
        organo_id=None,
    ),
    _Lic("DUP", "Licencias de ofimática y correo (reenvío)", "2025-12-10", 500_000.0),
    _Lic("X1", "Otro universo", "2025-02-10", 90_000.0, universo="pscp_observed"),
    _Lic("X2", "Otro CPV", "2025-02-10", 90_000.0, cpv="79510000"),
    _Lic("X3", "Fuera de las dos ventanas", "2022-10-10", 90_000.0),
    _Lic("X4", "Solo en la ventana larga", "2024-04-10", 150_000.0),
    _Lic(
        "O1", "Soporte de red", "2025-03-10", 400_000.0, organo="Diputación Vecina", organo_id=None
    ),
    _Lic(
        "O2",
        "Soporte de sistemas",
        "2025-05-10",
        600_000.0,
        organo="Junta Lejana",
        organo_id=None,
        ccaa="Andalucía",
    ),
    _Lic("OBJ2", "Otro expediente abierto", "2026-09-20", 100_000.0, cpv="72267100"),
]

#: (licitación, nombre, nif, importe adjudicado, fecha, ofertas, oferta mínima)
_ADJUDICACIONES: list[tuple[str, str, str | None, float, str, int | None, float | None]] = [
    ("OBJ", "OMEGA SA", "A00000001", 300_000.0, "2026-09-20", 12, None),
    ("H0", "ALFA SA", "A10000001", 330_000.0, "2022-03-14", 3, None),
    ("H1", "ALFA SA", "A10000001", 90_000.0, "2025-03-10", 2, 85_000.0),
    ("H2", "ALFA SA", "A10000001", 170_000.0, "2025-06-10", 3, 150_000.0),
    ("H3", "BETA SL", "B20000002", 49_000.0, "2025-09-10", 1, None),
    ("H4", "NOSOTROS SL", NIF_PROPIO, 240_000.0, "2026-01-10", 4, None),
    ("H5", "GAMMA SA", "A30000003", 72_000.0, "2026-03-10", 2, None),
    ("DUP", "ALFA SA", "A10000001", 450_000.0, "2026-02-10", 5, None),
    ("X1", "OTRO UNIVERSO SA", "A40000004", 80_000.0, "2025-03-10", 7, None),
    ("X2", "OTRO CPV SA", "A50000005", 80_000.0, "2025-03-10", 7, None),
    ("X3", "VIEJA SA", "A60000006", 80_000.0, "2023-01-10", 7, None),
    ("X4", "DELTA SA", "A70000007", 120_000.0, "2024-06-10", 9, 110_000.0),
    ("O1", "EPSILON SA", "A80000008", 300_000.0, "2025-05-10", 6, None),
    ("O2", "ZETA SA", "A90000009", 450_000.0, "2025-07-10", 8, None),
]


def _sembrar() -> None:
    from db.database import connect, now_utc_iso
    from db.upsert import (
        Adjudicacion,
        Licitacion,
        replace_adjudicaciones_batch,
        upsert_licitaciones,
    )

    upsert_licitaciones(
        [
            Licitacion(
                id_externo=lic.id_externo,
                titulo=lic.titulo,
                organo_contratacion=lic.organo,
                cpv=lic.cpv,
                ccaa=lic.ccaa,
                analysis_universe=lic.universo,
                fecha_publicacion=lic.publicacion,
                importe=lic.importe,
                estado="PUB" if lic.id_externo == "OBJ2" else "ADJ",
            )
            for lic in _LICITACIONES
        ]
    )
    agrupadas: dict[str, list[Adjudicacion]] = {}
    for lic_id, nombre, nif, importe, fecha, ofertas, minima in _ADJUDICACIONES:
        agrupadas.setdefault(lic_id, []).append(
            Adjudicacion(
                licitacion_id=lic_id,
                nombre=nombre,
                nif=nif,
                importe_adjudicado=importe,
                fecha_adjudicacion=fecha,
                n_ofertas_recibidas=ofertas,
                oferta_minima=minima,
            )
        )
    _total, _descartadas, fallidas = replace_adjudicaciones_batch(agrupadas)
    assert fallidas == 0

    ahora = now_utc_iso()
    con_organo_id = [lic.id_externo for lic in _LICITACIONES if lic.organo_id is not None]
    with connect() as c:
        c.execute(
            "INSERT INTO organos (organo_id, nombre_canonico, nombre_normalizado, "
            "created_at, updated_at) VALUES (%s, %s, %s, %s, %s)",
            (ORGANO_ID, ORGANO, "ayuntamiento de pruebas", ahora, ahora),
        )
        c.execute(
            "UPDATE licitaciones SET organo_id = %s WHERE id_externo = ANY(%s)",
            (ORGANO_ID, con_organo_id),
        )
        c.execute(
            "INSERT INTO empresas (empresa_id, nif_canonico, nombre_canonico, es_ute, "
            "created_at, updated_at) VALUES (%s, %s, %s, 0, %s, %s)",
            (101, "A10000001", "ALFA CONSULTORÍA SA", ahora, ahora),
        )
        c.execute("UPDATE adjudicaciones SET empresa_id = 101 WHERE nif = 'A10000001'")
        c.execute(
            "INSERT INTO licitaciones_duplicados (licitacion_id, canonical_id, confianza, "
            "status, detectado_en) VALUES ('DUP', 'H2', 1.0, 'confirmed', %s)",
            (ahora,),
        )


def _segmento() -> Any:
    from db.repositories.competencia_esperada import Segmento

    return Segmento(
        cpv4="7226", organo_id=ORGANO_ID, organo_norm="ayuntamiento de pruebas", ccaa="Madrid"
    )


def _corte_ofertas() -> str:
    from services.analytics.scoring_signals import corte_ventana_competencia_iso

    return corte_ventana_competencia_iso(ahora=AHORA)


# ── ¿Cuántos? ───────────────────────────────────────────────────────────────


def test_ofertas_por_nivel_ex_ante_y_con_lectura_dual(tmp_db: Any) -> None:
    from db.repositories.competencia_esperada import ofertas_del_segmento

    _sembrar()
    fila = ofertas_del_segmento(_segmento(), excluir="OBJ", desde_iso=_corte_ofertas())
    # CPV-4 en 24 meses: H1-H5, DUP, O1 y O2. Ni OBJ (ex ante), ni X1-X4.
    assert fila["cpv4_adjudicados"] == 8
    assert fila["cpv4_expedientes"] == 8
    assert fila["cpv4_media"] == pytest.approx(31 / 8)
    assert (fila["cpv4_banda_1"], fila["cpv4_banda_2_4"], fila["cpv4_banda_5"]) == (1, 4, 3)
    # El órgano: H1-H4 por `organo_id`, H5 por el nombre plegado, y DUP.
    assert fila["organo_expedientes"] == 6
    assert fila["organo_media"] == pytest.approx(17 / 6)
    assert (fila["organo_banda_1"], fila["organo_banda_2_4"], fila["organo_banda_5"]) == (1, 4, 1)


def test_la_media_del_cpv_es_la_de_la_senal_del_score(tmp_db: Any) -> None:
    """La barra del Radar y el bloque no pueden contradecirse."""
    from db.repositories.aggregates import AggregateRepository
    from db.repositories.competencia_esperada import ofertas_del_segmento

    _sembrar()
    corte = _corte_ofertas()
    # OBJ2 no tiene adjudicaciones: excluirlo no cambia el universo del score.
    fila = ofertas_del_segmento(_segmento(), excluir="OBJ2", desde_iso=corte)
    por_cpv4, _global = AggregateRepository().competencia_ofertas_por_cpv4(cutoff_iso=corte)
    media_score = {str(f["cpv4"]): float(f["media_ofertas"]) for f in por_cpv4}["7226"]
    assert fila["cpv4_media"] == pytest.approx(media_score)


def test_sin_organo_conocido_el_nivel_del_organo_queda_vacio(tmp_db: Any) -> None:
    from db.repositories.competencia_esperada import Segmento, ofertas_del_segmento

    _sembrar()
    fila = ofertas_del_segmento(Segmento(cpv4="7226"), excluir="OBJ", desde_iso=_corte_ofertas())
    assert fila["organo_expedientes"] == 0
    assert fila["cpv4_expedientes"] == 8


# ── ¿Contra quién? ──────────────────────────────────────────────────────────


def test_expedientes_por_nivel_anidados_y_sin_duplicados(tmp_db: Any) -> None:
    from db.repositories.competencia_esperada import expedientes_por_nivel

    _sembrar()
    niveles = expedientes_por_nivel(_segmento(), excluir="OBJ", desde_iso="2023-10-01")
    # Órgano: H1-H5 y X4 (36 meses); DUP no (duplicado confirmado), OBJ tampoco.
    assert niveles == {"organo_cpv4": 6, "cpv4_ccaa": 7, "cpv4": 8}


def test_rivales_cuota_sobre_el_segmento_y_parte_propia(tmp_db: Any) -> None:
    from db.repositories.competencia_esperada import rivales_del_segmento

    _sembrar()
    datos = rivales_del_segmento(
        _segmento(),
        "organo_cpv4",
        excluir="OBJ",
        desde_iso="2023-10-01",
        limite=10,
        propios_nifs=[NIF_PROPIO],
    )
    total = datos["total"]
    assert total["expedientes"] == 6
    assert total["importe_total"] == pytest.approx(741_000.0)
    # La parte propia se calcula sobre el segmento entero, no sobre los rivales.
    assert (total["propia_expedientes"], total["propia_importe"]) == (1, 240_000.0)
    # Bajas por fila: 2, 10, 10, 15, 20, 20 → mediana 12,5.
    assert total["baja_mediana_pct"] == pytest.approx(12.5)
    assert total["bajas_n"] == 6
    # Oferta más baja: H1 15 %, H2 25 %, X4 26,7 % → mediana 25.
    assert total["baja_oferta_minima_mediana_pct"] == pytest.approx(25.0)
    assert total["ofertas_minimas_n"] == 3

    nombres = [(r["nombre"], r["importe"]) for r in datos["rivales"]]
    assert nombres == [
        # El nombre del maestro manda sobre la grafía de la fila.
        ("ALFA CONSULTORÍA SA", 260_000.0),
        ("NOSOTROS SL", 240_000.0),
        ("DELTA SA", 120_000.0),
        ("GAMMA SA", 72_000.0),
        ("BETA SL", 49_000.0),
    ]
    alfa = datos["rivales"][0]
    assert (alfa["empresa_id"], alfa["expedientes"], alfa["bajas_n"]) == (101, 2, 2)
    assert alfa["baja_mediana_pct"] == pytest.approx(12.5)
    assert str(alfa["ultima_adjudicacion"]).startswith("2025-06-10")


def test_rivales_sin_ninguna_adjudicacion_devuelven_el_denominador(tmp_db: Any) -> None:
    from db.repositories.competencia_esperada import Segmento, rivales_del_segmento

    _sembrar()
    datos = rivales_del_segmento(
        Segmento(cpv4="1111"), "cpv4", excluir="OBJ", desde_iso="2023-10-01", limite=5
    )
    assert datos["rivales"] == []
    assert datos["total"]["expedientes"] == 0


# ── El servicio entero ──────────────────────────────────────────────────────


def _organizacion_con_nif() -> int:
    from db.repositories.organization_nifs import OrganizationNifRepository
    from db.repositories.organizations import OrganizationRepository
    from db.users import create_user

    user_id = create_user(
        email="competencia@example.test",
        password_hash="test-hash",  # pragma: allowlist secret
    )
    organizacion = int(OrganizationRepository().ensure_personal_organization(int(user_id))["id"])
    OrganizationNifRepository().replace_all(
        organizacion, nifs=[{"nif": NIF_PROPIO, "principal": True}]
    )
    return organizacion


def test_servicio_responde_las_tres_preguntas(tmp_db: Any) -> None:
    from services.competitive.competencia_esperada import competencia_esperada

    _sembrar()
    resultado = competencia_esperada("OBJ", organization_id=_organizacion_con_nif(), ahora=AHORA)
    assert resultado is not None

    ofertas = resultado.ofertas
    assert ofertas.estimacion_nivel == "organo_cpv4"
    assert ofertas.estimacion == 3
    assert ofertas.cpv4 is not None and ofertas.cpv4.media == pytest.approx(3.88, abs=0.01)

    incumbente = resultado.incumbente
    assert incumbente is not None
    assert (incumbente.licitacion_id, incumbente.adjudicatario) == ("H0", "ALFA SA")
    assert incumbente.empresa_id == 101
    assert incumbente.metodo == "fts"
    assert not incumbente.es_propia

    rivales = resultado.rivales
    assert (rivales.nivel, rivales.muestra_suficiente) == ("organo_cpv4", True)
    assert [r.nombre for r in rivales.items] == [
        "ALFA CONSULTORÍA SA",
        "DELTA SA",
        "GAMMA SA",
        "BETA SL",
    ]
    assert [r.cuota_pct for r in rivales.items] == [35.1, 16.2, 9.7, 6.6]
    assert rivales.items[0].es_incumbente
    assert rivales.propia is not None and rivales.propia.cuota_pct == 32.4
    assert rivales.identidad_conocida

    assert resultado.puja is not None
    assert resultado.puja.baja_ganadora_mediana_pct == 12.5
    assert resultado.calculado_en.startswith("2026-10-01T12:00:00")


def test_servicio_sin_identidad_cuenta_a_todos(tmp_db: Any) -> None:
    from services.competitive.competencia_esperada import competencia_esperada

    _sembrar()
    resultado = competencia_esperada("OBJ", organization_id=None, ahora=AHORA)
    assert resultado is not None
    assert "NOSOTROS SL" in [r.nombre for r in resultado.rivales.items]
    assert resultado.rivales.propia is None
    assert not resultado.rivales.identidad_conocida


def test_servicio_expediente_inexistente(tmp_db: Any) -> None:
    from services.competitive.competencia_esperada import competencia_esperada

    assert competencia_esperada("NO-EXISTE", ahora=AHORA) is None


# ── La ruta ─────────────────────────────────────────────────────────────────


def _ctx(user_id: int, email: str) -> dict[str, Any]:
    from shared.identity import user_key_from_email

    return {
        "user_id": user_id,
        "email": email,
        "display_name": "Test User",
        "is_admin": False,
        "auth_method": "session",
        "authenticated_at": datetime.now(UTC).isoformat(),
        "user_key": user_key_from_email(email, user_id),
    }


@pytest.fixture
def cliente(client: Any, api_db: Any) -> Any:
    """`client` autenticado con un usuario propio de este módulo.

    Email propio: la respuesta se cachea por usuario y organización, y la caché
    en memoria sobrevive entre tests del mismo proceso.
    """
    from api.app import app
    from api.routes.dual_auth import require_any_auth
    from db.users import create_user

    email = "ruta-competencia@example.test"
    user_id = create_user(email=email, password_hash="test-hash")  # pragma: allowlist secret
    app.dependency_overrides[require_any_auth] = lambda: _ctx(int(user_id), email)
    try:
        yield client
    finally:
        app.dependency_overrides.pop(require_any_auth, None)


def test_ruta_devuelve_el_contrato_tipado(cliente: Any) -> None:
    _sembrar()
    with cliente as c:
        resp = c.get("/api/v1/licitaciones/OBJ/competencia-esperada")
    assert resp.status_code == 200, resp.text
    cuerpo = resp.json()
    assert cuerpo["licitacion_id"] == "OBJ"
    assert set(cuerpo) >= {"ofertas", "incumbente", "rivales", "puja", "calculado_en"}
    assert cuerpo["incumbente"]["adjudicatario"] == "ALFA SA"
    # Ningún NIF en la respuesta.
    assert "A10000001" not in resp.text
    assert NIF_PROPIO not in resp.text


def test_similares_con_predecesor_responde(cliente: Any) -> None:
    """Regresión: `/similares` respondía 500 en cuanto había un predecesor.

    Hacía `vars()` sobre un dataclass con `slots`, que no tiene `__dict__`, y
    hasta la competencia esperada ninguna pantalla lo pedía con datos. De paso
    fija que la identidad interna del adjudicatario (su NIF) no se publica.
    """
    _sembrar()
    with cliente as c:
        resp = c.get("/api/v1/licitaciones/OBJ/similares")
    assert resp.status_code == 200, resp.text
    predecesor = resp.json()["predecesor"]
    assert (predecesor["id_externo"], predecesor["adjudicatario"]) == ("H0", "ALFA SA")
    assert "adjudicatario_nif" not in predecesor
    assert "A10000001" not in resp.text


def test_ruta_404_si_no_existe(cliente: Any) -> None:
    with cliente as c:
        resp = c.get("/api/v1/licitaciones/NO-EXISTE/competencia-esperada")
    assert resp.status_code == 404


def test_ruta_resuelve_un_id_con_barra(cliente: Any) -> None:
    from db.upsert import Licitacion, upsert_licitaciones

    upsert_licitaciones(
        [
            Licitacion(
                id_externo="PA-S 2026/000058",
                titulo="Expediente con barra",
                organo_contratacion=ORGANO,
                cpv="72267100",
                estado="PUB",
            )
        ]
    )
    with cliente as c:
        resp = c.get("/api/v1/licitaciones/PA-S 2026/000058/competencia-esperada")
    assert resp.status_code == 200, resp.text
    assert resp.json()["licitacion_id"] == "PA-S 2026/000058"


def test_ruta_403_con_una_organizacion_ajena(cliente: Any) -> None:
    with cliente as c:
        resp = c.get(
            "/api/v1/licitaciones/OBJ/competencia-esperada", params={"organization_id": 999999}
        )
    assert resp.status_code == 403
