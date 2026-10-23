"""Muestra para etiquetar «¿es TI?» a mano (`scripts/muestra_etiquetado_ti.py`).

Lo que se fija: la muestra sale sin etiquetas, estratificada y reproducible; la
vuelta solo manda lo etiquetado, valida todo antes de mandar nada y no
convierte una fila sin etiqueta en un negativo. Las pruebas del SQL usan
Postgres (`tmp_db`); las del formato, no.
"""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path
from types import ModuleType
from typing import Any

import pytest

_RUTA = Path(__file__).resolve().parents[1] / "scripts" / "muestra_etiquetado_ti.py"
_ETIQUETAS = ["SAP", "MICROSOFT", "CLOUD_INFRA"]


def _script() -> ModuleType:
    spec = importlib.util.spec_from_file_location("muestra_etiquetado_ti", _RUTA)
    assert spec is not None and spec.loader is not None
    modulo = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = modulo
    spec.loader.exec_module(modulo)
    return modulo


def _fila(id_externo: str = "EXP-1", **extra: Any) -> dict[str, Any]:
    return {
        "id_externo": id_externo,
        "estrato": "placsp|72|kw|2025",
        "fuente": "placsp",
        "fecha_publicacion": "2025-03-01",
        "titulo": "Mantenimiento del ERP",
        "descripcion": "Soporte",
        "cpv": "72267000",
        "organo_contratacion": "Ayuntamiento",
        "url": "https://contrataciondelestado.es/x",
        **extra,
    }


# ── Formato (sin BD) ───────────────────────────────────────────────────────


def test_registro_sale_sin_etiqueta() -> None:
    mod = _script()
    registro = mod.registro_sin_etiqueta(_fila())
    assert registro["es_ti"] is None
    assert registro["tecnologia"] is None
    assert registro["tecnologias_secundarias"] == []
    assert set(mod.CAMPOS_ETIQUETA) <= set(registro)
    # Ni la etiqueta de las reglas ni la probabilidad del modelo: se etiqueta leyendo.
    assert "tecnologia_reglas" not in registro and "ml_proba" not in registro


def test_escribir_y_leer_ida_y_vuelta(tmp_path: Path) -> None:
    mod = _script()
    salida = tmp_path / "m.jsonl"
    n = mod.escribir_muestra(
        [mod.registro_sin_etiqueta(_fila("A")), mod.registro_sin_etiqueta(_fila("B"))],
        salida,
        meta="total=2",
    )
    assert n == 2
    assert salida.read_text(encoding="utf-8").startswith("# Muestra estratificada")
    assert [r["id_externo"] for r in mod.leer_jsonl(salida)] == ["A", "B"]


def test_fila_sin_etiqueta_no_se_manda() -> None:
    mod = _script()
    assert mod.cuerpo_feedback(mod.registro_sin_etiqueta(_fila()), _ETIQUETAS) is None


def test_cuerpo_de_una_fila_etiquetada() -> None:
    mod = _script()
    registro = mod.registro_sin_etiqueta(_fila()) | {
        "es_ti": True,
        "tecnologia": "sap",
        "tecnologias_secundarias": ["microsoft"],
        "etiquetado_por": "ana",
        "nota": "ERP",
    }
    cuerpo = mod.cuerpo_feedback(registro, _ETIQUETAS)
    assert cuerpo == {
        "expediente": "EXP-1",
        "relevante": True,
        "nota": "[muestra_etiquetado_ti · ana] ERP",
        "tecnologia": "SAP",
        "tecnologias_secundarias": ["MICROSOFT"],
    }


@pytest.mark.parametrize(
    "cambios",
    [
        {"es_ti": "si"},
        {"es_ti": True, "tecnologia": "NO_EXISTE"},
        {"es_ti": False, "tecnologia": "SAP"},
    ],
)
def test_etiquetas_mal_formadas_se_rechazan(cambios: dict[str, Any]) -> None:
    mod = _script()
    with pytest.raises(mod.EtiquetaInvalida):
        mod.cuerpo_feedback(mod.registro_sin_etiqueta(_fila()) | cambios, _ETIQUETAS)


