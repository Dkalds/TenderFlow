"""El vocabulario de estados y sus etiquetas no pueden divergir.

Modo de fallo que fija este fichero: ``shared/estados.py`` gana un código nuevo
—como ``AGREG`` y ``EJEC``, que entraron con el conector de la PSCP catalana— y
nadie le da etiqueta. No falla nada. Lo que ocurre es que ``GET /meta/filters``,
que desde 2026-08-27 recorta el selector con ``filtrar_estados_canonicos``,
ofrece el código crudo al usuario ("AGREG"), ``estado_label`` lo devuelve tal
cual, y las tablas del frontend indexadas por la etiqueta castellana
(``ESTADO_CHART_COLOR``, ``ESTADO_STYLES``) caen a su valor por defecto.

Es exactamente la regresión que ``web/src/lib/estados.ts`` documenta haber
arreglado una vez: "el scatter pintaba sus mil puntos del mismo color bajo el
rótulo «color por estado»".
"""

from __future__ import annotations

from services.classification import ESTADO_LABELS, estado_label
from shared.estados import ESTADOS_CANONICOS, ESTADOS_CERRADOS


def test_todo_codigo_canonico_tiene_etiqueta_legible() -> None:
    faltan = sorted(ESTADOS_CANONICOS - set(ESTADO_LABELS))

    assert not faltan, (
        f"Códigos canónicos sin etiqueta: {faltan}. El selector de /meta/filters "
        "los ofrecería crudos y el color por estado caería al valor por defecto."
    )


def test_no_hay_etiquetas_para_codigos_que_no_existen() -> None:
    """La dirección contraria: una etiqueta huérfana es copy que nadie ve nunca."""
    sobran = sorted(set(ESTADO_LABELS) - ESTADOS_CANONICOS)

    assert not sobran, f"Etiquetas de códigos fuera del vocabulario canónico: {sobran}"


def test_los_estados_cerrados_son_parte_del_vocabulario() -> None:
    """Dos preguntas distintas, un solo vocabulario: no pueden salirse de él."""
    assert set(ESTADOS_CERRADOS) <= ESTADOS_CANONICOS


def test_las_etiquetas_nuevas_son_legibles_y_no_el_codigo() -> None:
    """Que la clave exista no basta: 'AGREG' como etiqueta sería el mismo fallo."""
    for codigo in ("AGREG", "EJEC"):
        etiqueta = estado_label(codigo)
        assert etiqueta != codigo
        assert etiqueta.strip()


def test_un_codigo_desconocido_se_devuelve_tal_cual() -> None:
    """Comportamiento existente que no cambia: mejor el código que una mentira."""
    assert estado_label("XXNOEXISTE") == "XXNOEXISTE"
    assert estado_label(None) == "Desconocido"
