"""Tests del dedupe cross-fuente (Fase 5.2, RFC 20260611-1)."""

from __future__ import annotations

import pytest

from services.dedupe import (
    detect_duplicates,
    exclude_duplicados_sql,
    match_key,
    medir_solape,
    natural_expediente,
    normalize_organo,
    resolve_pending,
    review_pending,
)


@pytest.fixture()
def db(tmp_db):
    db_mod, _ = tmp_db
    return db_mod


def _insert_lic(c, id_externo, *, fuente, organo, cpv, fecha_pub, extraccion):
    c.execute(
        "INSERT INTO licitaciones (id_externo, titulo, organo_contratacion, cpv, "
        " fecha_publicacion, fuente, fecha_extraccion) VALUES (%s, %s, %s, %s, %s, %s, %s)",
        (id_externo, f"Contrato {id_externo}", organo, cpv, fecha_pub, fuente, extraccion),
    )


def _insert_adj(c, lic_id, nombre, importe):
    c.execute(
        "INSERT INTO adjudicaciones (licitacion_id, nombre, importe_adjudicado, "
        " fecha_adjudicacion, fecha_extraccion) VALUES (%s, %s, %s, %s, CURRENT_TIMESTAMP)",
        (lic_id, nombre, importe, "2026-05-01"),
    )


# ---------------------------------------------------------------------------
# Helpers puros
# ---------------------------------------------------------------------------


def test_normalize_organo_pliega_acentos_y_formas():
    assert normalize_organo("Generalitat de Catalunya, S.A.") == "generalitat de catalunya"
    assert normalize_organo("GENERALITAT DE CATALUNYA") == "generalitat de catalunya"
    assert normalize_organo(None) is None


def test_natural_expediente_quita_namespace():
    assert natural_expediente("pscp:CTTI-2026-1") == "CTTI-2026-1"
    assert natural_expediente("EXP-PLACSP-7") == "EXP-PLACSP-7"  # placsp sin prefijo


def test_match_key():
    assert match_key("Òrgan A", "EXP-1", "72000000") == "organ a|EXP-1|7200"
    assert match_key("Òrgan A", "EXP-1", None) == "organ a|EXP-1|"
    assert match_key(None, "EXP-1", "72000000") is None


# ---------------------------------------------------------------------------
# Detección sobre par sintético PSCP↔PLACSP (acceptance del RFC)
# ---------------------------------------------------------------------------


def test_detect_marca_duplicado_exacto_y_excluye_en_analytics(db):
    from db.database import connect
    from services.competitive.mercado import cuota_mercado

    with connect() as c:
        _insert_lic(
            c,
            "EXP-2026-42",
            fuente="placsp",
            organo="Departament de Salut",
            cpv="72000000",
            fecha_pub="2026-05-01",
            extraccion="2026-05-02T00:00:00",
        )
        _insert_lic(
            c,
            "pscp:EXP-2026-42",
            fuente="pscp",
            organo="DEPARTAMENT DE SALUT",
            cpv="72004000",
            fecha_pub="2026-05-03",
            extraccion="2026-05-04T00:00:00",
        )
        _insert_adj(c, "EXP-2026-42", "Acme Consulting SL", 100000.0)
        _insert_adj(c, "pscp:EXP-2026-42", "Acme Consulting SL", 100000.0)

    result = detect_duplicates(fuente="pscp")

    assert result.evaluadas == 1
    assert result.confirmados == 1  # mismo órgano + expediente + CPV4 (7200)
    with connect() as c:
        row = c.execute(
            "SELECT canonical_id, confianza, status FROM licitaciones_duplicados "
            "WHERE licitacion_id = 'pscp:EXP-2026-42'"
        ).fetchone()
    assert row == ("EXP-2026-42", 1.0, "confirmed")  # canónico = PLACSP

    # Las métricas competitivas cuentan el contrato una sola vez
    cuota = cuota_mercado()
    acme = [r for r in cuota if r["empresa"] == "Acme Consulting SL"]
    assert acme and acme[0]["contratos"] == 1
    assert acme[0]["importe"] == 100000.0

    solape = medir_solape("pscp", "placsp")
    assert solape["solapadas"] == 1 and solape["solape_pct"] == 100.0


