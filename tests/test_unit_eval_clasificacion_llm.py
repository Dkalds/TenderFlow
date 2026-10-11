"""``scripts/eval_clasificacion_llm.py`` (``make eval-clasificacion``).

El eval llama al LLM real y por eso no corre en CI; lo que sí se puede fijar
sin red es lo que lo hace fiable: que no toca ninguna base de datos aunque el
entorno apunte a producción, y que sus recuentos —inestables, mayoría, cambios
entre dos ejecuciones— dicen lo que el informe afirma.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any

import pytest
from pydantic import SecretStr

import scripts.eval_clasificacion_llm as eval_clf
from services.llm_tech_labeling import Clasificacion

# Sin credenciales: basta una URL no vacía que no resuelva a ningún host.
_URL_PRODUCCION = "postgresql://prod.invalid:5432/tenderflow?sslmode=verify-full"
_REDIS_PRODUCCION = "rediss://prod.invalid:6379"


def _resultado(
    id_externo: str, *es_ti: bool | None, esperado: bool | None = None
) -> dict[str, Any]:
    return {
        "id_externo": id_externo,
        "esperado": esperado,
        "respuestas": [{"es_ti": v, "confianza": 0.9, "tecnologias": []} for v in es_ti],
    }


def _todo_ti(_fila: dict[str, Any]) -> Clasificacion:
    return Clasificacion(scores={}, es_ti=True, confianza_es_ti=0.9)


def _nada_ti(_fila: dict[str, Any]) -> Clasificacion:
    return Clasificacion(scores={}, es_ti=False, confianza_es_ti=0.9)


@pytest.fixture
def entorno_de_produccion(monkeypatch: pytest.MonkeyPatch) -> None:
    """Lo que ve el script lanzado desde un checkout cuyo ``.env`` apunta a producción."""
    from config import settings

    monkeypatch.setenv("DATABASE_URL", _URL_PRODUCCION)
    monkeypatch.setenv("REDIS_URL", _REDIS_PRODUCCION)
    monkeypatch.setattr(settings, "DATABASE_URL", SecretStr(_URL_PRODUCCION))
    monkeypatch.setattr(settings, "REDIS_URL", _REDIS_PRODUCCION)
    # `main()` añade la raíz del repo a `sys.path`; que no se quede puesta.
    monkeypatch.setattr(sys, "path", [*sys.path])


@pytest.mark.usefixtures("entorno_de_produccion")
def test_no_abre_conexiones_aunque_el_entorno_apunte_a_produccion(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    import psycopg

    import db.connection as conexion
    import services.llm_tech_labeling as etiquetado
    from config import settings

    def _conexion_prohibida(*_args: Any, **_kwargs: Any) -> Any:
        raise AssertionError("el eval intentó abrir una conexión a la BD")

    monkeypatch.setattr(conexion, "_get_conn", _conexion_prohibida)
    monkeypatch.setattr(psycopg, "connect", _conexion_prohibida)

    vistas: list[tuple[str, str, str]] = []

    def _llm_falso(lic: dict[str, Any], *, model: str) -> Clasificacion:
        vistas.append((str(lic["id_externo"]), conexion._database_url(), settings.REDIS_URL))
        return Clasificacion(scores={}, es_ti=True, confianza_es_ti=0.9)

    monkeypatch.setattr(etiquetado, "classify_licitacion", _llm_falso)
    entrada = tmp_path / "filas.jsonl"
    entrada.write_text(
        '# comentario\n{"id_externo": "A", "titulo": "t", "descripcion": "d", "cpv": null}\n',
        encoding="utf-8",
    )

    assert eval_clf.main(["--entrada", str(entrada), "--repeticiones", "2"]) == 0

    # Las dos llamadas se hicieron ya sin BD ni Redis a la vista.
    assert vistas == [("A", "", ""), ("A", "", "")]


@pytest.mark.usefixtures("entorno_de_produccion")
def test_con_el_golden_vacio_lo_dice_y_no_llama_al_llm(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.setattr(eval_clf, "filas_del_golden", list)

    def _no_debe_llamarse(_fila: dict[str, Any]) -> Any:
        raise AssertionError("no hay nada que clasificar")

    assert eval_clf.main([], clasificar=_no_debe_llamarse) == 2
    assert "--entrada" in capsys.readouterr().out


@pytest.mark.usefixtures("entorno_de_produccion")
def test_guarda_el_resultado_y_lo_compara_con_el_de_otra_ejecucion(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    entrada = tmp_path / "filas.json"
    entrada.write_text(
        json.dumps([{"id_externo": "A", "es_ti": True}, {"id_externo": "B", "es_ti": False}]),
        encoding="utf-8",
    )
    antes = tmp_path / "antes.json"
    base = ["--entrada", str(entrada), "--repeticiones", "1"]

    assert eval_clf.main([*base, "--salida", str(antes)], clasificar=_todo_ti) == 0
    guardado = json.loads(antes.read_text(encoding="utf-8"))
    assert [r["id_externo"] for r in guardado["resultados"]] == ["A", "B"]
    capsys.readouterr()

    assert eval_clf.main([*base, "--contra", str(antes)], clasificar=_nada_ti) == 0

    salida = capsys.readouterr().out
    assert "2 cambian de mayoría" in salida
    assert "A: es TI → no es TI" in salida
    assert "Acierto por mayoría: 1/2 = 50%" in salida


@pytest.mark.usefixtures("entorno_de_produccion")
def test_min_acierto_convierte_el_informe_en_un_gate(tmp_path: Path) -> None:
    entrada = tmp_path / "filas.json"
    entrada.write_text(json.dumps([{"id_externo": "A", "es_ti": False}]), encoding="utf-8")

    argumentos = ["--entrada", str(entrada), "--repeticiones", "1", "--min-acierto", "0.9"]

    assert eval_clf.main(argumentos, clasificar=_todo_ti) == 1
    assert eval_clf.main(argumentos, clasificar=_nada_ti) == 0


@pytest.mark.usefixtures("entorno_de_produccion")
def test_si_todas_las_llamadas_fallan_no_informa_de_un_acierto_del_cero_por_ciento(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    entrada = tmp_path / "filas.json"
    entrada.write_text(json.dumps([{"id_externo": "A", "es_ti": True}]), encoding="utf-8")

    def _sin_api_key(_fila: dict[str, Any]) -> Any:
        raise RuntimeError("El LLM devolvió una respuesta vacía")

    assert eval_clf.main(["--entrada", str(entrada)], clasificar=_sin_api_key) == 2
    salida = capsys.readouterr().out
    assert "no se evaluó nada" in salida
    assert "Acierto" not in salida


def test_un_fallo_del_llm_se_anota_y_el_eval_sigue() -> None:
    llamadas = iter([RuntimeError("429"), Clasificacion(scores={}, es_ti=False)])

    def _a_ratos(_fila: dict[str, Any]) -> Clasificacion:
        siguiente = next(llamadas)
        if isinstance(siguiente, Exception):
            raise siguiente
        return siguiente

    [resultado] = eval_clf.evaluar([{"id_externo": "A"}], _a_ratos, repeticiones=2)

    assert resultado["respuestas"][0] == {"error": "RuntimeError: 429"}
    assert resultado["respuestas"][1]["es_ti"] is False
    resumen = eval_clf.resumir([resultado])
    assert (resumen["errores"], resumen["inestables"]) == (1, [])


def test_inestable_es_que_las_repeticiones_no_coinciden_en_es_ti() -> None:
    resultados = [
        _resultado("estable", True, True, True),
        _resultado("duda", True, False, True),
        # Un `None` (el modelo no contestó la pregunta) no es una discrepancia.
        _resultado("a-medias", False, None, False),
    ]

    resumen = eval_clf.resumir(resultados)

    assert resumen["inestables"] == ["duda"]
    assert resumen["confianza_media_inestables"] == 0.9
    assert resumen["sin_es_ti"] == 1


def test_la_mayoria_no_inventa_un_veredicto_en_un_empate() -> None:
    assert eval_clf.mayoria(_resultado("x", True, True, False)) is True
    assert eval_clf.mayoria(_resultado("x", True, False)) is None
    assert eval_clf.mayoria(_resultado("x", None)) is None
    # Y un empate no cuenta como acierto, sea cual sea la respuesta esperada.
    resumen = eval_clf.resumir([_resultado("x", True, False, esperado=False)])
    assert (resumen["etiquetadas"], resumen["aciertos"]) == (1, 0)


def test_comparar_solo_mira_los_anuncios_presentes_en_las_dos_ejecuciones() -> None:
    antes = [_resultado("A", True, True), _resultado("B", False, True), _resultado("C", True)]
    despues = [_resultado("A", False, False), _resultado("B", False, False), _resultado("D", True)]

    comparacion = eval_clf.comparar(antes, despues)

    assert comparacion["comunes"] == 2
    assert comparacion["cambios_de_mayoria"] == [
        {"id_externo": "A", "antes": True, "despues": False},
        {"id_externo": "B", "antes": None, "despues": False},
    ]
    assert (comparacion["inestables_antes"], comparacion["inestables_despues"]) == (1, 0)
