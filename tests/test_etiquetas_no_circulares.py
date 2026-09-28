"""Etiquetas de tecnología independientes del regex de keywords.

``LicitacionRepository.etiquetas_tecnologia_no_circulares`` es lo único que
rompe la circularidad del ``TechnologyClassifier``: sin ella el modelo entrena
contra ``licitaciones.tecnologia``, que escriben los conectores con
``matches_technology()`` sobre el mismo texto que ve el modelo.

Regresión que cubre esta suite: la mitad LLM de la query hacía
``JOIN licitaciones l ON l.id = p.licitacion_id`` y ``licitaciones`` no tiene
columna ``id`` —``licitacion_tecnologia_pliego.licitacion_id`` ES el
``id_externo``, así lo declara su propia FK—. Cada llamada lanzaba
``UndefinedColumn``; ``train_from_db`` lo capturaba y degradaba a etiquetas
circulares con un warning, así que el fallo nunca se vio como fallo, solo como
un clasificador que imitaba al regex. No había ningún test sobre esta función.
"""

from __future__ import annotations

import pytest

from db.repositories.feedback import FUENTE_REVISION_TI
from db.repositories.licitaciones import LicitacionRepository
from db.repositories.tecnologia_pliego import (
    ES_TI_SENTINEL,
    NO_ES_TI_SENTINEL,
    NO_SIGNAL_SENTINEL,
    SIN_EVIDENCIA_SENTINEL,
    TechSignal,
    TecnologiaPliegoRepository,
)


@pytest.fixture()
def repos(tmp_db):
    _db_mod, _ = tmp_db
    return LicitacionRepository(), TecnologiaPliegoRepository()


def _insert_licitacion(id_externo: str) -> None:
    from db.database import connect

    with connect() as c:
        c.execute(
            "INSERT INTO licitaciones "
            "(id_externo, titulo, descripcion, fuente, fecha_publicacion, fecha_extraccion) "
            "VALUES (%s, %s, %s, 'placsp', '2026-06-01', CURRENT_TIMESTAMP)",
            (id_externo, f"Contrato {id_externo}", "Mantenimiento del ERP"),
        )


def _insert_feedback_humano(
    expediente: str,
    tecnologia: str | None,
    *,
    relevante: int = 1,
    source: str = "human",
) -> None:
    from db.database import connect

    with connect() as c:
        c.execute(
            "INSERT INTO ml_feedback (expediente, relevante, tecnologia, source, created_at) "
            "VALUES (%s, %s, %s, %s, CURRENT_TIMESTAMP)",
            (expediente, relevante, tecnologia, source),
        )


def _insert_senal(
    licitacion_id: str,
    tecnologia: str,
    *,
    method: str,
    signal_version: str,
    computed_at: str,
    score: float = 0.9,
) -> None:
    """Fila cruda, sin pasar por ``upsert_signals``.

    ``upsert_signals`` reescribe todas las filas del ``method`` con la versión
    nueva, así que por ese camino no conviven dos versiones. La lectura no
    puede depender de eso: basta un backfill a mano o un escritor nuevo para
    mezclar respuestas de dos prompts distintos.
    """
    from db.database import connect

    with connect() as c:
        c.execute(
            "INSERT INTO licitacion_tecnologia_pliego "
            "(licitacion_id, tecnologia, method, score, signal_version, computed_at) "
            "VALUES (%s, %s, %s, %s, %s, %s)",
            (licitacion_id, tecnologia, method, score, signal_version, computed_at),
        )


def test_la_query_no_revienta_contra_el_schema_real(repos) -> None:
    """La regresión desnuda: antes lanzaba UndefinedColumn en cada llamada."""
    lic_repo, _ = repos

    assert lic_repo.etiquetas_tecnologia_no_circulares() == {}


