"""``scripts/eval_ficha.py``: el eval de la ficha con el modelo real.

Aquí nunca hay modelo: el extractor es un doble. Lo que se fija es lo que
rodea a la medición y puede hacerla mentir —un caso que falla y desaparece de
la cuenta, un ``--check`` que pasa porque no había nada que comprobar— y que el
script no puede abrir la base de datos aunque el entorno apunte a producción.
"""

from __future__ import annotations

import json
import sys
from collections.abc import Callable, Iterator
from datetime import date
from pathlib import Path
from typing import Any

import pytest
from pydantic import SecretStr

import scripts.eval_ficha as eval_ficha
from services.rag.fact_sheet import ExtraccionHechos
from services.rag.ficha_eval import MetricasFamilia, agregar, medir_caso
from services.rag.ficha_golden import (
    CasoGolden,
    escribir_golden,
    escribir_paginas,
    leer_caso,
    leer_pendientes,
)
from shared.tender_facts import TenderFactSheet

_URL_PRODUCCION = "postgresql://prod.invalid:5432/tenderflow?sslmode=verify-full"

_CITA_PRECIO = "El criterio precio tendrá una ponderación del 60 por ciento del total"
_CITA_CALIDAD = "La calidad técnica de la oferta se valorará con hasta cuarenta puntos"
_CITA_MEJORAS = "Se valorarán las mejoras ofertadas sin coste para la Administración"
_TEXTO = f"{_CITA_PRECIO}. {_CITA_CALIDAD}. {_CITA_MEJORAS}."


def _criterio(peso: float, nombre: str, cita: str) -> dict[str, Any]:
    return {
        "name": nombre,
        "description": "Criterio de adjudicación",
        "weight_pct": peso,
        "criterion_type": "other",
        "confidence": 0.9,
        "evidence": [{"documento_id": 7, "page_number": 1, "quote": cita}],
    }


_PRECIO = _criterio(60, "Precio", _CITA_PRECIO)
_CALIDAD = _criterio(40, "Calidad", _CITA_CALIDAD)
_MEJORAS = _criterio(5, "Mejoras", _CITA_MEJORAS)


def _crear(
    raiz: Path,
    nombre: str,
    *,
    completo: bool,
    hechos: list[dict[str, Any]] | None = None,
    veredicto: str | None = "correcto",
) -> Path:
    carpeta = raiz / nombre
    golden = CasoGolden.model_validate(
        {
            "licitacion_id": nombre,
            "completo": completo,
            "capturado_el": date(2026, 10, 11).isoformat(),
            "extraction_version": "tender-facts-v6",
            "model": "modelo-x",
            "status_origen": "extracted",
            "hechos": {
                "award_criteria": [
                    {"veredicto": veredicto, "hecho": h}
                    for h in (hechos if hechos is not None else [_PRECIO, _CALIDAD])
                ]
            },
        }
    )
    escribir_golden(carpeta, golden)
    escribir_paginas(
        carpeta,
        [
            {
                "documento_id": 7,
                "page_number": 1,
                "tipo": "legal",
                "filename": "pcap.pdf",
                "texto": _TEXTO,
            }
        ],
    )
    return carpeta


def _extractor(
    por_caso: dict[str, list[dict[str, Any]]] | None = None,
    *,
    falla_en: str | None = None,
    llamadas: list[str] | None = None,
) -> Callable[..., ExtraccionHechos]:
    """Doble de ``extraer_hechos``: devuelve los criterios que se le digan."""

    def extraer(
        paginas: list[dict[str, Any]], *, licitacion_id: str, model: str
    ) -> ExtraccionHechos:
        if llamadas is not None:
            llamadas.append(licitacion_id)
        if licitacion_id == falla_en:
            raise ValueError("El modelo devolvió una respuesta vacía")
        criterios = (por_caso or {}).get(licitacion_id, [_PRECIO, _CALIDAD])
        return ExtraccionHechos(
            facts=TenderFactSheet.model_validate({"award_criteria": criterios}),
            invalidos=0,
            inverificables=0,
            seleccionadas=paginas,
        )

    return extraer


@pytest.fixture(autouse=True)
def _sin_efectos_fuera_del_test(monkeypatch: pytest.MonkeyPatch) -> None:
    # `main()` vacía `DATABASE_URL` en el entorno y en `settings`: que no salga del test.
    from config import settings

    monkeypatch.setenv("DATABASE_URL", "")
    monkeypatch.setattr(settings, "DATABASE_URL", SecretStr(""))
    monkeypatch.setattr(sys, "path", [*sys.path])


def _con_extractor(
    monkeypatch: pytest.MonkeyPatch, extraer: Callable[..., ExtraccionHechos]
) -> None:
    monkeypatch.setattr(eval_ficha, "extraer_hechos", extraer)


