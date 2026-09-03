"""Tests de integración (tmp_db) de la señal de tecnología por pliego:
repositorio, fase del job de scheduler y endpoint HTTP.

La aritmética pura del merge (sin BD, repo mockeado) vive en
``tests/test_tech_signal.py``.
"""

from __future__ import annotations

import pytest

from db.database import DocumentoReferencia, connect
from db.repositories.documentos import DocumentosRepository
from db.repositories.tecnologia_pliego import TechSignal, TecnologiaPliegoRepository
from services.tech_signal import _build_merge_result, merge_doc_signals


def _insert_licitacion(
    id_externo: str, *, tecnologia: str | None = None, ml_tecnologias: str | None = None
) -> None:
    with connect() as c:
        c.execute(
            "INSERT INTO licitaciones "
            "(id_externo, titulo, fuente, fecha_extraccion, tecnologia, ml_tecnologias) "
            "VALUES (%s, %s, 'placsp', CURRENT_TIMESTAMP, %s, %s)",
            (id_externo, f"Contrato {id_externo}", tecnologia, ml_tecnologias),
        )


def _seed_pages(licitacion_id: str, texto: str, *, tipo: str = "technical") -> int:
    """Licitación + documento ``extracted`` con una página de texto. Devuelve
    el documento_id."""
    _insert_licitacion(licitacion_id)
    repo = DocumentosRepository()
    repo.upsert_meta(
        licitacion_id, [DocumentoReferencia(tipo=tipo, uri=f"https://x/{licitacion_id}.pdf")]
    )
    doc = repo.list_pendientes()[0]
    repo.mark_extracted(doc["id"], texto=texto, sha256="h", pages=[texto])
    return int(doc["id"])


@pytest.fixture()
def repo(tmp_db):
    _db_mod, _ = tmp_db
    return TecnologiaPliegoRepository()


class TestUpsertSignals:
    def test_replaces_previous_signals_for_the_same_method(self, repo):
        _insert_licitacion("SIG-1")
        repo.upsert_signals(
            "SIG-1",
            method="keywords",
            signal_version="v1",
            scores={"SAP": TechSignal(score=0.9, matched_terms=["sap"])},
        )
        repo.upsert_signals(
            "SIG-1",
            method="keywords",
            signal_version="v2",
            scores={"ORACLE": TechSignal(score=0.7, matched_terms=["oracle"])},
        )
        rows = repo.list_for_licitacion("SIG-1")
        assert [r["tecnologia"] for r in rows] == ["ORACLE"]

    def test_empty_scores_persists_sentinel_invisible_to_reads(self, repo):
        # _seed_pages (no _insert_licitacion a secas): sin un documento
        # 'extracted', list_licitaciones_pending_signal excluiría SIG-2 por
        # esa razón sola y la aserción de abajo pasaría aunque el sentinel
        # no se persistiera -- necesitamos que SIG-2 sea elegible de verdad.
        _seed_pages("SIG-2", "contenido sin tecnología detectable")
        n = repo.upsert_signals("SIG-2", method="keywords", signal_version="v1", scores={})
        assert n == 0
        assert repo.list_for_licitacion("SIG-2") == []
        # pero SÍ cuenta como "ya puntuada" para list_licitaciones_pending_signal
        assert repo.list_licitaciones_pending_signal(signal_version="v1") == []

    def test_keywords_and_llm_coexist_for_the_same_licitacion(self, repo):
        _insert_licitacion("SIG-3")
        repo.upsert_signals(
            "SIG-3",
            method="keywords",
            signal_version="v1",
            scores={"SAP": TechSignal(score=0.6, matched_terms=["sap"])},
        )
        repo.upsert_signals(
            "SIG-3",
            method="llm",
            signal_version="tender-facts-v2",
            scores={
                "SAP": TechSignal(
                    score=0.95,
                    evidence=[{"documento_id": 1, "page_number": 1, "quote": "SAP"}],
                )
            },
        )
        rows = repo.list_for_licitacion("SIG-3")
        assert {r["method"] for r in rows} == {"keywords", "llm"}


