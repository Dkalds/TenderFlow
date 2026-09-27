"""El golden set real de «¿es TI?» y familias (plan de tres niveles, F2).

Sustituye a los 27 ejemplos de `golden_set.jsonl` como gate del binario: sale
de la revisión humana (`ml_feedback`, `source='revision_ti'`), lleva fuente y
fecha, y su holdout es el 50 % más reciente, fijo.
"""

from __future__ import annotations

import json
from dataclasses import replace
from pathlib import Path
from types import ModuleType
from unittest.mock import MagicMock

import pytest

from services.ml import golden_ti
from services.ml.golden_ti import (
    PREFIJO_CORTE_HOLDOUT,
    EjemploGoldenTi,
    a_linea,
    asignar_splits,
    cargar_golden_ti,
    corte_mediano,
    ejemplo_desde_fila,
    leer_corte_holdout,
    repartir,
)


def _ejemplo(id_: str, fecha: str, **cambios: object) -> EjemploGoldenTi:
    base = EjemploGoldenTi(
        id_externo=id_,
        fuente="pscp",
        fecha=fecha,
        titulo="t",
        descripcion="",
        cpv=None,
        es_ti=True,
        familias=(),
        fabricantes=(),
        etiquetado_por="humano",
        etiquetado_at="2026-09-28T00:00:00+00:00",
        split="tune",
    )
    return replace(base, **cambios)  # type: ignore[arg-type]  # cambios de test


def test_el_holdout_es_la_mitad_mas_reciente() -> None:
    ejemplos = [_ejemplo(f"E{i}", f"2026-0{i}-01") for i in range(1, 5)]
    splits = {e.id_externo: e.split for e in asignar_splits(ejemplos)}
    assert splits == {"E1": "tune", "E2": "tune", "E3": "holdout", "E4": "holdout"}


def _fila(expediente: str, fecha_publicacion: str | None) -> dict[str, object]:
    return {
        "expediente": expediente,
        "fuente": "placsp",
        "fecha_publicacion": fecha_publicacion,
        "titulo": "t",
        "descripcion": "",
        "cpv": None,
        "relevante": 1,
        "tecnologia": None,
        "tecnologias_secundarias": None,
        "created_at": "2026-09-28T10:00:00+00:00",
    }


def test_la_primera_exportacion_fija_el_corte_en_la_mediana(tmp_path: Path) -> None:
    """Sin corte en el fichero, el corte es la fecha que deja en holdout la
    mitad más reciente: con seis fechas distintas, las tres últimas."""
    ejemplos = [_ejemplo(f"E{i}", f"2026-0{i}-15") for i in range(1, 7)]

    repartidos, corte = repartir(ejemplos, tmp_path / "golden.jsonl")

    assert corte == corte_mediano(ejemplos) == "2026-04-15"
    assert [e.split for e in repartidos] == ["tune"] * 3 + ["holdout"] * 3


def test_un_ejemplo_antiguo_anadido_despues_no_mueve_los_existentes(tmp_path: Path) -> None:
    """El reparto es temporal y fijo: el corte de la primera exportación se
    guarda en la cabecera y las siguientes reparten contra él. Recalcular la
    mediana con el ejemplo nuevo pasaría E2 de tune a holdout."""
    ruta = tmp_path / "golden.jsonl"
    originales = [_ejemplo(f"E{i}", f"2026-0{i}-01") for i in range(1, 5)]
    primera, corte = repartir(originales, ruta)
    ruta.write_text(f"# cabecera\n{PREFIJO_CORTE_HOLDOUT}{corte}\n", encoding="utf-8")

    segunda, corte_segunda = repartir([*originales, _ejemplo("E0", "2025-12-01")], ruta)

    assert corte_segunda == corte == "2026-03-01"
    antes = {e.id_externo: e.split for e in primera}
    despues = {e.id_externo: e.split for e in segunda}
    assert {id_: despues[id_] for id_ in antes} == antes
    assert despues["E0"] == "tune"