def test_detect_cpv_distinto_va_a_revision(db):
    from db.database import connect

    with connect() as c:
        _insert_lic(
            c,
            "EXP-9",
            fuente="placsp",
            organo="Ajuntament de Girona",
            cpv="48000000",
            fecha_pub="2026-05-01",
            extraccion="2026-05-02T00:00:00",
        )
        _insert_lic(
            c,
            "pscp:EXP-9",
            fuente="pscp",
            organo="Ajuntament de Girona",
            cpv="72000000",
            fecha_pub="2026-05-01",
            extraccion="2026-05-02T00:00:00",
        )

    result = detect_duplicates(fuente="pscp")

    assert result.pendientes == 1 and result.confirmados == 0
    pendientes = review_pending()
    assert len(pendientes) == 1
    assert pendientes[0]["confianza"] == 0.8

    # Pending NO se excluye de analytics hasta confirmación humana
    from db.database import connect_read

    with connect_read() as c:
        sql = f"SELECT COUNT(*) FROM licitaciones l WHERE {exclude_duplicados_sql()}"  # noqa: S608
        assert c.execute(sql).fetchone()[0] == 2

    assert resolve_pending("pscp:EXP-9", accept=True, resolved_by="test")
    with connect_read() as c:
        assert c.execute(sql).fetchone()[0] == 1
    assert review_pending() == []


def test_detect_es_incremental_por_cursor(db):
    from db.database import connect

    with connect() as c:
        _insert_lic(
            c,
            "EXP-1",
            fuente="placsp",
            organo="Organo X",
            cpv="72000000",
            fecha_pub="2026-05-01",
            extraccion="2026-05-02T00:00:00",
        )
        _insert_lic(
            c,
            "pscp:EXP-1",
            fuente="pscp",
            organo="Organo X",
            cpv="72000000",
            fecha_pub="2026-05-01",
            extraccion="2026-05-02T00:00:00",
        )

    first = detect_duplicates(fuente="pscp")
    second = detect_duplicates(fuente="pscp")

    assert first.evaluadas == 1 and first.confirmados == 1
    assert second.evaluadas == 0  # watermark avanzado: no re-evalúa


def test_detect_sin_match_no_marca(db):
    from db.database import connect

    with connect() as c:
        _insert_lic(
            c,
            "pscp:EXP-solo",
            fuente="pscp",
            organo="Organo Y",
            cpv="72000000",
            fecha_pub="2026-05-01",
            extraccion="2026-05-02T00:00:00",
        )

    result = detect_duplicates(fuente="pscp")

    assert result.evaluadas == 1
    assert result.confirmados == 0 and result.pendientes == 0
    with connect() as c:
        assert c.execute("SELECT COUNT(*) FROM licitaciones_duplicados").fetchone()[0] == 0


# ---------------------------------------------------------------------------
# El índice de candidatas se acota por expediente (no materializa el corpus)
# ---------------------------------------------------------------------------