class TestUpsertSignalsPreservesMergedAt:
    """Regresión: un DELETE+INSERT ciego reseteaba ``merged_at`` a NULL en
    cada re-puntuación, así que ``merge_doc_signals`` reemitía un evento de
    auditoría duplicado para una detección ya fusionada. Esto no es un edge
    case: un bump de ``signal_version`` (cambio en las keywords, o un
    extractor LLM nuevo) reprocesa TODO el universo por diseño."""

    def test_rescoring_an_already_merged_technology_preserves_merged_at(self, repo):
        _insert_licitacion("PRESERVE-1")
        repo.upsert_signals(
            "PRESERVE-1",
            method="keywords",
            signal_version="v1",
            scores={"SAP": TechSignal(score=0.9, matched_terms=["sap"])},
        )
        merge_doc_signals(licitacion_ids=["PRESERVE-1"])  # marca merged_at

        before = repo.list_signals_for_merge(min_score=0.0, licitacion_ids=["PRESERVE-1"])
        assert before[0]["merged_at"] is not None

        # Re-puntuación (ej. bump de signal_version) que redetecta SAP a otro score.
        repo.upsert_signals(
            "PRESERVE-1",
            method="keywords",
            signal_version="v2",
            scores={"SAP": TechSignal(score=0.92, matched_terms=["sap"])},
        )

        after = repo.list_signals_for_merge(min_score=0.0, licitacion_ids=["PRESERVE-1"])
        assert after[0]["merged_at"] == before[0]["merged_at"]  # sobrevive intacto
        assert after[0]["score"] == 0.92  # pero el score sí se actualiza
        assert after[0]["signal_version"] == "v2"

    def test_a_technology_no_longer_detected_is_removed(self, repo):
        """Una tecnología que la re-puntuación ya no detecta se borra, aunque
        las que sí siguen detectadas conserven su merged_at."""
        _insert_licitacion("PRESERVE-2")
        repo.upsert_signals(
            "PRESERVE-2",
            method="keywords",
            signal_version="v1",
            scores={
                "SAP": TechSignal(score=0.9, matched_terms=["sap"]),
                "ORACLE": TechSignal(score=0.6, matched_terms=["oracle"]),
            },
        )
        repo.upsert_signals(
            "PRESERVE-2",
            method="keywords",
            signal_version="v2",
            scores={"SAP": TechSignal(score=0.9, matched_terms=["sap"])},
        )
        rows = repo.list_for_licitacion("PRESERVE-2")
        assert [r["tecnologia"] for r in rows] == ["SAP"]


