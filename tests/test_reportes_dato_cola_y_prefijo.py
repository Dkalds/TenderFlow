"""F6.2 — qué cola nombra un reporte de dato y con qué ``source`` se guarda.

``services/reportes_dato.py`` no tiene tabla propia: **todo** reporte, sea cual
sea su tipo, se escribe en ``ml_feedback`` con ``source = 'reporte:<tipo>'``.
``COLA_POR_TIPO`` sólo decide la cola que nombran el acuse y el log; hoy ningún
proceso de dedupe ni de empresas lee estas filas. Guardarlo todo en la misma
tabla sólo es seguro mientras tres módulos hablen del **mismo** prefijo:

* la vista de Calidad (``services/analytics/quality.py``) agrupa por él;
* la cola de active learning (``db/repositories/licitaciones.py``) lo excluye
  en su anti-join, para que reportar no cuente como etiquetar;
* el servicio lo escribe.

Hoy hay una sola definición, que viaja de ``db/`` al servicio y de ahí a
Calidad, así que cambiar el literal en su origen lo cambia en los tres. El riesgo
real es que alguien escriba una copia a mano en cualquiera de los tres
módulos. Según dónde esté la copia, nada falla pero la vista de Calidad se
queda a cero, la cola de etiquetado se vacía sola con cada reporte, o pasan
las dos cosas. Por eso aquí se fija el literal y se comprueba el viaje
completo por los consumidores, no sólo que dos constantes sean iguales.
"""

from __future__ import annotations

from typing import get_args

import pytest

from db.database import connect
from db.repositories.licitaciones import PREFIJO_REPORTE
from services.reportes_dato import (
    COLA_POR_TIPO,
    PREFIJO_SOURCE,
    TipoReporte,
    registrar_reporte,
    source_de,
)

#: El catálogo y su cola, escritos a mano a propósito: derivarlos de
#: `TipoReporte` o de `COLA_POR_TIPO` haría que el test aceptara cualquier
#: tipo nuevo o cualquier reasignación.
_COLA_ESPERADA = {
    "tecnologia": "ml_feedback",
    "ccaa": "ml_feedback",
    "importe": "ml_feedback",
    "otro": "ml_feedback",
    "duplicado": "dedupe",
    "adjudicatario": "empresas",
}


def _filas_feedback(expediente: str) -> list[dict[str, object]]:
    with connect() as c:
        filas = c.execute(
            "SELECT expediente, relevante, nota, tecnologia, source, user_id, created_at "
            "FROM ml_feedback WHERE expediente = %s ORDER BY id",
            (expediente,),
        ).fetchall()
    columnas = ("expediente", "relevante", "nota", "tecnologia", "source", "user_id", "created_at")
    return [dict(zip(columnas, fila, strict=True)) for fila in filas]


def _licitacion(id_externo: str) -> None:
    with connect() as c:
        c.execute(
            "INSERT INTO licitaciones (id_externo, titulo, fecha_publicacion, fecha_extraccion) "
            "VALUES (%s, %s, '2026-09-10', '2026-09-10')",
            (id_externo, f"Expediente {id_externo}"),
        )


# ---------------------------------------------------------------------------
# Catálogo: todo tipo nombra una cola
# ---------------------------------------------------------------------------


def test_todo_tipo_de_reporte_tiene_cola_y_ninguna_cola_es_huerfana():
    """Añadir un tipo obliga a decidir qué cola nombra. Si no, la ruta lo
    valida y ``registrar_reporte`` guarda la fila y revienta con ``KeyError``
    en la línea de log, **después** del insert: la ruta responde 500 con el
    reporte ya escrito, y el usuario no sabe que llegó.

    Es este test, y no el siguiente, el que mira el ``Literal``: si alguien
    amplía ``TipoReporte`` y se olvida de ``COLA_POR_TIPO``, el diccionario
    sigue idéntico a ``_COLA_ESPERADA`` y la comparación de abajo no lo nota.
    """
    tipos = set(get_args(TipoReporte))

    assert tipos == set(_COLA_ESPERADA)
    assert set(COLA_POR_TIPO) == tipos


def test_cada_tipo_nombra_la_cola_que_decidio_producto():
    """Es la ``cola`` que devuelve el acuse para que la consola diga quién lo
    revisa. Hoy es sólo una etiqueta —la fila va a ``ml_feedback`` en todos
    los casos—, pero reasignarla cambia lo que se le promete al usuario y
    tiene que ser deliberado."""
    assert COLA_POR_TIPO == _COLA_ESPERADA


def test_el_prefijo_del_servicio_es_el_del_sql_que_filtra():
    """Fija el literal ``reporte:`` y que las dos constantes coinciden.

    No demuestra que haya una sola definición: dos copias escritas a mano con
    el mismo valor también pasarían, y una copia en ``quality.py`` o dentro del
    SQL ni siquiera se ve desde aquí. Una copia que diverja la detectan los
    tests de consumidores de más abajo.

    El literal se fija aparte porque las filas ya guardadas llevan
    ``reporte:``. Cambiarlo, aunque sea en su origen y llegue igual a los tres
    módulos, dejaría fuera de Calidad los reportes anteriores, y el anti-join
    de active learning los tomaría por etiquetas y sacaría esos expedientes de
    la cola."""
    assert PREFIJO_SOURCE == PREFIJO_REPORTE == "reporte:"


