"""Golden de la ficha del pliego: modelos y ficheros de los casos.

Sin BD y sin LLM. Lo que se prueba aquí es que un caso mal formado no llegue a
medirse como si valiera, y que el fichero que guarda horas de etiquetado no se
pueda quedar a medias.
"""

from __future__ import annotations

import json
from datetime import date
from pathlib import Path
from typing import Any

import pytest
from pydantic import ValidationError

from services.rag.ficha_golden import (
    CAMPOS_CLAVE,
    CasoGolden,
    escribir_golden,
    escribir_paginas,
    escribir_pendientes,
    leer_caso,
    leer_pendientes,
    listar_casos,
    modelo_de,
    negativos,
    positivos,
    propuesta_desde_ficha,
    sin_revisar,
)
from shared.tender_facts import TenderFactSheet

_HOY = date(2026, 10, 11)


def _criterio(peso: float | None, nombre: str = "Precio") -> dict[str, Any]:
    return {
        "name": nombre,
        "description": "Criterio de adjudicación",
        "weight_pct": peso,
        "criterion_type": "price",
        "confidence": 0.9,
        "evidence": [
            {"documento_id": 7, "page_number": 3, "quote": "ponderación del 60 por ciento"}
        ],
    }


def _caso(hechos: dict[str, list[dict[str, Any]]], *, completo: bool = False) -> CasoGolden:
    return CasoGolden.model_validate(
        {
            "licitacion_id": "EXP-1",
            "completo": completo,
            "capturado_el": "2026-10-11",
            "extraction_version": "tender-facts-v6",
            "model": "modelo-x",
            "status_origen": "extracted",
            "hechos": hechos,
        }
    )


def test_campos_clave_cubre_todas_las_familias_y_sus_campos_existen() -> None:
    assert set(CAMPOS_CLAVE) == set(TenderFactSheet.model_fields)
    for familia, campos in CAMPOS_CLAVE.items():
        assert set(campos) <= set(modelo_de(familia).model_fields), familia


def test_un_hecho_que_no_encaja_en_su_familia_se_rechaza() -> None:
    sin_nombre = _criterio(60)
    del sin_nombre["name"]

    with pytest.raises(ValidationError):
        _caso({"award_criteria": [{"veredicto": "correcto", "hecho": sin_nombre}]})


def test_una_familia_desconocida_se_rechaza() -> None:
    with pytest.raises(ValidationError):
        _caso({"familia_inventada": [{"veredicto": "correcto", "hecho": _criterio(60)}]})


def test_positivos_negativos_y_sin_revisar() -> None:
    golden = _caso(
        {
            "award_criteria": [
                {"veredicto": "correcto", "hecho": _criterio(50, "Calidad")},
                {
                    "veredicto": "corregido",
                    "hecho": _criterio(60),
                    "valor_extraido": {"weight_pct": 40},
                },
                {"veredicto": "añadido", "hecho": _criterio(10, "Plazo")},
                {"veredicto": "incorrecto", "hecho": _criterio(25, "Inventado")},
                {"veredicto": None, "hecho": _criterio(5, "Pendiente")},
            ]
        }
    )

    assert [p.weight_pct for p in positivos(golden)["award_criteria"]] == [50, 60, 10]
    # El incorrecto, y el valor original del corregido: los dos son errores conocidos.
    assert [n.weight_pct for n in negativos(golden)["award_criteria"]] == [40, 25]
    assert sin_revisar(golden) == 1
    assert positivos(golden)["lots"] == []


def test_escribir_paginas_omite_la_uri_y_conserva_las_paginas_vacias(tmp_path: Path) -> None:
    paginas = [
        {
            "documento_id": 7,
            "page_number": 1,
            "tipo": "legal",
            "filename": "pcap.pdf",
            "texto": "Cláusula primera. Ñandú.",
            "start_offset": 0,
            "end_offset": 24,
            "ocr": False,
            "uri": "https://contrataciondelestado.es/doc?token=secreto",
        },
        {"documento_id": 7, "page_number": 2, "texto": "   ", "uri": "https://x.test"},
    ]

    escritos = escribir_paginas(tmp_path, paginas)

    crudo = (tmp_path / "paginas.jsonl").read_bytes()
    assert escritos == len(crudo)
    lineas = crudo.decode("utf-8").split("\n")[:-1]
    # La página vacía se queda: producción la persiste, y la primera página de
    # cada documento es la que el selector trata como portada. Quitarla haría
    # que el eval eligiera otra portada que producción.
    assert [json.loads(linea)["page_number"] for linea in lineas] == [1, 2]
    assert all("uri" not in json.loads(linea) for linea in lineas)
    assert "token" not in crudo.decode("utf-8")
    assert "Ñandú" in lineas[0]