class TestMergeManyWithLockBatch:
    """El merge por lotes resuelve N licitaciones en una transacción por chunk.
    El modo de fallo propio de ese rediseño —cruzar el estado de una licitación
    con el de otra al agrupar las lecturas— solo se ve contra BD real."""

    def test_each_licitacion_gets_its_own_signal_not_its_neighbours(self, repo):
        _insert_licitacion("BATCH-1", ml_tecnologias="SAP")
        _insert_licitacion("BATCH-2")
        _insert_licitacion("BATCH-3", ml_tecnologias="ORACLE")
        with connect() as c:
            c.executemany(
                "INSERT INTO licitacion_tecnologia_score "
                "(licitacion_id, tecnologia, probabilidad, threshold_aplicado, computed_at) "
                "VALUES (%s, %s, %s, %s, %s)",
                [
                    ("BATCH-1", "SAP", 0.95, 0.5, "2026-08-01T00:00:00+00:00"),
                    ("BATCH-3", "ORACLE", 0.60, 0.5, "2026-08-01T00:00:00+00:00"),
                ],
            )
        for licitacion_id, tech, score in (
            ("BATCH-1", "META4", 0.8),
            ("BATCH-2", "DOCKER", 0.7),
            ("BATCH-3", "META4", 0.9),
        ):
            repo.upsert_signals(
                licitacion_id,
                method="keywords",
                signal_version="v1",
                scores={tech: TechSignal(score=score, matched_terms=[tech.lower()])},
            )

        result = merge_doc_signals()

        assert result["licitaciones_merged"] == 3
        assert result["errors"] == 0
        with connect() as c:
            rows = c.execute(
                "SELECT id_externo, ml_tecnologias, ml_tech_principal, ml_proba_max "
                "FROM licitaciones WHERE id_externo LIKE 'BATCH-%' ORDER BY id_externo"
            ).fetchall()
        por_id = {str(r[0]): r for r in rows}
        assert set(str(por_id["BATCH-1"][1]).split(",")) == {"SAP", "META4"}
        assert por_id["BATCH-1"][2] == "SAP"  # 0.95 del score previo gana al 0.8
        assert str(por_id["BATCH-2"][1]) == "DOCKER"
        assert por_id["BATCH-2"][2] == "DOCKER"
        assert set(str(por_id["BATCH-3"][1]).split(",")) == {"ORACLE", "META4"}
        assert por_id["BATCH-3"][2] == "META4"  # 0.9 del pliego gana al 0.60

    def test_chunking_does_not_change_the_result(self, repo):
        """Con ``chunk_size`` menor que el lote se abren varias transacciones;
        el resultado tiene que ser idéntico al de una sola."""
        ids = [f"CHUNK-{i}" for i in range(5)]
        for licitacion_id in ids:
            _insert_licitacion(licitacion_id)
            repo.upsert_signals(
                licitacion_id,
                method="keywords",
                signal_version="v1",
                scores={"META4": TechSignal(score=0.8, matched_terms=["meta4"])},
            )

        outcome = repo.merge_many_with_lock(
            ids,
            lambda _lic, state: _build_merge_result(
                state, pliego_scores={"META4": 0.8}, threshold_aplicado=0.5
            ),
            chunk_size=2,
        )

        assert set(outcome.results) == set(ids)
        assert outcome.errors == {}
        with connect() as c:
            rows = c.execute(
                "SELECT ml_tecnologias FROM licitaciones WHERE id_externo LIKE 'CHUNK-%'"
            ).fetchall()
        assert [str(r[0]) for r in rows] == ["META4"] * 5

    def test_an_unknown_licitacion_id_does_not_poison_its_chunk(self, repo):
        """``licitacion_tecnologia_score`` tiene FK contra ``licitaciones``: un
        id inexistente reventaría el INSERT y, al ir todo el chunk en una sola
        transacción, se llevaría por delante a los vecinos. Se descarta antes
        de tocar la BD."""
        _insert_licitacion("FK-OK")

        outcome = repo.merge_many_with_lock(
            ["FK-OK", "FK-NO-EXISTE"],
            lambda _lic, state: _build_merge_result(
                state, pliego_scores={"META4": 0.8}, threshold_aplicado=0.5
            ),
        )

        assert set(outcome.results) == {"FK-OK"}
        assert "FK-NO-EXISTE" in outcome.errors
        with connect() as c:
            row = c.execute(
                "SELECT ml_tecnologias FROM licitaciones WHERE id_externo = 'FK-OK'"
            ).fetchone()
        assert str(row[0]) == "META4"

    def test_a_licitacion_whose_compute_raises_does_not_lose_the_chunk(self, repo):
        """Fail-open por licitación dentro de la MISMA transacción: la que
        revienta se descarta y las demás del chunk se escriben igual."""
        for licitacion_id in ("FAILOPEN-1", "FAILOPEN-2"):
            _insert_licitacion(licitacion_id)

        def _compute(licitacion_id, state):
            if licitacion_id == "FAILOPEN-1":
                raise KeyError("SAP")
            return _build_merge_result(state, pliego_scores={"META4": 0.8}, threshold_aplicado=0.5)

        outcome = repo.merge_many_with_lock(["FAILOPEN-1", "FAILOPEN-2"], _compute)

        assert set(outcome.results) == {"FAILOPEN-2"}
        assert outcome.errors == {"FAILOPEN-1": "KeyError: 'SAP'"}
        with connect() as c:
            row = c.execute(
                "SELECT ml_tecnologias FROM licitaciones WHERE id_externo = 'FAILOPEN-2'"
            ).fetchone()
        assert str(row[0]) == "META4"

    def test_predicted_technology_without_score_row_still_merges(self, repo):
        """Regresión (2026-09-02): ``ml_tecnologias`` nombraba una tecnología
        sin fila en ``licitacion_tecnologia_score``; el KeyError dejaba a esas
        33 licitaciones de producción sin fusionar en cada pasada."""
        _insert_licitacion("ORPHAN-1", ml_tecnologias="SAP")  # sin fila de score
        repo.upsert_signals(
            "ORPHAN-1",
            method="keywords",
            signal_version="v1",
            scores={"META4": TechSignal(score=0.8, matched_terms=["meta4"])},
        )

        result = merge_doc_signals(licitacion_ids=["ORPHAN-1"])

        assert result == {"licitaciones_merged": 1, "events_emitted": 1, "errors": 0}
        with connect() as c:
            row = c.execute(
                "SELECT ml_tecnologias, ml_tech_principal "
                "FROM licitaciones WHERE id_externo = 'ORPHAN-1'"
            ).fetchone()
        assert set(str(row[0]).split(",")) == {"SAP", "META4"}
        assert row[1] == "META4"