def test_sin_fecha_de_publicacion_va_a_tune_con_aviso(monkeypatch: pytest.MonkeyPatch) -> None:
    """Una licitación sin ``fecha_publicacion`` no puede ser «de las más
    recientes»: va a tune y se avisa. Antes llegaba como la cadena "None", que
    ordena detrás de cualquier fecha y caía en holdout."""
    log = MagicMock()
    monkeypatch.setattr(golden_ti, "log", log)
    sin_fecha = ejemplo_desde_fila(_fila("EXP-SIN-FECHA", None))
    fechadas = [ejemplo_desde_fila(_fila(f"EXP-{i}", f"2026-0{i}-01")) for i in range(1, 5)]

    assert sin_fecha.fecha == ""
    splits = {e.id_externo: e.split for e in asignar_splits([*fechadas, sin_fecha])}

    assert splits["EXP-SIN-FECHA"] == "tune"
    assert [splits[f"EXP-{i}"] for i in range(1, 5)] == ["tune", "tune", "holdout", "holdout"]
    assert log.warning.call_args.args[0] == "golden_ti.sin_fecha"
    assert log.warning.call_args.kwargs["id_externo"] == "EXP-SIN-FECHA"


def _exportador_sin_bd(
    monkeypatch: pytest.MonkeyPatch, filas: list[dict[str, object]], golden_del_repo: Path
) -> ModuleType:
    """El script de exportación con la BD sustituida por ``filas`` y el golden
    del repo apuntando a ``golden_del_repo`` (el test no lee el fichero real)."""
    import scripts.exportar_golden_ti as exportador

    monkeypatch.setattr("db.database.init_db", lambda: None)
    monkeypatch.setattr(
        "db.repositories.feedback.FeedbackRepository.filas_revision_ti",
        lambda _self: list(filas),
    )
    monkeypatch.setattr(golden_ti, "RUTA_GOLDEN_TI", golden_del_repo)
    return exportador


