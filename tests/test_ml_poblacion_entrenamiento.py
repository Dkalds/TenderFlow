"""Población de entrenamiento y de scoring del clasificador SAP (S6.1).

El diagnóstico del backlog P2, medido contra producción el 2026-09-04: el
corpus de PSCP son 683.076 filas con un 0,46% de positivos frente a las 21.963
filas con 4.928 positivos (22,4%) de PLACSP + bulk + TED. Mezclados, la clase
minoritaria queda en 1,14% y ``validate_training_data`` aborta el
entrenamiento; servidos, el modelo de mayo daba «SAP» al 90,64% del corpus.

Lo que fija esta suite es la elección: la población son los universos que
filtraron por señal tecnológica **en ingesta**, y no ``universo_tecnologico_sql``
—que admitiría filas por tener ``tecnologia`` (la condición de la etiqueta
positiva) o ``ml_tecnologias`` (la salida del modelo anterior)—.
"""

from __future__ import annotations

from db.repositories.ml_dataset import (
    POBLACION_SAP_UNIVERSOS,
    TRAIN_POPULATION_SAP,
    poblacion_clasificador_sql,
)
from scripts.audit_domain_truth import (
    MAX_PCT_ML_PROBA_ALTA,
    UMBRAL_ML_PROBA_ALTA,
    evaluar,
)


class TestPredicadoDePoblacion:
    def test_excluye_el_universo_de_pscp(self) -> None:
        """El corpus que ahoga el dataset es justo el que no puede entrar."""
        assert "pscp_observed" not in poblacion_clasificador_sql()
        assert "pscp_observed" not in POBLACION_SAP_UNIVERSOS

    def test_incluye_los_universos_filtrados_en_ingesta(self) -> None:
        sql = poblacion_clasificador_sql()
        for universo in POBLACION_SAP_UNIVERSOS:
            assert f"'{universo}'" in sql

    def test_las_filas_sin_universo_cuentan_como_technology_observed(self) -> None:
        """Los negativos de ``seed_negatives`` se insertan sin universo.

        Si el ``COALESCE`` no estuviera, el dataset perdería exactamente los
        ejemplos negativos que el entrenamiento necesita para tener dos clases.
        """
        assert "COALESCE(l.analysis_universe, 'technology_observed')" in (
            poblacion_clasificador_sql()
        )

    def test_respeta_el_alias(self) -> None:
        """El alias llega a las DOS mitades del predicado, no solo a la primera.

        No se fija el prefijo literal: el predicado creció con la exclusión de
        duplicados y un aserto de prefijo lo habría roto sin que nada del
        significado cambiara. Lo que importa es que ninguna de las dos mitades
        se quede con el alias por defecto, porque una query que use ``x`` y un
        fragmento que diga ``l`` no compila.
        """
        sql = poblacion_clasificador_sql("x")
        assert "COALESCE(x.analysis_universe" in sql
        assert "x.id_externo NOT IN" in sql
        assert "l." not in sql

    def test_excluye_los_duplicados_confirmados(self) -> None:
        """Un expediente republicado ya marcado no puede pesar doble al entrenar.

        Es el criterio que vigila ``tests/test_dedup_guardrail.py`` para toda
        consulta analítica sobre ``licitaciones``; aquí se fija además que la
        exclusión viva DENTRO del predicado de población, para que una query
        nueva que lo use la herede sin acordarse.
        """
        sql = poblacion_clasificador_sql()
        assert "licitaciones_duplicados" in sql
        assert "status = 'confirmed'" in sql

    def test_no_admite_filas_por_su_propia_etiqueta(self) -> None:
        """Ni por ``tecnologia`` (que ES la etiqueta positiva) ni por
        ``ml_tecnologias`` (que es la salida del modelo anterior): admitirlas
        haría que la fuente decidiera la clase, y que el modelo previo eligiera
        la población del siguiente."""
        sql = poblacion_clasificador_sql()
        assert "tecnologia IS NOT NULL" not in sql
        assert "ml_tecnologias" not in sql

    def test_el_nombre_de_la_poblacion_es_estable(self) -> None:
        """Viaja al registro como ``train_population``: cambiarlo rompe la
        comparación entre versiones, que es justo para lo que se guarda."""
        assert TRAIN_POPULATION_SAP == "universos_filtrados_en_ingesta"


def _medicion(
    *,
    puntuadas: int,
    por_encima: int,
    fuera_puntuadas: int = 0,
) -> dict[str, object]:
    return {
        "umbral": UMBRAL_ML_PROBA_ALTA,
        "poblacion": TRAIN_POPULATION_SAP,
        "total_corpus": puntuadas + fuera_puntuadas,
        "puntuadas": puntuadas,
        "por_encima": por_encima,
        "pct_corpus_por_encima": 0.0,
        "pct_puntuadas_por_encima": (
            round(100.0 * por_encima / puntuadas, 2) if puntuadas else None
        ),
        "dentro_poblacion": {"total": puntuadas, "puntuadas": puntuadas, "por_encima": por_encima},
        "fuera_poblacion": {
            "total": fuera_puntuadas,
            "puntuadas": fuera_puntuadas,
            "por_encima": 0,
        },
    }