class TestMergeManyWithLockScope:
    def test_untouched_technology_score_row_is_not_clobbered(self, repo):
        """El upsert de licitacion_tecnologia_score solo debe tocar las
        tecnologías que la señal de pliego aportó -- una que el pliego no
        toca conserva intacto su threshold_aplicado/computed_at de
        precompute_ml_tecnologias, no el umbral del merge."""
        _insert_licitacion("SCOPE-1", ml_tecnologias="SAP")
        with connect() as c:
            c.execute(
                "INSERT INTO licitacion_tecnologia_score "
                "(licitacion_id, tecnologia, probabilidad, threshold_aplicado, computed_at) "
                "VALUES (%s, %s, %s, %s, %s)",
                ("SCOPE-1", "SAP", 0.95, 0.5, "2026-08-01T00:00:00+00:00"),
            )
        repo.upsert_signals(
            "SCOPE-1",
            method="keywords",
            signal_version="v1",
            scores={"META4": TechSignal(score=0.8, matched_terms=["meta4"])},
        )

        merge_doc_signals(licitacion_ids=["SCOPE-1"])

        with connect() as c:
            row = c.execute(
                "SELECT probabilidad, threshold_aplicado, computed_at "
                "FROM licitacion_tecnologia_score WHERE licitacion_id = %s AND tecnologia = %s",
                ("SCOPE-1", "SAP"),
            ).fetchone()
        assert row[0] == 0.95
        assert row[1] == 0.5  # threshold ML propio, no PLIEGO_TECH_MIN_SCORE
        assert row[2] == "2026-08-01T00:00:00+00:00"

    def test_ml_tech_principal_is_never_absent_from_ml_tecnologias(self, repo):
        """Regresión: ml_tech_principal/ml_proba_max se calculaban sobre
        TODAS las tecnologías con score>0 en licitacion_tecnologia_score,
        incluidas las que nunca cruzaron su propio threshold ML -- podían
        nombrar una tecnología ausente de ml_tecnologias."""
        _insert_licitacion("SCOPE-2")  # ml_tecnologias vacío: SAP nunca fue "predicha"
        with connect() as c:
            c.execute(
                "INSERT INTO licitacion_tecnologia_score "
                "(licitacion_id, tecnologia, probabilidad, threshold_aplicado, computed_at) "
                "VALUES (%s, %s, %s, %s, %s)",
                ("SCOPE-2", "SAP", 0.45, 0.5, "2026-08-01T00:00:00+00:00"),
            )
        repo.upsert_signals(
            "SCOPE-2",
            method="keywords",
            signal_version="v1",
            scores={"DOCKER": TechSignal(score=0.6, matched_terms=["docker"])},
        )

        merge_doc_signals(licitacion_ids=["SCOPE-2"])

        with connect() as c:
            row = c.execute(
                "SELECT ml_tecnologias, ml_tech_principal FROM licitaciones WHERE id_externo = %s",
                ("SCOPE-2",),
            ).fetchone()
        assert row[0] == "DOCKER"
        assert row[1] == "DOCKER"  # nunca "SAP" -- ausente de ml_tecnologias


