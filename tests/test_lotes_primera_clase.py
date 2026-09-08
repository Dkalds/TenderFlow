"""Los lotes son parte del contrato, no un detalle interno (C1.4).

`GET /licitaciones/{id}` devolvía el expediente sin sus lotes, así que un
multi-lote se presentaba como uno solo con el presupuesto total — la misma
confusión que `EFFECTIVE_BUDGET_SQL` resolvió del lado del cálculo y que seguía
viva del lado de lo que el usuario ve.

`db/repositories/publico.py` ya tenía la consulta para la superficie anónima:
lo que faltaba era exponerla en la ficha autenticada y en el export.
"""

from __future__ import annotations

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


class TestContrato:
    def test_la_ficha_devuelve_los_lotes(self) -> None:
        from api.routes.licitaciones import LicitacionDetail

        campo = LicitacionDetail.model_fields.get("lotes")
        assert campo is not None, "la ficha no expone los lotes"

    def test_el_lote_trae_importe_cpv_y_plazo(self) -> None:
        """Los tres campos que el ítem pide, no solo el número."""
        from api.routes.licitaciones import LoteOut

        assert {"numero", "titulo", "cpv", "importe", "fecha_limite"} <= set(LoteOut.model_fields)

    def test_sin_lotes_la_lista_esta_vacia_no_ausente(self) -> None:
        """Lote único implícito es el caso mayoritario, y no es «no medido»."""
        from api.routes.licitaciones import LicitacionDetail

        campo = LicitacionDetail.model_fields["lotes"]
        assert campo.default_factory is not None

    def test_el_export_acepta_por_lote(self) -> None:
        from api.app import app

        operacion = app.openapi()["paths"]["/api/v1/exports/download"]["get"]
        nombres = {p["name"] for p in operacion.get("parameters", [])}
        assert "por_lote" in nombres

    def test_por_lote_es_opcional(self) -> None:
        """Añadirlo no puede cambiar lo que reciben los clientes de hoy."""
        from api.app import app

        operacion = app.openapi()["paths"]["/api/v1/exports/download"]["get"]
        param = next(p for p in operacion["parameters"] if p["name"] == "por_lote")
        assert not param.get("required", False)
        assert param["schema"].get("default") is False


class TestConsultas:
    def test_los_lotes_se_ordenan_numericamente(self) -> None:
        """`ORDER BY numero` como texto pone el lote 10 antes del 2."""
        fuente = (ROOT / "db" / "repositories" / "licitaciones.py").read_text(encoding="utf-8")
        cuerpo = re.search(r"def lotes_de\(.*?return rows_to_dicts", fuente, re.S)
        assert cuerpo, "no se encontró lotes_de"
        assert "CAST(numero AS INTEGER)" in cuerpo.group(0)

    def test_el_export_por_lote_conserva_los_sin_lote(self) -> None:
        """Un LEFT JOIN, no un INNER: si no, el export pierde la mayoría."""
        fuente = (ROOT / "db" / "repositories" / "licitaciones.py").read_text(encoding="utf-8")
        cuerpo = re.search(r"def licitaciones_por_lote\(.*?return rows_to_dicts", fuente, re.S)
        assert cuerpo, "no se encontró licitaciones_por_lote"
        assert "LEFT JOIN lotes" in cuerpo.group(0)
        assert "INNER JOIN lotes" not in cuerpo.group(0)

    def test_la_lista_vacia_no_lanza_consulta(self) -> None:
        from db.repositories.licitaciones import licitaciones_por_lote

        assert licitaciones_por_lote([]) == []