def test_el_exportador_congela_el_corte_entre_exportaciones(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """De punta a punta, sin BD: la primera exportación escribe el corte en la
    cabecera y la segunda, con un expediente antiguo revisado después, lo
    respeta."""
    filas = [_fila(f"EXP-{i}", f"2026-0{i}-01") for i in range(1, 5)]
    ruta = tmp_path / "golden.jsonl"
    exportador = _exportador_sin_bd(monkeypatch, filas, golden_del_repo=ruta)

    assert exportador.main(["--salida", str(ruta)]) == 0
    primera = {e.id_externo: e.split for e in cargar_golden_ti(ruta)}
    filas.append(_fila("EXP-0", "2025-12-01"))
    assert exportador.main(["--salida", str(ruta)]) == 0
    segunda = {e.id_externo: e.split for e in cargar_golden_ti(ruta)}

    assert leer_corte_holdout(ruta) == "2026-03-01"
    assert primera == {"EXP-1": "tune", "EXP-2": "tune", "EXP-3": "holdout", "EXP-4": "holdout"}
    assert {id_: segunda[id_] for id_ in primera} == primera
    assert segunda["EXP-0"] == "tune"


def test_una_salida_nueva_reutiliza_el_corte_del_golden_del_repo(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """``--salida`` a una ruta sin corte no calcula una mediana propia si el
    golden del repo ya tiene uno: copiar esa salida encima del golden movería
    el corte sin que nada lo avisara. Aquí la mediana sería 2026-03-01."""
    golden_del_repo = tmp_path / "golden_del_repo.jsonl"
    golden_del_repo.write_text(f"# cabecera\n{PREFIJO_CORTE_HOLDOUT}2026-02-01\n", encoding="utf-8")
    filas = [_fila(f"EXP-{i}", f"2026-0{i}-01") for i in range(1, 5)]
    exportador = _exportador_sin_bd(monkeypatch, filas, golden_del_repo=golden_del_repo)
    salida = tmp_path / "otra" / "golden.jsonl"

    assert exportador.main(["--salida", str(salida)]) == 0

    assert leer_corte_holdout(salida) == "2026-02-01"
    assert {e.id_externo: e.split for e in cargar_golden_ti(salida)} == {
        "EXP-1": "tune",
        "EXP-2": "holdout",
        "EXP-3": "holdout",
        "EXP-4": "holdout",
    }


def test_el_corte_se_lee_de_la_cabecera(tmp_path: Path) -> None:
    ruta = tmp_path / "golden.jsonl"
    ruta.write_text(
        f"# cabecera\n{PREFIJO_CORTE_HOLDOUT}2026-05-01\n"
        + a_linea(_ejemplo("E1", "2026-06-01", split="holdout"))
        + "\n",
        encoding="utf-8",
    )

    assert leer_corte_holdout(ruta) == "2026-05-01"
    assert [e.id_externo for e in cargar_golden_ti(ruta)] == ["E1"]
    assert leer_corte_holdout(tmp_path / "no_existe.jsonl") is None


def test_una_fila_de_revision_separa_familias_de_fabricantes() -> None:
    fila = {
        "expediente": "EXP-1",
        "fuente": "placsp",
        "fecha_publicacion": "2026-09-01",
        "titulo": "Implantación de SAP S/4HANA",
        "descripcion": None,
        "cpv": "72000000",
        "relevante": 1,
        "tecnologia": "ERP",
        "tecnologias_secundarias": '["SAP"]',
        "created_at": "2026-09-28T10:00:00+00:00",
    }
    ejemplo = ejemplo_desde_fila(fila)
    assert ejemplo.es_ti is True
    assert ejemplo.familias == ("ERP",)
    assert ejemplo.fabricantes == ("SAP",)
    assert ejemplo.descripcion == ""


def test_una_tecnologia_desconocida_se_descarta_con_aviso(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Una tecnología que no está en TECH_LABEL_TIPO no se cuela como negativo
    silencioso: se descarta (no entra en familias ni en fabricantes) y queda
    rastro -- un aviso estructurado con el expediente y el valor malo -- para
    que un label retirado o un dato legacy corrupto no desaparezca sin dejar
    huella, tal y como ya exige `cargar_golden_ti` para el fichero."""
    log = MagicMock()
    monkeypatch.setattr(golden_ti, "log", log)
    fila = {
        "expediente": "EXP-9",
        "fuente": "placsp",
        "fecha_publicacion": "2026-09-01",
        "titulo": "t",
        "descripcion": "",
        "cpv": None,
        "relevante": 1,
        "tecnologia": "NO_EXISTE",
        "tecnologias_secundarias": '["SAP"]',
        "created_at": "2026-09-28T10:00:00+00:00",
    }

    ejemplo = ejemplo_desde_fila(fila)

    assert ejemplo.familias == ()
    assert ejemplo.fabricantes == ("SAP",)  # la conocida se conserva
    assert log.warning.call_args.args[0] == "golden_ti.tecnologia_desconocida"
    assert log.warning.call_args.kwargs["expediente"] == "EXP-9"
    assert log.warning.call_args.kwargs["tecnologia"] == "NO_EXISTE"


def test_un_campo_obligatorio_ausente_es_un_error_claro(tmp_path: Path) -> None:
    ruta = tmp_path / "golden.jsonl"
    incompleto = json.loads(a_linea(_ejemplo("E1", "2026-09-01")))
    del incompleto["titulo"]
    ruta.write_text(json.dumps(incompleto), encoding="utf-8")
    with pytest.raises(ValueError, match="titulo"):
        cargar_golden_ti(ruta)


def test_ida_y_vuelta_por_el_fichero(tmp_path: Path) -> None:
    ruta = tmp_path / "golden.jsonl"
    ejemplo = _ejemplo("E1", "2026-09-01", familias=("ERP",), split="holdout")
    ruta.write_text("# cabecera\n\n" + a_linea(ejemplo) + "\n", encoding="utf-8")
    assert cargar_golden_ti(ruta) == [ejemplo]


def test_una_etiqueta_fuera_del_vocabulario_es_un_error(tmp_path: Path) -> None:
    ruta = tmp_path / "golden.jsonl"
    ruta.write_text(
        a_linea(_ejemplo("E1", "2026-09-01", familias=("NO_EXISTE",))), encoding="utf-8"
    )
    with pytest.raises(ValueError, match="NO_EXISTE"):
        cargar_golden_ti(ruta)


def test_el_fichero_del_repo_carga() -> None:
    """Vacío es válido, roto no. Con ejemplos, el fichero trae su corte y sus
    ejemplos están repartidos contra él (hoy solo tiene la cabecera: ni
    ejemplos ni corte, que fija la primera exportación con revisión humana)."""
    ejemplos = cargar_golden_ti()
    corte = leer_corte_holdout()

    if not ejemplos:
        return
    assert corte is not None
    en_el_fichero = sorted(ejemplos, key=lambda e: (e.fecha, e.id_externo))
    assert asignar_splits(ejemplos, corte) == en_el_fichero