class TestListLicitacionesPendingSignal:
    def test_only_selects_licitaciones_with_extracted_documents(self, repo):
        _seed_pages("PEND-1", "algo")
        _insert_licitacion("PEND-2")  # sin documentos
        assert repo.list_licitaciones_pending_signal(signal_version="v1") == ["PEND-1"]

    def test_excludes_licitaciones_with_current_signal_version(self, repo):
        _seed_pages("PEND-3", "algo")
        repo.upsert_signals("PEND-3", method="keywords", signal_version="v1", scores={})
        assert repo.list_licitaciones_pending_signal(signal_version="v1") == []

    def test_stale_signal_version_is_reselected(self, repo):
        _seed_pages("PEND-4", "algo")
        repo.upsert_signals("PEND-4", method="keywords", signal_version="v1", scores={})
        assert repo.list_licitaciones_pending_signal(signal_version="v2") == ["PEND-4"]


class TestListSignalsForMerge:
    def test_filters_by_min_score(self, repo):
        _insert_licitacion("MRG-1")
        repo.upsert_signals(
            "MRG-1",
            method="keywords",
            signal_version="v1",
            scores={"SAP": TechSignal(score=0.9), "ORACLE": TechSignal(score=0.2)},
        )
        rows = repo.list_signals_for_merge(min_score=0.5)
        assert [r["tecnologia"] for r in rows] == ["SAP"]

    def test_filters_by_licitacion_ids(self, repo):
        _insert_licitacion("MRG-2")
        _insert_licitacion("MRG-3")
        repo.upsert_signals(
            "MRG-2", method="keywords", signal_version="v1", scores={"SAP": TechSignal(score=0.9)}
        )
        repo.upsert_signals(
            "MRG-3", method="keywords", signal_version="v1", scores={"SAP": TechSignal(score=0.9)}
        )
        rows = repo.list_signals_for_merge(min_score=0.5, licitacion_ids=["MRG-2"])
        assert {r["licitacion_id"] for r in rows} == {"MRG-2"}


class TestStampMerged:
    def test_only_updates_rows_that_were_still_null(self, repo):
        _insert_licitacion("STAMP-1")
        repo.upsert_signals(
            "STAMP-1", method="keywords", signal_version="v1", scores={"SAP": TechSignal(score=0.9)}
        )
        repo.stamp_merged([("STAMP-1", "SAP", "keywords")], merged_at="2026-08-01T00:00:00+00:00")
        repo.stamp_merged([("STAMP-1", "SAP", "keywords")], merged_at="2026-08-02T00:00:00+00:00")

        rows = repo.list_signals_for_merge(min_score=0.0, licitacion_ids=["STAMP-1"])
        assert rows[0]["merged_at"] == "2026-08-01T00:00:00+00:00"


class TestMergeReapplicableAfterClobber:
    def test_merge_survives_upsert_clobber_without_reemitting_event(self, repo):
        """precompute_ml_tecnologias / db/upsert.py resetean ml_tecnologias en
        cada re-scrape (ver plan): el merge nightly debe curarlo sin duplicar
        el evento de auditoría."""
        _insert_licitacion("HEAL-1")
        repo.upsert_signals(
            "HEAL-1",
            method="keywords",
            signal_version="v1",
            scores={"META4": TechSignal(score=0.8, matched_terms=["meta4"])},
        )

        first = merge_doc_signals(licitacion_ids=["HEAL-1"])
        assert first["events_emitted"] == 1

        with connect() as c:
            row = c.execute(
                "SELECT ml_tecnologias FROM licitaciones WHERE id_externo = %s", ("HEAL-1",)
            ).fetchone()
        assert row[0] == "META4"

        # Simula el clobber de un re-scrape (db/upsert.py) / precompute_ml_tecnologias.
        with connect() as c:
            c.execute(
                "UPDATE licitaciones SET ml_tecnologias = NULL, ml_proba_max = NULL, "
                "ml_tech_principal = NULL WHERE id_externo = %s",
                ("HEAL-1",),
            )

        second = merge_doc_signals()  # nightly: cubre TODAS, no solo HEAL-1
        assert second["events_emitted"] == 0  # ya se emitió antes -- no duplica

        with connect() as c:
            row = c.execute(
                "SELECT ml_tecnologias FROM licitaciones WHERE id_externo = %s", ("HEAL-1",)
            ).fetchone()
        assert row[0] == "META4"  # curado