def test_la_señal_llm_se_indexa_por_id_externo(repos) -> None:
    lic_repo, tech_repo = repos
    _insert_licitacion("EXP-LLM")
    tech_repo.upsert_signals(
        "EXP-LLM",
        method="llm_metadata",
        signal_version="v1",
        scores={"SAP": TechSignal(score=0.91)},
    )

    externas = lic_repo.etiquetas_tecnologia_no_circulares()

    assert "EXP-LLM" in externas
    assert externas["EXP-LLM"]["tecnologia_llm"].startswith("SAP:")


def test_la_señal_de_keywords_no_cuenta_como_independiente(repos) -> None:
    """Es justo la fuente circular: si contara, el gate no serviría de nada."""
    lic_repo, tech_repo = repos
    _insert_licitacion("EXP-KW")
    tech_repo.upsert_signals(
        "EXP-KW",
        method="keywords",
        signal_version="v1",
        scores={"SAP": TechSignal(score=0.9)},
    )

    assert lic_repo.etiquetas_tecnologia_no_circulares() == {}


def test_el_feedback_humano_sin_tecnologia_es_un_pronunciamiento(repos) -> None:
    """Cadena vacía, no ausencia: `revision_ti` revisó y descartó, y eso es un
    negativo verdadero que el entrenamiento necesita. Una fila `human`
    heredada sin tecnología, en cambio, no se pronuncia sea cual sea su
    `relevante` -- eso lo cubre la suite de `etiqueta_humana` y el test de más
    abajo sobre esta misma función."""
    lic_repo, _ = repos
    _insert_licitacion("EXP-H")
    _insert_feedback_humano("EXP-H", None, source=FUENTE_REVISION_TI)

    externas = lic_repo.etiquetas_tecnologia_no_circulares()

    assert externas["EXP-H"]["tecnologia_humana"] == ""


def test_las_dos_fuentes_conviven_en_la_misma_licitacion(repos) -> None:
    lic_repo, tech_repo = repos
    _insert_licitacion("EXP-2F")
    _insert_feedback_humano("EXP-2F", "ORACLE")
    tech_repo.upsert_signals(
        "EXP-2F",
        method="llm",
        signal_version="v1",
        scores={"SAP": TechSignal(score=0.8)},
    )

    fuentes = lic_repo.etiquetas_tecnologia_no_circulares()["EXP-2F"]

    assert fuentes["tecnologia_humana"] == "ORACLE"
    assert fuentes["tecnologia_llm"].startswith("SAP:")


# ── Solo la versión vigente del LLM ────────────────────────────────────────


def test_solo_cuenta_la_version_mas_reciente_del_llm(repos) -> None:
    """Un cambio de prompt no puede mezclar respuestas viejas y nuevas."""
    lic_repo, _ = repos
    _insert_licitacion("EXP-V")
    _insert_senal(
        "EXP-V",
        "SAP",
        method="llm_metadata",
        signal_version="llm-meta-v1/m",
        computed_at="2026-09-01T10:00:00+00:00",
    )
    _insert_senal(
        "EXP-V",
        "ORACLE",
        method="llm_metadata",
        signal_version="llm-meta-v2/m",
        computed_at="2026-09-20T10:00:00+00:00",
    )

    fuentes = lic_repo.etiquetas_tecnologia_no_circulares()["EXP-V"]

    assert fuentes["tecnologia_llm"] == "ORACLE:0.9000"


def test_la_version_vigente_se_decide_por_method(repos) -> None:
    """``llm`` (fichas de pliego) y ``llm_metadata`` son carriles distintos:
    la versión nueva de uno no retira las respuestas del otro."""
    lic_repo, _ = repos
    _insert_licitacion("EXP-M")
    _insert_senal(
        "EXP-M",
        "ORACLE",
        method="llm",
        signal_version="ficha-v3",
        computed_at="2026-08-01T10:00:00+00:00",
    )
    _insert_senal(
        "EXP-M",
        "SAP",
        method="llm_metadata",
        signal_version="llm-meta-v2/m",
        computed_at="2026-09-20T10:00:00+00:00",
    )

    csv = lic_repo.etiquetas_tecnologia_no_circulares()["EXP-M"]["tecnologia_llm"]

    assert sorted(csv.split(",")) == ["ORACLE:0.9000", "SAP:0.9000"]