def test_un_texto_con_separadores_de_linea_unicode_se_relee_entero(tmp_path: Path) -> None:
    # U+2028, U+2029 y U+0085 salen de algunos PDF. `json.dumps` no los escapa
    # con `ensure_ascii=False`, y `str.splitlines()` parte la línea por ellos.
    texto = "antes" + chr(0x2028) + "medio" + chr(0x2029) + "casi" + chr(0x85) + "después"
    escribir_golden(tmp_path, _caso({}))
    escribir_paginas(tmp_path, [{"documento_id": 7, "page_number": 1, "texto": texto}])

    (pagina,) = leer_caso(tmp_path).paginas

    assert pagina["texto"] == texto


def test_los_ficheros_del_caso_se_escriben_con_saltos_lf(tmp_path: Path) -> None:
    # En Windows `write_text` traduce a CRLF, y el hook `mixed-line-ending`
    # tumbaría el primer intento de cada commit de un caso.
    golden = _caso({"award_criteria": [{"veredicto": "correcto", "hecho": _criterio(60)}]})

    escribir_golden(tmp_path, golden)
    escribir_paginas(tmp_path, [{"documento_id": 7, "page_number": 1, "texto": "a"}])
    escribir_pendientes(tmp_path, [("award_criteria", _criterio(10, "Plazo"))])

    for nombre in ("golden.json", "paginas.jsonl", "pendientes.json"):
        assert b"\r" not in (tmp_path / nombre).read_bytes(), nombre


def test_golden_se_relee_igual_y_no_deja_temporal(tmp_path: Path) -> None:
    carpeta = tmp_path / "caso-a"
    golden = _caso({"award_criteria": [{"veredicto": "correcto", "hecho": _criterio(60)}]})
    escribir_paginas(
        carpeta, [{"documento_id": 7, "page_number": 3, "texto": "ponderación del 60 por ciento"}]
    )

    escribir_golden(carpeta, golden)
    caso = leer_caso(carpeta)

    assert caso.nombre == "caso-a"
    assert caso.golden == golden
    assert [p["page_number"] for p in caso.paginas] == [3]
    assert sorted(p.name for p in carpeta.iterdir()) == ["golden.json", "paginas.jsonl"]


def test_listar_casos_solo_devuelve_carpetas_con_golden_y_en_orden(tmp_path: Path) -> None:
    golden = _caso({})
    escribir_golden(tmp_path / "b-caso", golden)
    escribir_golden(tmp_path / "a-caso", golden)
    (tmp_path / "sin-golden").mkdir()
    (tmp_path / "minimos.json").write_text("{}", encoding="utf-8")

    assert [c.name for c in listar_casos(tmp_path)] == ["a-caso", "b-caso"]
    assert listar_casos(tmp_path / "no-existe") == []


def test_propuesta_desde_ficha_deja_todo_sin_veredicto() -> None:
    ficha = {
        "status": "needs_review",
        "extraction_version": "tender-facts-v6",
        "model": "modelo-x",
        "facts": {"award_criteria": [_criterio(60)], "lots": []},
    }

    golden = propuesta_desde_ficha("EXP-1", ficha, completo=True, hoy=_HOY)

    assert golden.completo is True
    assert golden.capturado_el == _HOY
    assert (golden.status_origen, golden.extraction_version, golden.model) == (
        "needs_review",
        "tender-facts-v6",
        "modelo-x",
    )
    assert list(golden.hechos) == ["award_criteria"]
    assert [h.veredicto for h in golden.hechos["award_criteria"]] == [None]
    assert sin_revisar(golden) == 1


def test_propuesta_de_una_ficha_fallida_no_tiene_hechos() -> None:
    fallida = {
        "status": "failed",
        "extraction_version": "tender-facts-v6",
        "model": "m",
        "facts": None,
    }

    con_fila = propuesta_desde_ficha("EXP-1", fallida, completo=False, hoy=_HOY)
    sin_fila = propuesta_desde_ficha("EXP-2", None, completo=False, hoy=_HOY)

    assert con_fila.hechos == {} and con_fila.status_origen == "failed"
    assert sin_fila.hechos == {} and sin_fila.status_origen is None


def test_los_pendientes_se_releen_y_el_fichero_desaparece_al_vaciarse(tmp_path: Path) -> None:
    pendientes = [("award_criteria", _criterio(10, "Plazo")), ("lots", {"description": "Lote 1"})]

    escribir_pendientes(tmp_path, pendientes)
    assert leer_pendientes(tmp_path) == pendientes

    escribir_pendientes(tmp_path, [])
    assert not (tmp_path / "pendientes.json").exists()
    assert leer_pendientes(tmp_path) == []