class TestTechSignalJobPhase:
    def test_scores_pending_and_merges_the_batch(self, repo):
        from scheduler.jobs.documentos_embeddings import _run_tech_signal_phase

        _seed_pages(
            "PHASE-1",
            "Implantación y mantenimiento de SAP S/4HANA. Migración a SAP HANA.",
        )

        counts = _run_tech_signal_phase()

        assert counts["scored"] == 1
        assert counts["error"] == 0
        assert counts.get("merged") == 1
        with connect() as c:
            row = c.execute(
                "SELECT ml_tecnologias FROM licitaciones WHERE id_externo = %s", ("PHASE-1",)
            ).fetchone()
        assert row[0] is not None and "SAP" in row[0]

    def test_documents_without_tech_mentions_do_not_block_the_batch(self, repo):
        from scheduler.jobs.documentos_embeddings import _run_tech_signal_phase

        _seed_pages(
            "PHASE-2",
            "El plazo de ejecución será de doce meses naturales desde la firma.",
            tipo="legal",
        )

        counts = _run_tech_signal_phase()

        assert counts["no_signal"] == 1
        assert counts["scored"] == 0

    def test_is_idempotent_across_runs(self, repo):
        """Una licitación ya puntuada a la signal_version vigente no se
        vuelve a seleccionar en la siguiente corrida."""
        from scheduler.jobs.documentos_embeddings import _run_tech_signal_phase

        _seed_pages("PHASE-3", "Consultoría e implantación de SAP S/4HANA y SAP HANA.")

        first = _run_tech_signal_phase()
        second = _run_tech_signal_phase()

        assert first["scored"] == 1
        assert second["scored"] == 0
        assert second["no_signal"] == 0


class TestTecnologiasEndpoint:
    def test_consolidates_titulo_ml_and_pliego_signals(self, client, auth):
        _insert_licitacion("EP-1", tecnologia="SAP", ml_tecnologias="SAP")
        with connect() as c:
            c.execute(
                "INSERT INTO licitacion_tecnologia_score "
                "(licitacion_id, tecnologia, probabilidad, threshold_aplicado, computed_at) "
                "VALUES (%s, %s, %s, %s, %s)",
                ("EP-1", "SAP", 0.92, 0.5, "2026-08-01T00:00:00+00:00"),
            )
        TecnologiaPliegoRepository().upsert_signals(
            "EP-1",
            method="keywords",
            signal_version="v1",
            scores={"META4": TechSignal(score=0.75, matched_terms=["meta4", "recursos humanos"])},
        )

        r = client.get("/api/v1/licitaciones/EP-1/tecnologias", headers=auth)

        assert r.status_code == 200
        data = r.json()
        by_tech = {item["tecnologia"]: item for item in data["items"]}
        assert by_tech["SAP"]["en_titulo"] is True
        assert by_tech["SAP"]["ml_probabilidad"] == 0.92
        assert by_tech["META4"]["en_titulo"] is False
        assert by_tech["META4"]["pliego_keywords_score"] == 0.75
        assert by_tech["META4"]["pliego_keywords_terms"] == ["meta4", "recursos humanos"]

    def test_returns_404_for_unknown_licitacion(self, client, auth):
        r = client.get("/api/v1/licitaciones/NOPE-TECH/tecnologias", headers=auth)
        assert r.status_code == 404

    def test_requires_auth(self, client):
        _insert_licitacion("EP-2")
        r = client.get("/api/v1/licitaciones/EP-2/tecnologias")
        assert r.status_code in (401, 403)

    def test_empty_items_when_no_signal_at_all(self, client, auth):
        _insert_licitacion("EP-3")
        r = client.get("/api/v1/licitaciones/EP-3/tecnologias", headers=auth)
        assert r.status_code == 200
        assert r.json()["items"] == []