@pytest.mark.parametrize("tipo", sorted(_COLA_ESPERADA))
def test_el_source_de_cada_tipo_nunca_parece_una_etiqueta(tipo):
    """Los consumidores de ML filtran por ``source = 'human'``: un reporte con
    otro source no puede convertirse en etiqueta de entrenamiento."""
    assert source_de(tipo) == f"reporte:{tipo}"


# ---------------------------------------------------------------------------
# Persistencia
# ---------------------------------------------------------------------------


def test_el_reporte_se_guarda_en_ml_feedback_como_senal_negativa(tmp_db):
    """Expediente, nota, autor y fecha: la cola de revisión que ya existe.
    ``relevante`` va a 0 porque es NOT NULL y porque un reporte es eso, una
    señal negativa sobre la fila; ``tecnologia`` queda vacía para que nadie la
    lea como etiqueta."""
    from db.users import create_user

    autor = create_user(
        email="reportes-autor@example.test",
        password_hash="test-hash",  # pragma: allowlist secret
    )

    creado = registrar_reporte(
        id_externo="REP-CCAA",
        tipo="ccaa",
        comentario="  Es de Galicia, no de Asturias  ",
        user_id=autor,
    )

    assert _filas_feedback("REP-CCAA") == [
        {
            "expediente": "REP-CCAA",
            "relevante": 0,
            "nota": "Es de Galicia, no de Asturias",
            "tecnologia": None,
            "source": "reporte:ccaa",
            "user_id": autor,
            "created_at": creado,
        }
    ]


def test_sin_comentario_la_nota_queda_vacia_y_uno_largo_se_corta(tmp_db):
    """``nota`` es NOT NULL y el servicio no confía en que la ruta haya
    acotado la longitud: lo llaman también procesos internos."""
    registrar_reporte(id_externo="REP-SIN-NOTA", tipo="otro", comentario=None, user_id=None)
    registrar_reporte(id_externo="REP-LARGO", tipo="otro", comentario="x" * 2500, user_id=None)

    assert [f["nota"] for f in _filas_feedback("REP-SIN-NOTA")] == [""]
    assert [len(str(f["nota"])) for f in _filas_feedback("REP-LARGO")] == [2000]


# ---------------------------------------------------------------------------
# Contrato con los consumidores del prefijo
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("filas_en_corpus", [0, 1], ids=["corpus_vacio", "corpus_con_filas"])
def test_la_vista_de_calidad_cuenta_los_reportes_por_tipo_y_nada_mas(tmp_db, filas_en_corpus):
    """La vista agrupa ``ml_feedback`` por el prefijo y lo quita del nombre:
    tiene que devolver exactamente los tipos del catálogo, sin mezclar las
    etiquetas humanas ni las del LLM que viven en la misma tabla.

    ``get_quality`` construye el resultado en dos ramas —tabla vacía y tabla
    con filas— y los reportes tienen que salir en las dos; la que corre en
    producción es la segunda.
    """
    from db.repositories.feedback import FeedbackRepository
    from services.analytics.quality import get_quality

    for n in range(filas_en_corpus):
        _licitacion(f"REP-Q-CORPUS-{n}")
    for tipo in ("ccaa", "ccaa", "duplicado", "adjudicatario"):
        registrar_reporte(id_externo=f"REP-Q-{tipo}", tipo=tipo, comentario=None, user_id=None)
    FeedbackRepository().insert(expediente="REP-Q-HUMANA", relevante=True, nota="ok")
    FeedbackRepository().insert(
        expediente="REP-Q-LLM", relevante=True, nota="auto", source="llm_batch"
    )

    calidad = get_quality()

    assert calidad.total_records == filas_en_corpus
    assert calidad.reportes_por_tipo == {"ccaa": 2, "duplicado": 1, "adjudicatario": 1}


def test_reportar_un_expediente_no_lo_saca_de_la_cola_de_etiquetado(tmp_db):
    """Cualquier usuario puede reportar; si eso contara como etiqueta, bastaría
    reportar para vaciar la cola de active learning. La etiqueta humana, en
    cambio, sí lo saca de las dos consultas: es lo que demuestra que cada
    anti-join está vivo y no sólo que el prefijo coincide."""
    from db.repositories.feedback import FeedbackRepository
    from db.repositories.licitaciones import LicitacionRepository

    _licitacion("REP-COLA")
    repo = LicitacionRepository()

    registrar_reporte(id_externo="REP-COLA", tipo="tecnologia", comentario=None, user_id=None)

    assert "REP-COLA" in {c["id_externo"] for c in repo.get_unlabelled_candidates(50)}
    assert "REP-COLA" in {c["id_externo"] for c in repo.get_unlabelled_random(50)}

    FeedbackRepository().insert(expediente="REP-COLA", relevante=True, nota="humana")

    assert "REP-COLA" not in {c["id_externo"] for c in repo.get_unlabelled_candidates(50)}
    assert "REP-COLA" not in {c["id_externo"] for c in repo.get_unlabelled_random(50)}