def test_no_abre_conexiones_aunque_el_entorno_apunte_a_produccion(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    import psycopg

    import db.connection as conexion
    from config import settings

    monkeypatch.setenv("DATABASE_URL", _URL_PRODUCCION)
    monkeypatch.setattr(settings, "DATABASE_URL", SecretStr(_URL_PRODUCCION))
    intentos: list[str] = []

    def _conexion_prohibida(*_args: Any, **_kwargs: Any) -> Any:
        intentos.append("conexión")
        raise AssertionError("el eval intentó abrir una conexión a la BD")

    monkeypatch.setattr(conexion, "_get_conn", _conexion_prohibida)
    monkeypatch.setattr(psycopg, "connect", _conexion_prohibida)
    urls: list[str] = []

    def _llm_falso(**_: Any) -> Iterator[str]:
        urls.append(conexion._database_url())
        yield json.dumps({"award_criteria": [_PRECIO]})

    monkeypatch.setattr("services.rag.fact_sheet.stream_llm_response", _llm_falso)
    _crear(tmp_path, "caso-a", completo=True)

    assert eval_ficha.main(["--raiz", str(tmp_path)]) == 0

    assert intentos == []
    # La URL de producción no llega a la extracción: el script la vació antes.
    assert urls == [""]


def test_un_caso_con_veredictos_pendientes_se_salta_y_se_avisa(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    _crear(tmp_path, "revisado", completo=True)
    _crear(tmp_path, "a-medias", completo=True, veredicto=None)
    llamadas: list[str] = []

    _informe, resultados, _selector = eval_ficha.evaluar(
        tmp_path, model="m", extraer=_extractor(llamadas=llamadas)
    )

    assert [r.nombre for r in resultados] == ["revisado"]
    assert llamadas == ["revisado"]
    assert "a-medias" in capsys.readouterr().err


def test_si_la_extraccion_de_un_caso_lanza_los_demas_se_evaluan(tmp_path: Path) -> None:
    _crear(tmp_path, "caso-a", completo=True)
    _crear(tmp_path, "caso-b", completo=True)

    informe, resultados, _selector = eval_ficha.evaluar(
        tmp_path, model="m", extraer=_extractor(falla_en="caso-b")
    )

    assert len(resultados) == 2
    assert informe.casos_fallidos == 1
    assert resultados[1].fallo == "El modelo devolvió una respuesta vacía"
    # Dos casos con dos positivos cada uno; el fallido no aporta ningún acierto.
    assert informe.totales["cobertura_completos"] == 0.5


def test_evaluar_un_solo_caso(tmp_path: Path) -> None:
    _crear(tmp_path, "caso-a", completo=True)
    _crear(tmp_path, "caso-b", completo=True)

    _informe, resultados, _selector = eval_ficha.evaluar(
        tmp_path, model="m", solo="caso-b", extraer=_extractor()
    )

    assert [r.nombre for r in resultados] == ["caso-b"]


def test_evaluar_suma_la_cobertura_del_selector_aunque_la_extraccion_falle(tmp_path: Path) -> None:
    _crear(tmp_path, "caso-a", completo=True)
    _crear(tmp_path, "caso-b", completo=False)

    _informe, _resultados, selector = eval_ficha.evaluar(
        tmp_path, model="m", extraer=_extractor(falla_en="caso-b")
    )

    assert selector == {"award_criteria": (4, 4)}


def test_sin_casos_evaluables_devuelve_2(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    assert eval_ficha.main(["--raiz", str(tmp_path)]) == 2
    assert "capturar_ficha_golden" in capsys.readouterr().err


def _minimos(raiz: Path, **minimos: float) -> None:
    (raiz / "minimos.json").write_text(
        json.dumps(
            {
                "medido_el": "2026-10-11",
                "model": "m",
                "extraction_version": "tender-facts-v6",
                "ejecuciones": 3,
                "minimos": minimos,
            }
        ),
        encoding="utf-8",
    )


def test_check_pasa_cuando_se_cumplen_los_minimos(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _crear(tmp_path, "caso-a", completo=True)
    _crear(tmp_path, "caso-b", completo=False)
    _minimos(
        tmp_path,
        precision_completos=1.0,
        cobertura_completos=1.0,
        conservados_parciales=1.0,
        selector_cobertura=1.0,
    )
    _con_extractor(monkeypatch, _extractor())

    assert eval_ficha.main(["--raiz", str(tmp_path), "--check"]) == 0


def test_check_devuelve_1_por_debajo_del_minimo(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    _crear(tmp_path, "caso-a", completo=True)
    _minimos(tmp_path, precision_completos=0.9)
    # Dos aciertos y un hecho que no está en el golden: precisión 2/3.
    _con_extractor(monkeypatch, _extractor({"caso-a": [_PRECIO, _CALIDAD, _MEJORAS]}))

    assert eval_ficha.main(["--raiz", str(tmp_path), "--check"]) == 1
    assert "precision_completos" in capsys.readouterr().out


def test_check_devuelve_1_sin_poblacion_que_comprobar(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # Solo un caso parcial: no hay precisión estricta que medir.
    _crear(tmp_path, "caso-a", completo=False)
    _minimos(tmp_path, precision_completos=0.5)
    _con_extractor(monkeypatch, _extractor())

    assert eval_ficha.main(["--raiz", str(tmp_path), "--check"]) == 1


def test_check_devuelve_1_si_no_hay_minimos_json(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    _crear(tmp_path, "caso-a", completo=True)
    _con_extractor(monkeypatch, _extractor())

    assert eval_ficha.main(["--raiz", str(tmp_path), "--check"]) == 1
    assert "minimos.json" in capsys.readouterr().out


def test_formatear_dice_sin_datos_suficientes_con_menos_de_diez_positivos(tmp_path: Path) -> None:
    caso = leer_caso(_crear(tmp_path, "caso-a", completo=True))
    informe = agregar(
        [medir_caso(caso, _extractor()(caso.paginas, licitacion_id="caso-a", model="m"))]
    )

    texto = eval_ficha.formatear(informe, {"award_criteria": (2, 2)})

    (fila,) = [linea for linea in texto.splitlines() if linea.startswith("award_criteria")]
    assert "sin datos suficientes" in fila
    assert "%" not in fila
    assert "lots" not in texto


def test_formatear_da_porcentajes_con_poblacion_suficiente() -> None:
    doce = MetricasFamilia(extraidos=12, positivos=12, aciertos=9, falsos_positivos=3)
    informe = agregar([])
    informe.completos["award_criteria"] = doce

    texto = eval_ficha.formatear(informe, {})

    (fila,) = [linea for linea in texto.splitlines() if linea.startswith("award_criteria")]
    assert "75,0 %" in fila and "sin datos suficientes" not in fila


def test_pendientes_escribe_los_sin_juzgar_de_un_caso_parcial(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    parcial = _crear(tmp_path, "parcial", completo=False)
    completo = _crear(tmp_path, "completo", completo=True)
    extra = {"parcial": [_PRECIO, _MEJORAS], "completo": [_PRECIO, _MEJORAS]}
    _con_extractor(monkeypatch, _extractor(extra))

    assert eval_ficha.main(["--raiz", str(tmp_path), "--pendientes"]) == 0

    ((familia, hecho),) = leer_pendientes(parcial)
    assert (familia, hecho["name"]) == ("award_criteria", "Mejoras")
    # En un caso completo lo que no casa es un falso positivo, no un pendiente.
    assert leer_pendientes(completo) == []
    # Y el golden no se toca: sigue sin veredictos en null.
    assert [h.veredicto for h in leer_caso(parcial).golden.hechos["award_criteria"]] == [
        "correcto",
        "correcto",
    ]


def test_fijar_minimos_escribe_la_base_con_tres_ejecuciones(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _crear(tmp_path, "caso-a", completo=True)
    _crear(tmp_path, "caso-b", completo=False)
    llamadas: list[str] = []
    _con_extractor(monkeypatch, _extractor(llamadas=llamadas))

    assert eval_ficha.main(["--raiz", str(tmp_path), "--fijar-minimos", "--model", "modelo-y"]) == 0

    assert len(llamadas) == 3 * 2
    escrito = json.loads((tmp_path / "minimos.json").read_text(encoding="utf-8"))
    assert escrito["minimos"] == {
        "precision_completos": 0.98,
        "cobertura_completos": 0.98,
        "conservados_parciales": 0.98,
        "selector_cobertura": 1.0,
    }
    assert (escrito["ejecuciones"], escrito["model"]) == (3, "modelo-y")
    assert escrito["extraction_version"] == "tender-facts-v6"
    assert escrito["medido_el"] == date.today().isoformat()


def test_fijar_minimos_no_baja_un_minimo_existente(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    _crear(tmp_path, "caso-a", completo=True)
    _crear(tmp_path, "caso-b", completo=False)
    _minimos(tmp_path, precision_completos=0.99, cobertura_completos=0.5)
    antes = (tmp_path / "minimos.json").read_bytes()
    _con_extractor(monkeypatch, _extractor())

    assert eval_ficha.main(["--raiz", str(tmp_path), "--fijar-minimos"]) == 1

    assert (tmp_path / "minimos.json").read_bytes() == antes
    assert "precision_completos" in capsys.readouterr().out


def test_fijar_minimos_sin_casos_completos_no_escribe_nada(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _crear(tmp_path, "caso-b", completo=False)
    _con_extractor(monkeypatch, _extractor())

    assert eval_ficha.main(["--raiz", str(tmp_path), "--fijar-minimos"]) == 1
    assert not (tmp_path / "minimos.json").exists()


def test_salida_escribe_el_resultado_en_json(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _crear(tmp_path / "casos", "caso-a", completo=True)
    _con_extractor(monkeypatch, _extractor())
    salida = tmp_path / "resultado.json"

    assert eval_ficha.main(["--raiz", str(tmp_path / "casos"), "--salida", str(salida)]) == 0

    escrito = json.loads(salida.read_text(encoding="utf-8"))
    assert escrito["totales"]["precision_completos"] == 1.0
    assert escrito["totales"]["selector_cobertura"] == 1.0
    assert escrito["casos"][0]["nombre"] == "caso-a"
    assert escrito["completos"]["award_criteria"]["aciertos"] == 2