def test_importar_valida_todo_antes_de_mandar_nada() -> None:
    mod = _script()
    enviados: list[dict[str, Any]] = []
    registros = [
        mod.registro_sin_etiqueta(_fila("A")) | {"es_ti": True},
        mod.registro_sin_etiqueta(_fila("B")) | {"es_ti": "quizá"},
    ]
    with pytest.raises(mod.EtiquetaInvalida):
        mod.importar(registros, _ETIQUETAS, lambda c, k: enviados.append(c) or 201, semilla="s")
    assert enviados == []


def test_importar_cuenta_enviadas_sin_etiqueta_y_fallidas() -> None:
    mod = _script()
    claves: list[str] = []

    def enviar(cuerpo: dict[str, Any], clave: str) -> int:
        claves.append(clave)
        return 201 if cuerpo["expediente"] != "C" else 500

    registros = [
        mod.registro_sin_etiqueta(_fila("A")) | {"es_ti": True, "tecnologia": "SAP"},
        mod.registro_sin_etiqueta(_fila("B")),
        mod.registro_sin_etiqueta(_fila("C")) | {"es_ti": False},
    ]
    resumen = mod.importar(registros, _ETIQUETAS, enviar, semilla="s")
    assert resumen == {"enviadas": 1, "sin_etiqueta": 1, "fallidas": 1}
    assert len(set(claves)) == 2


# ── SQL (Postgres) ─────────────────────────────────────────────────────────


def _insertar(
    id_externo: str, *, fuente: str, cpv: str | None, tecnologia: str | None, fecha: str | None
) -> None:
    from db.database import connect

    with connect() as c:
        c.execute(
            "INSERT INTO licitaciones "
            "(id_externo, titulo, descripcion, fuente, cpv, tecnologia, fecha_publicacion, "
            "fecha_extraccion) VALUES (%s, %s, %s, %s, %s, %s, %s, CURRENT_TIMESTAMP)",
            (id_externo, f"Contrato {id_externo}", "texto", fuente, cpv, tecnologia, fecha),
        )


def test_estratos_y_seleccion_reproducible(tmp_db: Any) -> None:
    from db.database import connect
    from db.repositories import muestra_etiquetado as repo
    from services.ml.muestra_estratificada import repartir_cuotas

    for i in range(6):
        _insertar(f"P72-{i}", fuente="placsp", cpv="72267000", tecnologia="SAP", fecha="2025-02-01")
    _insertar("TED-48", fuente="ted", cpv="48000000", tecnologia=None, fecha="2024-05-01")
    _insertar("BULK-OLD", fuente="bulk_202001", cpv=None, tecnologia=None, fecha="2019-05-01")
    _insertar("PSCP-SF", fuente="pscp", cpv="72000000", tecnologia=None, fecha=None)
    _insertar("DUP", fuente="placsp", cpv="72267000", tecnologia="SAP", fecha="2025-02-01")
    with connect() as c:
        c.execute(
            "INSERT INTO licitaciones_duplicados (licitacion_id, canonical_id, status) "
            "VALUES ('DUP', 'P72-0', 'confirmed')"
        )

    tamanos = repo.tamanos_estratos(anio_desde=2023)
    assert tamanos == {
        "placsp|72|kw|2025": 6,
        "ted|48|sin_kw|2024": 1,
        "placsp|otros|sin_kw|antes": 1,
        "pscp|72|sin_kw|sin_fecha": 1,
    }

    cuotas = repartir_cuotas(tamanos, 6)
    primera = repo.seleccionar(cuotas=cuotas, semilla="s1", anio_desde=2023)
    segunda = repo.seleccionar(cuotas=cuotas, semilla="s1", anio_desde=2023)
    otra = repo.seleccionar(cuotas=cuotas, semilla="s2", anio_desde=2023)

    ids = [f["id_externo"] for f in primera]
    assert len(ids) == 6 and "DUP" not in ids
    assert ids == [f["id_externo"] for f in segunda]
    assert {"TED-48", "BULK-OLD", "PSCP-SF"} <= set(ids)
    assert {f["estrato"] for f in primera} == set(tamanos)
    assert len(otra) == 6