class TestUmbralDeDiscriminacion:
    """El criterio de aceptación de S6.1, con el umbral en la mitad."""

    def test_el_modelo_de_mayo_habria_disparado(self) -> None:
        # 90,64% de las filas puntuadas por encima del umbral: un binario que
        # dice SAP a nueve de cada diez es una constante.
        violaciones = evaluar({"ml_proba": _medicion(puntuadas=10_000, por_encima=9_064)})
        assert any("no discrimina" in v for v in violaciones), violaciones

    def test_por_debajo_de_la_mitad_no_dispara(self) -> None:
        violaciones = evaluar({"ml_proba": _medicion(puntuadas=10_000, por_encima=3_000)})
        assert violaciones == []

    def test_el_umbral_es_la_mitad(self) -> None:
        assert MAX_PCT_ML_PROBA_ALTA == 50.0
        assert UMBRAL_ML_PROBA_ALTA == 0.7

    def test_avisa_de_scores_heredados_fuera_de_la_poblacion(self) -> None:
        """Si quedan scores fuera de la población, el modelo sigue opinando
        sobre un corpus que no vio: es lo que ``precompute_ml_proba`` limpia."""
        violaciones = evaluar(
            {"ml_proba": _medicion(puntuadas=100, por_encima=10, fuera_puntuadas=683_076)}
        )
        assert any("fuera de la población" in v for v in violaciones), violaciones

    def test_sin_filas_puntuadas_no_hay_veredicto(self) -> None:
        """Con la columna entera a NULL no se puede juzgar al clasificador; el
        umbral no debe inventarse un 0% que parezca una mejora."""
        assert evaluar({"ml_proba": _medicion(puntuadas=0, por_encima=0)}) == []


class _ConexionFalsa:
    """Conexión que captura SQL y parámetros sin BD.

    Mismo patrón que ``tests/test_search_semantic_source.py::_FakeConn``.
    """

    def __init__(self, rowcount: int = 0) -> None:
        self.sql: str = ""
        self.params: tuple[object, ...] = ()
        self.rowcount = rowcount

    def execute(self, sql: str, params: object = None) -> _ConexionFalsa:
        self.sql = sql
        self.params = tuple(params or ())
        return self

    def __enter__(self) -> _ConexionFalsa:
        return self

    def __exit__(self, *_exc: object) -> None:
        return None


class TestLaLimpiezaDeScoresVaAcotada:
    """La limpieza de ``ml_proba`` heredado no puede ser un ``UPDATE`` sin tope.

    La primera vez que corre en producción hay del orden de 600.000 filas que
    limpiar (el corpus PSCP del backlog P2), y corre dentro del cierre
    post-ingesta —cada cuatro horas— sobre ``licitaciones``, que es la tabla en
    la que escribe el scraper. Un ``UPDATE`` sin ``LIMIT`` mantendría abierta
    una transacción de escritura durante minutos: o lo mata el
    ``statement_timeout`` del rol, o bloquea la ingesta.
    """

    @staticmethod
    def _capturar(monkeypatch: object, rowcount: int = 0) -> _ConexionFalsa:
        import db.repositories.ml_dataset as mod

        conn = _ConexionFalsa(rowcount=rowcount)
        monkeypatch.setattr(mod, "connect", lambda: conn)  # type: ignore[attr-defined]
        return conn

    def test_el_update_lleva_limit_parametrizado(self, monkeypatch: object) -> None:
        from db.repositories.ml_dataset import _LIMPIEZA_BATCH, limpiar_ml_proba_fuera_de_poblacion

        conn = self._capturar(monkeypatch)
        limpiar_ml_proba_fuera_de_poblacion()

        assert "LIMIT %s" in conn.sql, "el UPDATE no está acotado: barrería la tabla entera"
        assert conn.params == (_LIMPIEZA_BATCH,)

    def test_el_tope_es_parametrizable(self, monkeypatch: object) -> None:
        from db.repositories.ml_dataset import limpiar_ml_proba_fuera_de_poblacion

        conn = self._capturar(monkeypatch)
        limpiar_ml_proba_fuera_de_poblacion(limite=7)
        assert conn.params == (7,)

    def test_solo_toca_filas_fuera_de_la_poblacion_y_con_score(self, monkeypatch: object) -> None:
        """Sin las dos condiciones, la limpieza borraría lo que sí hay que servir."""
        from db.repositories.ml_dataset import limpiar_ml_proba_fuera_de_poblacion

        conn = self._capturar(monkeypatch)
        limpiar_ml_proba_fuera_de_poblacion()
        assert "l.ml_proba IS NOT NULL" in conn.sql
        assert "NOT (" in conn.sql

    def test_el_tope_es_razonable(self) -> None:
        """Ni tan pequeño que no converja, ni tan grande que vuelva al problema."""
        from db.repositories.ml_dataset import _LIMPIEZA_BATCH

        assert 500 <= _LIMPIEZA_BATCH <= 20_000
