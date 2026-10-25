"""Fechas a ``timestamptz``, fase 1 (``v159``) contra Postgres.

Lo que sin motor real no prueba nada:

* la paridad de las gemelas: ``nucleo_iso_a_timestamptz`` y
  ``db.fechas_ts.a_timestamptz`` dan el mismo instante para cada formato de
  producción (si no, la verificación del backfill daría por divergente lo que
  la escritura dual escribió bien);
* que los triggers de ``v159`` mantienen la sombra con cualquier escritor, y
  que la escritura dual del upsert la mantiene en ``licitaciones``;
* que el backfill por lotes es idempotente y deja la verificación en cero;
* que la lectura dual ordena por instante donde el texto se equivoca.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

import pytest

from tests.test_unit_fechas_ts import FORMATOS_PRODUCCION


@pytest.fixture()
def db(tmp_db: Any) -> Any:
    db_mod, _ = tmp_db
    return db_mod


@pytest.fixture()
def lectura(monkeypatch: pytest.MonkeyPatch) -> Any:
    from config import settings

    def fijar(valor: bool) -> None:
        monkeypatch.setattr(settings, "FECHAS_TS_LECTURA", valor, raising=False)

    return fijar


def _lic(**kwargs: Any) -> Any:
    from db.upsert import Licitacion

    base: dict[str, Any] = {
        "id_externo": "FTS-001",
        "titulo": "Mantenimiento de la plataforma SAP del organismo",
        "organo_contratacion": "Ministerio de Hacienda",
        "fecha_publicacion": "2026-01-15",
    }
    base.update(kwargs)
    return Licitacion(**base)


def test_las_gemelas_coinciden_en_cada_formato_de_produccion(db: Any) -> None:
    from db.database import connect
    from db.fechas_ts import a_timestamptz

    with connect() as c:
        for texto, _ in FORMATOS_PRODUCCION:
            fila = c.execute("SELECT nucleo_iso_a_timestamptz(%s)", [texto]).fetchone()
            assert fila[0] == a_timestamptz(texto), texto


def test_el_upsert_escribe_las_sombras_de_licitaciones(db: Any) -> None:
    from db.database import connect
    from db.upsert import upsert_licitaciones_with_history

    upsert_licitaciones_with_history(
        [
            _lic(
                fecha_inicio="2026-02-01",
                fecha_fin="2026-12-31",
                fecha_actualizacion_fuente="2026-07-13T13:26:08.273Z",
            )
        ],
        source="test",
    )
    with connect() as c:
        fila = c.execute(
            "SELECT fecha_extraccion, fecha_extraccion_ts, fecha_inicio_ts, fecha_fin_ts, "
            "fecha_actualizacion_fuente_ts FROM licitaciones WHERE id_externo = 'FTS-001'"
        ).fetchone()
    texto, extraccion, inicio, fin, actualizacion = fila
    assert extraccion == datetime.fromisoformat(texto)
    assert inicio == datetime(2026, 2, 1, tzinfo=UTC)
    assert fin == datetime(2026, 12, 31, tzinfo=UTC)
    assert actualizacion == datetime(2026, 7, 13, 13, 26, 8, 273000, tzinfo=UTC)


def test_la_reingesta_mueve_la_sombra_con_su_texto(db: Any) -> None:
    from db.database import connect
    from db.upsert import upsert_licitaciones_with_history

    upsert_licitaciones_with_history([_lic(fecha_fin="2026-12-31")], source="test")
    upsert_licitaciones_with_history([_lic(fecha_fin=None)], source="test")
    with connect() as c:
        fila = c.execute(
            "SELECT fecha_fin, fecha_fin_ts FROM licitaciones WHERE id_externo = 'FTS-001'"
        ).fetchone()
    # `fecha_fin` no es COALESCE en el upsert: su sombra tampoco.
    assert fila == (None, None)


def test_los_triggers_mantienen_las_sombras_con_cualquier_escritor(db: Any) -> None:
    from db.database import connect
    from db.upsert import upsert_licitaciones_with_history

    upsert_licitaciones_with_history([_lic()], source="test")
    with connect() as c:
        # El DEFAULT de created_at/updated_at (v151) también pasa por el trigger.
        doc_id = c.execute(
            "INSERT INTO documentos (licitacion_id, tipo, uri, status) "
            "VALUES ('FTS-001', 'pcap', 'https://x/1', 'pending') RETURNING id"
        ).fetchone()[0]
        creado, creado_ts, fetched_ts = c.execute(
            "SELECT created_at, created_at_ts, fetched_at_ts FROM documentos WHERE id = %s",
            [doc_id],
        ).fetchone()
        assert creado_ts == datetime.fromisoformat(creado)
        assert fetched_ts is None
        c.execute(
            "UPDATE documentos SET fetched_at = '2026-09-04 09:38:20.097671+00' WHERE id = %s",
            [doc_id],
        )
        fetched_ts = c.execute(
            "SELECT fetched_at_ts FROM documentos WHERE id = %s", [doc_id]
        ).fetchone()[0]
        assert fetched_ts == datetime(2026, 9, 4, 9, 38, 20, 97671, tzinfo=UTC)

        c.execute(
            "INSERT INTO adjudicaciones (licitacion_id, nombre, fecha_adjudicacion, "
            "fecha_extraccion) VALUES ('FTS-001', 'Empresa', '2026-05-20', '2026-05-21')"
        )
        adj = c.execute(
            "SELECT fecha_adjudicacion_ts FROM adjudicaciones WHERE licitacion_id = 'FTS-001'"
        ).fetchone()[0]
        assert adj == datetime(2026, 5, 20, tzinfo=UTC)


def test_las_notificaciones_llevan_sombra_al_crearse_y_al_leerse(db: Any) -> None:
    from db.database import connect
    from db.notifications import insert_user_notification, marcar_todas_alertas_leidas
    from db.repositories.organizations import OrganizationRepository
    from db.users import create_user

    duena = create_user(
        email="fechas-ts@example.test", password_hash="x"
    )  # pragma: allowlist secret
    org = int(OrganizationRepository().create_organization("Equipo fechas", duena)["id"])

    insert_user_notification(
        user_key="u1",
        type_="deadline_7",
        title="Plazo",
        body=None,
        licitacion_id=None,
        organization_id=org,
        created_at="2026-09-04 09:38:20+00",
    )
    with connect() as c:
        creado_ts, leido_ts = c.execute(
            "SELECT created_at_ts, read_at_ts FROM user_notifications WHERE user_key = 'u1'"
        ).fetchone()
    assert creado_ts == datetime(2026, 9, 4, 9, 38, 20, tzinfo=UTC)
    assert leido_ts is None
    marcar_todas_alertas_leidas("u1")
    with connect() as c:
        leido, leido_ts = c.execute(
            "SELECT read_at, read_at_ts FROM user_notifications WHERE user_key = 'u1'"
        ).fetchone()
    assert leido is not None and leido_ts == datetime.fromisoformat(leido)


def _recorrer(funcion: Any, nombre: str) -> tuple[int, dict[str, int]]:
    from db.fechas_ts import cursor_de_texto, tabla

    desde: Any = cursor_de_texto(tabla(nombre), "")
    total, detalle = 0, {}
    while True:
        lote = funcion(nombre, desde, 2)
        if lote.hasta is None:
            return total, detalle
        total += lote.afectadas
        for clave, valor in lote.detalle.items():
            detalle[clave] = detalle.get(clave, 0) + valor
        desde = lote.hasta


def test_el_backfill_rellena_es_idempotente_y_deja_la_verificacion_en_cero(db: Any) -> None:
    from db.database import connect
    from db.fechas_ts import rellenar_lote, verificar_lote
    from db.upsert import upsert_licitaciones_with_history

    upsert_licitaciones_with_history(
        [_lic(id_externo=f"FTS-{i:03d}", fecha_inicio="2026-02-01") for i in range(5)],
        source="test",
    )
    with connect() as c:
        # Filas «anteriores a v159»: sombras vacías y un formato mezclado.
        c.execute(
            "UPDATE licitaciones SET fecha_extraccion_ts = NULL, fecha_inicio_ts = NULL, "
            "primera_extraccion = '2026-05-11 01:49:44'"
        )
    divergentes, _ = _recorrer(verificar_lote, "licitaciones")
    assert divergentes == 5

    assert _recorrer(rellenar_lote, "licitaciones")[0] == 5
    assert _recorrer(rellenar_lote, "licitaciones")[0] == 0  # idempotente

    divergentes, detalle = _recorrer(verificar_lote, "licitaciones")
    assert divergentes == 0
    assert all(v == 0 for v in detalle.values())
    with connect() as c:
        primera = c.execute("SELECT DISTINCT primera_extraccion_ts FROM licitaciones").fetchall()
    assert primera == [(datetime(2026, 5, 11, 1, 49, 44, tzinfo=UTC),)]


def test_la_verificacion_cuenta_aparte_lo_que_no_es_iso(db: Any) -> None:
    from db.database import connect
    from db.fechas_ts import verificar_lote
    from db.upsert import upsert_licitaciones_with_history

    upsert_licitaciones_with_history([_lic(fecha_inicio="31/12/2026")], source="test")
    divergentes, detalle = _recorrer(verificar_lote, "licitaciones")
    assert divergentes == 0
    assert detalle["fecha_inicio_no_iso"] == 1
    with connect() as c:
        assert c.execute("SELECT fecha_inicio_ts FROM licitaciones").fetchone()[0] is None


def test_el_historial_ordena_por_instante_con_la_lectura_dual(db: Any, lectura: Any) -> None:
    from db.database import connect
    from db.repositories.licitaciones import LicitacionRepository

    with connect() as c:
        c.executemany(
            "INSERT INTO licitaciones_history (id_externo, captured_at, source, "
            "snapshot_json, changed_fields) VALUES ('FTS-001', %s, 'test', '{}', '[]')",
            [
                ("2026-09-04T09:00:00.000000+00:00",),  # antes
                ("2026-09-04 10:00:00.000000+00",),  # después, con espacio
            ],
        )
    repo = LicitacionRepository()
    lectura(False)
    como_texto = [h["captured_at"] for h in repo.get_history("FTS-001")]
    assert como_texto[0].startswith("2026-09-04T09")  # el fallo: ' ' < 'T'
    lectura(True)
    como_instante = [h["captured_at"] for h in repo.get_history("FTS-001")]
    assert como_instante[0].startswith("2026-09-04 10")


def test_la_ultima_extraccion_lee_la_sombra(db: Any, lectura: Any) -> None:
    from db.database import connect
    from db.repositories.licitaciones import LicitacionRepository
    from db.upsert import upsert_licitaciones_with_history

    upsert_licitaciones_with_history(
        [_lic(id_externo="FTS-A"), _lic(id_externo="FTS-B")], source="test"
    )
    with connect() as c:
        c.execute(
            "UPDATE licitaciones SET fecha_extraccion = '2026-09-04T09:00:00+00:00', "
            "fecha_extraccion_ts = '2026-09-04T09:00:00+00:00' WHERE id_externo = 'FTS-A'"
        )
        c.execute(
            "UPDATE licitaciones SET fecha_extraccion = '2026-09-04 10:00:00+00', "
            "fecha_extraccion_ts = '2026-09-04T10:00:00+00:00' WHERE id_externo = 'FTS-B'"
        )
    repo = LicitacionRepository()
    lectura(False)
    assert repo.get_last_extraction_date() == "2026-09-04T09:00:00+00:00"
    lectura(True)
    assert repo.get_last_extraction_date() == "2026-09-04T10:00:00+00:00"