def test_una_version_nueva_sin_tecnologia_anula_la_vieja(repos) -> None:
    """El «ninguna» del prompt nuevo es la respuesta vigente: el SAP del prompt
    anterior ya no cuenta."""
    lic_repo, _ = repos
    _insert_licitacion("EXP-NV")
    _insert_senal(
        "EXP-NV",
        "SAP",
        method="llm_metadata",
        signal_version="llm-meta-v1/m",
        computed_at="2026-09-01T10:00:00+00:00",
    )
    _insert_senal(
        "EXP-NV",
        NO_SIGNAL_SENTINEL,
        method="llm_metadata",
        signal_version="llm-meta-v2/m",
        computed_at="2026-09-20T10:00:00+00:00",
        score=0.0,
    )

    assert lic_repo.etiquetas_tecnologia_no_circulares()["EXP-NV"]["tecnologia_llm"] == ""


# ── Etiquetas descartadas por falta de cita ────────────────────────────────


def test_sin_evidencia_no_es_un_pronunciamiento(repos) -> None:
    """El LLM afirmó una tecnología y no la sostuvo con una cita: eso no es
    «ninguna tecnología». Si contara como ``""`` entrenaría un negativo falso."""
    lic_repo, tech_repo = repos
    _insert_licitacion("EXP-SE")
    tech_repo.upsert_signals(
        "EXP-SE", method="llm_metadata", signal_version="v2", scores={}, sin_evidencia=True
    )

    assert "EXP-SE" not in lic_repo.etiquetas_tecnologia_no_circulares()


def test_sin_evidencia_no_tapa_lo_que_dijo_otro_carril(repos) -> None:
    lic_repo, tech_repo = repos
    _insert_licitacion("EXP-SE2")
    tech_repo.upsert_signals(
        "EXP-SE2", method="llm_metadata", signal_version="v2", scores={}, sin_evidencia=True
    )
    tech_repo.upsert_signals(
        "EXP-SE2", method="llm", signal_version="ficha-v3", scores={"SAP": TechSignal(score=0.8)}
    )

    assert lic_repo.etiquetas_tecnologia_no_circulares()["EXP-SE2"]["tecnologia_llm"] == (
        "SAP:0.8000"
    )


def test_una_version_nueva_sin_evidencia_retira_la_vieja_sin_pronunciarse(repos) -> None:
    """La versión vigente manda aunque no se pronuncie: el SAP del prompt
    anterior no vuelve por la puerta de atrás."""
    lic_repo, _ = repos
    _insert_licitacion("EXP-SE3")
    _insert_senal(
        "EXP-SE3",
        "SAP",
        method="llm_metadata",
        signal_version="llm-meta-v1/m",
        computed_at="2026-09-01T10:00:00+00:00",
    )
    _insert_senal(
        "EXP-SE3",
        SIN_EVIDENCIA_SENTINEL,
        method="llm_metadata",
        signal_version="llm-meta-v2/m",
        computed_at="2026-09-20T10:00:00+00:00",
        score=0.0,
    )

    assert "EXP-SE3" not in lic_repo.etiquetas_tecnologia_no_circulares()


# ── Marcador de nivel 1 (plan de clasificación en tres niveles) ───────────
#
# El marcador (``__es_ti__``/``__no_es_ti__``) vive DENTRO de
# ``method='llm_metadata'``, junto a las familias en la misma llamada de
# ``upsert_signals``: la CHECK ``ck_lic_tec_pliego_method`` de la tabla no
# admite un ``method`` propio sin migración (F5).