def test_indice_de_candidatas_solo_trae_los_expedientes_pedidos(db):
    """El prefiltro SQL devuelve otras fuentes y sólo los expedientes pedidos.

    Cubre las dos ramas de ``_EXPEDIENTE_NATURAL_SQL``: el ``id_externo``
    namespaceado (``pscp:X``) y el que no lo está (PLACSP), que es el gemelo del
    ``partition(':')`` de :func:`natural_expediente`.
    """
    from db.database import connect
    from db.repositories.dedupe import iter_filas_de_otras_fuentes_por_expediente

    with connect() as c:
        _insert_lic(
            c,
            "EXP-PEDIDO",
            fuente="placsp",
            organo="Organo Z",
            cpv="72000000",
            fecha_pub="2026-05-01",
            extraccion="2026-05-02T00:00:00",
        )
        _insert_lic(
            c,
            "ted:EXP-PEDIDO",
            fuente="ted",
            organo="Organo Z",
            cpv="72000000",
            fecha_pub="2026-05-01",
            extraccion="2026-05-02T00:00:00",
        )
        _insert_lic(
            c,
            "pscp:EXP-PEDIDO",
            fuente="pscp",
            organo="Organo Z",
            cpv="72000000",
            fecha_pub="2026-05-01",
            extraccion="2026-05-02T00:00:00",
        )
        _insert_lic(
            c,
            "EXP-AJENO",
            fuente="placsp",
            organo="Organo Z",
            cpv="72000000",
            fecha_pub="2026-05-01",
            extraccion="2026-05-02T00:00:00",
        )

    traidas = {
        row["id_externo"]
        for row in iter_filas_de_otras_fuentes_por_expediente("pscp", ["EXP-PEDIDO"])
    }

    # La propia fuente queda fuera (la aporta el lado de las filas nuevas) y el
    # expediente no pedido tampoco viaja: es justo lo que el SELECT sin LIMIT
    # traía —el corpus entero— en cada ingesta.
    assert traidas == {"EXP-PEDIDO", "ted:EXP-PEDIDO"}
    assert list(iter_filas_de_otras_fuentes_por_expediente("pscp", [])) == []


def test_detect_pide_solo_los_expedientes_de_las_filas_nuevas(db, monkeypatch):
    """Regresión: el índice se acota, no se materializa ``fuente != %s`` entero."""
    from db.database import connect
    from db.repositories import dedupe as dedupe_repo

    with connect() as c:
        _insert_lic(
            c,
            "EXP-NUEVA",
            fuente="placsp",
            organo="Organo W",
            cpv="72000000",
            fecha_pub="2026-05-01",
            extraccion="2026-05-02T00:00:00",
        )
        _insert_lic(
            c,
            "pscp:EXP-NUEVA",
            fuente="pscp",
            organo="Organo W",
            cpv="72000000",
            fecha_pub="2026-05-01",
            extraccion="2026-05-02T00:00:00",
        )

    original = dedupe_repo.iter_filas_de_otras_fuentes_por_expediente
    pedidos: list[list[str]] = []

    def _spy(fuente, expedientes):
        pedidos.append(list(expedientes))
        return original(fuente, expedientes)

    monkeypatch.setattr(dedupe_repo, "iter_filas_de_otras_fuentes_por_expediente", _spy)

    result = detect_duplicates(fuente="pscp")

    assert result.confirmados == 1
    assert pedidos == [["EXP-NUEVA"]]


# ---------------------------------------------------------------------------
# Dedupe intra-run del runner de conectores (`mejor_recencia`)
#
# Vive aquí y no en test_connectors.py porque es el mismo problema que el resto
# del módulo: colapsar dos filas que describen el mismo contrato quedándose con
# la buena. Lo que cambia es el ámbito — dentro de un run, antes de escribir.
# ---------------------------------------------------------------------------


