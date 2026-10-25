"""``scripts/inventario_uso.py``: el dato para decidir qué superficie sobra.

Fija lo que promete su docstring sobre fixtures con la forma de las fuentes
reales (CSV exportado de Vercel Analytics, respuesta de ``/api/v1/query`` de
Prometheus y texto de ``GET /metrics``) y comprueba que el catálogo se sigue
leyendo de los ficheros reales del frontend y de la superficie de la API.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from scripts import inventario_uso as inv

_FIX = Path(__file__).parent / "fixtures" / "inventario_uso"


def _fila(tabla: str, espacio: str, vista: str = "—") -> str:
    vista_md = vista if vista == "—" else f"`{vista}`"
    for linea in tabla.splitlines():
        if linea.startswith(f"| `{espacio}` | {vista_md} |"):
            return linea
    raise AssertionError(f"sin fila para {espacio}/{vista}:\n{tabla}")


# ── Catálogo ────────────────────────────────────────────────────────────────


def test_catalogo_real_del_frontend() -> None:
    espacios = inv.leer_espacios()
    vistas = inv.leer_vistas()
    assert espacios[0] == "resumen"
    assert {"radar", "mercado", "competencia", "ops"} <= set(espacios)
    assert len(espacios) == len(set(espacios))
    assert vistas["mercado"][:2] == ["tiempo", "cpv"]
    assert "agenda" in vistas["mi-pipeline"]  # la entrada de una sola línea
    assert set(vistas) <= set(espacios)


def test_catalogo_real_de_la_api() -> None:
    ops = inv.leer_operaciones()
    assert "DELETE /api/v1/etiquetas/{etiqueta_id}" in ops  # línea base
    assert "GET /api/v1/admin/api-keys" in ops  # NUEVAS de check_api_surface
    assert not any(op.startswith("#") for op in ops)


# ── Espacios y vistas ───────────────────────────────────────────────────────


def test_csv_prefiere_visitantes_y_separa_vistas() -> None:
    uso = inv.leer_csv_espacios(_FIX / "vercel_espacio_abierto.csv")
    assert uso.metrica == "visitors"
    assert uso.por_espacio["radar"] == 980
    assert uso.por_vista[("mercado", "tiempo")] == 90


def test_csv_sin_columna_espacio_falla(tmp_path: Path) -> None:
    roto = tmp_path / "roto.csv"
    roto.write_text("pagina,visitors\n/radar,3\n", encoding="utf-8")
    with pytest.raises(ValueError, match="espacio"):
        inv.leer_csv_espacios(roto)


def test_tabla_espacios_marca_lo_que_queda_bajo_el_umbral() -> None:
    uso = inv.leer_csv_espacios(_FIX / "vercel_espacio_abierto.csv")
    espacios = ["radar", "mercado", "ops", "resumen"]
    vistas = {"mercado": ["tiempo", "cpv", "calendario"]}
    tabla = inv.tabla_espacios(espacios, vistas, uso)

    assert _fila(tabla, "radar").endswith("| 980 | 97.9 |  |")
    assert "**sí**" in _fila(tabla, "mercado")  # 15 de 1001 = 1,5 %
    assert "**sí**" in _fila(tabla, "ops")
    # Un espacio sin ninguna apertura sale con 0, no desaparece.
    assert "| 0 | 0.0 | **sí**" in _fila(tabla, "resumen")
    # Un espacio retirado que aún llega en el CSV se señala, no se mezcla.
    assert "fuera del catálogo" in _fila(tabla, "empresas")
    # Las vistas se miden sobre las aperturas de vista de su espacio (94).
    assert "| 90 | 95.7 |  |" in _fila(tabla, "mercado", "tiempo")
    assert "**sí**" in _fila(tabla, "mercado", "cpv")
    assert "| 0 | 0.0 | **sí**" in _fila(tabla, "mercado", "calendario")
    assert "fuera del catálogo" in _fila(tabla, "mercado", "inventada")
    assert "Total de aperturas de espacio: 1001." in tabla


def test_tabla_espacios_sin_datos_no_inventa_cifras() -> None:
    tabla = inv.tabla_espacios(["radar", "mercado"], {"mercado": ["tiempo"]}, None)
    assert inv.PENDIENTE in _fila(tabla, "radar")
    assert inv.PENDIENTE in _fila(tabla, "mercado", "tiempo")
    assert not any(c.isdigit() for c in tabla.split("|---|")[-1])


# ── API ─────────────────────────────────────────────────────────────────────

_OPS = [
    "GET /api/v1/radar",
    "GET /api/v1/licitaciones/{id_externo:path}",
    "DELETE /api/v1/etiquetas/{etiqueta_id}",
    "POST /api/v1/nunca",
]


def test_prom_json_suma_por_operacion_y_normaliza_convertidores() -> None:
    cuentas = inv.contar_prom_json(json.loads((_FIX / "prom_query.json").read_text("utf-8")))
    assert cuentas["GET /api/v1/licitaciones/{id_externo}"] == 33
    assert inv.sin_uso(_OPS, cuentas) == [
        "DELETE /api/v1/etiquetas/{etiqueta_id}",  # 0,2 por extrapolación de increase
        "POST /api/v1/nunca",  # ninguna serie en la ventana
    ]


def test_prom_json_con_error_falla() -> None:
    with pytest.raises(ValueError):
        inv.contar_prom_json({"status": "error", "error": "bad_data"})


def test_metrics_texto_junta_codigos_de_estado() -> None:
    cuentas = inv.contar_metrics_texto((_FIX / "metrics.txt").read_text("utf-8"))
    assert cuentas == {
        "GET /api/v1/radar": 12.0,
        "GET /api/v1/licitaciones/{id_externo}": 1.0,
    }


def test_tabla_api_lista_candidatas_y_handlers_fuera() -> None:
    cuentas = inv.contar_prom_json(json.loads((_FIX / "prom_query.json").read_text("utf-8")))
    tabla = inv.tabla_api(_OPS, cuentas, "fixture")
    assert "**sin ninguna: 2**" in tabla
    assert "- `POST /api/v1/nunca`" in tabla
    assert "- `GET /api/v1/radar`" not in tabla
    assert "`GET /api/v1/fantasma` (7)" in tabla
    assert "none" not in tabla


def test_tabla_api_sin_fuente_queda_pendiente() -> None:
    assert inv.PENDIENTE in inv.tabla_api(_OPS, None, "")


def test_consultar_prometheus_rechaza_esquemas_raros() -> None:
    with pytest.raises(ValueError):
        inv.consultar_prometheus("file:///etc/passwd")


def test_main_con_fixtures(capsys: pytest.CaptureFixture[str]) -> None:
    assert inv.main(["api", "--metrics", str(_FIX / "metrics.txt")]) == 0
    salida = capsys.readouterr().out
    assert "desde el último arranque" in salida
    assert "Candidatas a encoger" in salida