def test_solo_el_marcador_se_pronuncia_sin_etiqueta(repos) -> None:
    """El marcador por sí solo -- sin familias -- cuenta como
    pronunciamiento, igual que ``__no_signal__``, pero nunca da una
    etiqueta: contestar si es TI no es nombrar una tecnología."""
    lic_repo, tech_repo = repos
    _insert_licitacion("EXP-MK1")
    tech_repo.upsert_signals(
        "EXP-MK1",
        method="llm_metadata",
        signal_version="llm-meta-v3/m",
        scores={NO_ES_TI_SENTINEL: TechSignal(score=0.0, evidence=[{"es_ti": False}])},
    )

    externas = lic_repo.etiquetas_tecnologia_no_circulares()

    assert externas["EXP-MK1"]["tecnologia_llm"] == ""


def test_el_marcador_no_ensucia_la_etiqueta_de_familia(repos) -> None:
    """Familias y marcador conviven en la misma llamada (``upsert_signals``,
    ver su docstring): el CSV de salida solo lleva la familia."""
    lic_repo, tech_repo = repos
    _insert_licitacion("EXP-MK2")
    tech_repo.upsert_signals(
        "EXP-MK2",
        method="llm_metadata",
        signal_version="llm-meta-v3/m",
        scores={
            "SAP": TechSignal(score=0.9),
            ES_TI_SENTINEL: TechSignal(score=0.0, evidence=[{"es_ti": True}]),
        },
    )

    assert lic_repo.etiquetas_tecnologia_no_circulares()["EXP-MK2"]["tecnologia_llm"] == (
        "SAP:0.9000"
    )


def test_sin_evidencia_junto_al_marcador_sigue_sin_pronunciarse(repos) -> None:
    """``__sin_evidencia__`` gana dentro de su propio ``method`` aunque la
    misma versión vigente también traiga el marcador de nivel 1: son
    respuestas independientes (una sobre las familias, otra sobre si es
    TI), pero la licitación sigue sin pronunciarse para las familias."""
    lic_repo, tech_repo = repos
    _insert_licitacion("EXP-MK3")
    tech_repo.upsert_signals(
        "EXP-MK3",
        method="llm_metadata",
        signal_version="llm-meta-v3/m",
        scores={ES_TI_SENTINEL: TechSignal(score=0.0, evidence=[{"es_ti": True}])},
        sin_evidencia=True,
    )

    assert "EXP-MK3" not in lic_repo.etiquetas_tecnologia_no_circulares()


# ── Un solo significado para el feedback humano (2026-09-27) ──────────────


def test_una_fila_human_heredada_sin_tecnologia_no_se_pronuncia(repos) -> None:
    """`relevante` significó «es SAP» hasta el plan de tres niveles. Una fila
    `human` sin tecnología no dice «ninguna familia» sea cual sea su
    `relevante`: ni `relevante=0` («no es SAP») ni `relevante=1` («es SAP»,
    pero de cuál no consta) pueden entrenar como negativo de todas las
    familias. El caso `relevante=1` es el hallazgo de la ronda de revisión de
    Tarea 3 (2026-09-27): 14 filas así en producción se etiquetaban como
    negativo de todas las familias por error.

    `revision_ti`, en cambio, sí se pronuncia siempre: su `relevante` es «es
    TI» y una fila con tecnología puesta da esa tecnología como etiqueta.
    """
    lic_repo, _ = repos
    _insert_licitacion("EXP-H0")
    _insert_feedback_humano("EXP-H0", None, relevante=0, source="human")
    _insert_licitacion("EXP-H1")
    _insert_feedback_humano("EXP-H1", None, relevante=1, source="human")
    _insert_licitacion("EXP-RTI")
    _insert_feedback_humano("EXP-RTI", "ERP", relevante=1, source=FUENTE_REVISION_TI)

    externas = lic_repo.etiquetas_tecnologia_no_circulares()

    assert "EXP-H0" not in externas
    assert "EXP-H1" not in externas
    assert externas["EXP-RTI"]["tecnologia_humana"] == "ERP"
