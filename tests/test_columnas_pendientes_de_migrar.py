"""Leer una columna que la migración aún no puso no puede tumbar la página.

Motivación
----------
Las migraciones de producción se aplican **sólo a mano**
(`.github/workflows/migrate.yml` es `workflow_dispatch` a propósito), mientras
que el código llega con el despliegue. La ventana entre las dos cosas es real y
ya mordió a este proyecto: el propio workflow lo cuenta —«column "lote_id" of
relation "adjudicaciones" does not exist» en los runs de `scrape-daily` del 31
de julio—.

Este cambio añadió cinco columnas (v121, v123, v124, v125, v126). Tres de ellas
se leen en caminos calientes de usuario: el hilo de comentarios, la lista de
favoritos y el retrieval de la ficha. Nombrarlas a pelo dejaría esas tres
pantallas en 500 hasta que alguien migrara.

Qué se comprueba aquí es el **contrato**: que esas lecturas pasan por
`db/columnas.py` y que la forma de la fila no cambia entre las dos situaciones.
"""

from __future__ import annotations

import inspect
from unittest.mock import patch

import pytest

pytestmark = pytest.mark.unit


@pytest.fixture(autouse=True)
def _sin_cache() -> object:
    from db.columnas import olvidar

    olvidar()
    yield
    olvidar()


class TestProyeccionDefensiva:
    def test_sin_columna_se_proyecta_null_con_el_mismo_nombre(self) -> None:
        """La forma de la fila —y por tanto el DTO— no cambia."""
        from db.columnas import proyeccion

        with patch("db.columnas.existe", return_value=False):
            assert proyeccion("t", "nota") == "NULL AS nota"

    def test_con_columna_se_proyecta_la_columna(self) -> None:
        from db.columnas import proyeccion

        with patch("db.columnas.existe", return_value=True):
            assert proyeccion("t", "nota", prefijo="wi.") == "wi.nota AS nota"

    def test_sin_base_de_datos_se_asume_que_no_existe(self) -> None:
        """El modo degradado correcto: la lectura sigue funcionando sin ella."""
        from db.columnas import existe

        assert existe("tabla_que_no_existe", "columna_que_no_existe") is False

    def test_el_resultado_se_cachea(self) -> None:
        """Una consulta a information_schema por columna y proceso, no por fila."""
        from db.columnas import existe

        with patch("db.database.connect_read", side_effect=RuntimeError("sin bd")) as conectar:
            existe("t", "c")
            existe("t", "c")
            assert conectar.call_count <= 1


class TestCaminosCalientes:
    def test_el_hilo_de_comentarios_no_nombra_la_columna_a_pelo(self) -> None:
        import db.repositories.pursuit_comments as mod

        fuente = inspect.getsource(mod._comment_select)
        assert "proyeccion(" in fuente
        assert '"c.mentions_json"' not in fuente

    def test_la_lista_de_favoritos_tampoco(self) -> None:
        import db.repositories.watchlist as mod

        fuente = inspect.getsource(mod._proyeccion_nota)
        assert "NULL AS nota" in fuente
        assert "_nota_disponible()" in inspect.getsource(mod.WatchlistRepository.list_items)

    def test_el_retrieval_cae_al_comportamiento_anterior(self) -> None:
        """Sin `v121`, se comporta como antes de C5.7 — que es el estado real de
        esa base."""
        import db.repositories.documentos as mod

        fuente = inspect.getsource(mod.DocumentosRepository.search_chunks_by_embedding)
        assert 'existe("documento_chunks", "embedding_model")' in fuente
        assert 'sql.format(filtro="")' in fuente

    def test_el_informe_de_pendientes_lo_dice_en_vez_de_fallar(self) -> None:
        import db.repositories.documentos as mod

        fuente = inspect.getsource(mod.DocumentosRepository.pendientes_por_version_embedding)
        assert '"sin_columna": True' in fuente


def test_el_helper_es_solo_para_lecturas() -> None:
    """Un INSERT que se salta una columna nueva persiste dato incompleto en
    silencio, que es peor que fallar."""
    import db.columnas as mod

    assert (
        "No** es para" in inspect.getdoc(mod)
        or "no es para escrituras" in (inspect.getdoc(mod) or "").lower()
    )
