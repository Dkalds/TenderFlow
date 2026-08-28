"""Cada decisión conserva el score que la motivó, y sólo el de la primera vez.

El producto vende priorización y hasta la revisión ``v93`` no había forma de
saber si acierta: el score se calcula en vivo y no se persistía, así que ni con
acceso total a la base se podía cruzar «lo que el Radar puso arriba» con «lo que
el equipo ganó». Estas columnas cierran ese bucle.

Lo que estos tests protegen no es que la columna exista —eso lo dice el
schema— sino la propiedad que la hace **útil**: el valor sellado es el del
momento de decidir. Los dos caminos de escritura son idempotentes
(``ON CONFLICT DO NOTHING``), y si un segundo POST reescribiera el score, la
medida quedaría contaminada con la puntuación de un instante en que nadie
decidió nada — que es exactamente el error que haría inservible el análisis de
«qué banda concentra los descartes».
"""

from __future__ import annotations

from typing import Any

import pytest

from db import radar_dismissals

pytestmark = pytest.mark.usefixtures("tmp_db")


def _fila(conn: Any, user_key: str, id_externo: str) -> tuple[Any, Any]:
    cur = conn.execute(
        "SELECT score, banda FROM radar_dismissals WHERE user_key = %s AND id_externo = %s",
        (user_key, id_externo),
    )
    fila = cur.fetchone()
    assert fila is not None, "el descarte no se guardó"
    return fila[0], fila[1]


def test_el_descarte_guarda_el_score_que_el_usuario_tenia_delante(tmp_db: Any) -> None:
    radar_dismissals.add("u-1", "EXP-1", score=82, banda="Caliente")

    assert _fila(tmp_db, "u-1", "EXP-1") == (82, "Caliente")


def test_un_segundo_descarte_no_reescribe_el_score_de_la_decision(tmp_db: Any) -> None:
    """El ``DO NOTHING`` tiene que conservar el primero, no el último.

    Escenario real: el usuario descarta con score 82, y más tarde el cliente
    reintenta el POST (reconexión, doble pulsación, replay de una mutación
    optimista) cuando el motor ya puntúa esa señal con 31. Si ganase el segundo,
    el análisis diría que descartó algo tibio cuando en realidad descartó algo
    que el Radar le estaba vendiendo como caliente — que es justo la señal de
    que el ranking no sirve.
    """
    radar_dismissals.add("u-1", "EXP-1", score=82, banda="Caliente")
    radar_dismissals.add("u-1", "EXP-1", score=31, banda="Tibia")

    assert _fila(tmp_db, "u-1", "EXP-1") == (82, "Caliente")


def test_se_puede_descartar_sin_score_y_la_fila_dice_que_no_se_supo(tmp_db: Any) -> None:
    """Descartar es la acción; medir es el efecto secundario.

    La agenda de Mi Pipeline descarta sin tener el score en pantalla, y una
    llamada por API tampoco lo manda. Eso no puede impedir el descarte, y la
    fila queda con ``NULL`` —«no se supo»— en vez de con un cero, que se
    confundiría con una señal puntuada bajísima.
    """
    radar_dismissals.add("u-1", "EXP-2")

    assert _fila(tmp_db, "u-1", "EXP-2") == (None, None)


def test_el_score_es_por_usuario_como_el_resto_de_la_tabla(tmp_db: Any) -> None:
    """Dos usuarios pueden descartar el mismo expediente con puntuaciones distintas.

    El score depende de los pesos del perfil de cada uno, así que no es una
    propiedad del expediente sino de la decisión. La clave primaria compuesta ya
    lo permitía; esto lo fija.
    """
    radar_dismissals.add("u-1", "EXP-3", score=90, banda="Caliente")
    radar_dismissals.add("u-2", "EXP-3", score=12, banda="Descarte")

    assert _fila(tmp_db, "u-1", "EXP-3") == (90, "Caliente")
    assert _fila(tmp_db, "u-2", "EXP-3") == (12, "Descarte")


def test_listar_descartes_no_cambia_de_forma_al_anadir_las_columnas(tmp_db: Any) -> None:
    """``list_ids`` sigue devolviendo sólo ids: el contrato del Radar no se movió.

    Las columnas nuevas son para analítica, no para la pantalla. Si se colaran
    en la respuesta, el frontend tendría que conocerlas y el cambio dejaría de
    ser aditivo.
    """
    radar_dismissals.add("u-1", "EXP-4", score=55, banda="Atractiva")

    assert radar_dismissals.list_ids("u-1") == ["EXP-4"]