class _ConectorDosFases:
    """Emite dos veces el MISMO ``id_externo``, como PSCP: una fila por fase.

    ``recencias`` permite probar el caso real (PSCP no poblaba
    ``fecha_actualizacion_fuente``, así que ambas venían vacías) y el contraste
    con una fuente que sí la puebla.
    """

    def __init__(
        self,
        *,
        stream_asc: bool,
        recencias: tuple[str | None, str | None] = (None, None),
    ) -> None:
        self.source_id = "fake_fases"
        self.cursor_advances_incrementally = stream_asc
        self.recencias = recencias

    def fetch(self, cursor):
        from scraper.connectors.base import RawNotice

        for estado, recencia in zip(("publicado", "adjudicada"), self.recencias, strict=True):
            yield RawNotice(
                natural_id="EXP-FASES", payload={"estado": estado, "recencia": recencia}
            )

    def parse(self, raw):
        from db.upsert import Licitacion
        from scraper.connectors.base import ParsedTender

        return ParsedTender(
            licitacion=Licitacion(
                id_externo=f"{self.source_id}:{raw.natural_id}",
                titulo="Contracte amb dues fases",
                fuente=self.source_id,
                estado=raw.payload["estado"],
                fecha_publicacion="2026-05-01",
                fecha_actualizacion_fuente=raw.payload["recencia"],
            )
        )

    def new_cursor(self):
        return None


def _estado_persistido(lic_id: str) -> str | None:
    from db.database import connect_read

    with connect_read() as c:
        row = c.execute(
            "SELECT estado FROM licitaciones WHERE id_externo = %s", (lic_id,)
        ).fetchone()
    return row[0] if row else None


def test_runner_feed_asc_sin_recencia_conserva_la_ultima_fase(db):
    """Sin recencia en NINGÚN lado, en un feed ASC gana la última vista.

    Es el bug de PSCP: ``"" <= ""`` se cumple siempre, así que la primera
    aparición ganaba y se descartaban todas las posteriores. Con el feed
    ``:updated_at ASC`` y una fila por fase, lo que sobrevivía era la fase MÁS
    ANTIGUA del expediente — el estado retrocedía a cada backfill por lotes.
    """
    from scraper.connectors.base import run_connector

    result = run_connector(_ConectorDosFases(stream_asc=True))

    assert result.parsed == 2 and result.nuevas == 1
    assert _estado_persistido("fake_fases:EXP-FASES") == "adjudicada"


def test_runner_feed_newest_first_sin_recencia_conserva_la_primera(db):
    """En un feed newest-first la primera vista ES la más reciente: no se pisa."""
    from scraper.connectors.base import run_connector

    run_connector(_ConectorDosFases(stream_asc=False))

    assert _estado_persistido("fake_fases:EXP-FASES") == "publicado"


def test_runner_con_recencia_manda_la_fecha_y_no_el_orden(db):
    """Cuando la fuente sí puebla la recencia, decide ella aunque llegue última."""
    from scraper.connectors.base import run_connector

    run_connector(_ConectorDosFases(stream_asc=False, recencias=("2026-05-01", "2026-06-01")))

    assert _estado_persistido("fake_fases:EXP-FASES") == "adjudicada"


def test_pscp_parse_puebla_la_recencia_con_el_updated_at():
    """PSCP arrastra ``:updated_at`` al modelo: sin él las fases no se ordenan."""
    from scraper.connectors.base import RawNotice
    from scraper.connectors.pscp import PscpConnector

    conector = PscpConnector(dataset_id="ybgg-dgi6", domain="ejemplo.cat", app_token="")
    record = {
        "codi_expedient": "EXP-1",
        "objecte_contracte": "Servei de manteniment",
        ":updated_at": "2026-06-11T10:23:45.000",
    }

    parsed = conector.parse(RawNotice(natural_id="EXP-1", payload=record))
    assert parsed is not None
    assert parsed.licitacion.fecha_actualizacion_fuente == "2026-06-11T10:23:45.000"

    # Un `:updated_at` que no empiece por YYYY-MM-DD no se escribe: violaría el
    # CHECK ck_licitaciones_fecha_actualizacion_fuente_iso (v59) y con él caería
    # el INSERT del lote entero, no sólo el de esta fila.
    raro = dict(record)
    raro[":updated_at"] = "1780000000"
    parsed_raro = conector.parse(RawNotice(natural_id="EXP-1", payload=raro))
    assert parsed_raro is not None
    assert parsed_raro.licitacion.fecha_actualizacion_fuente is None
