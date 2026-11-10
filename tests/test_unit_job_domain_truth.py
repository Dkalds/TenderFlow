"""La auditoría de verdad del dato como job del plano de cron (ADR-033)."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import patch

import pytest
import yaml

from scheduler.jobs import domain_truth
from scripts.check_job_parity import check

_WORKFLOWS = Path(__file__).resolve().parent.parent / ".github" / "workflows"


def test_avisa_de_los_umbrales_superados() -> None:
    with (
        patch("services.verdad_dominio.medir_bd", return_value={"ute": {"pct": 9}}),
        patch("services.verdad_dominio.evaluar", return_value=["UTE: 9 % > 5 %"]),
        patch("observability.notify") as notify,
    ):
        assert domain_truth.run() == {"violaciones": 1}

    assert "UTE: 9 % > 5 %" in notify.call_args.kwargs["body"]


def test_sin_violaciones_no_manda_correo() -> None:
    with (
        patch("services.verdad_dominio.medir_bd", return_value={}),
        patch("services.verdad_dominio.evaluar", return_value=[]),
        patch("observability.notify") as notify,
    ):
        assert domain_truth.run() == {"violaciones": 0}

    notify.assert_not_called()


def test_si_la_medicion_revienta_el_job_falla() -> None:
    """Un fallo tiene que verse como fallo del job: el plano lo reintenta y
    alerta. Tragárselo daría por hecha una auditoría que no midió nada."""
    with (
        patch("services.verdad_dominio.medir_bd", side_effect=RuntimeError("bd caída")),
        pytest.raises(RuntimeError),
    ):
        domain_truth.run()


def test_la_paridad_da_el_job_por_cubierto_por_la_api() -> None:
    filas, problemas = check()
    fila = next(f for f in filas if f["job"] == "domain_truth_audit")
    assert fila["plane"] == "render"
    assert "tenderflow-api" in fila["cubierto_por"]
    assert not [p for p in problemas if "domain_truth_audit" in p]


@pytest.mark.parametrize("workflow", ["domain-truth.yml", "pliegos.yml"])
def test_el_workflow_de_un_job_del_plano_ya_no_tiene_cron(workflow: str) -> None:
    """Con `schedule:` aquí y el job en el plano de la API, correría dos veces:
    dos correos por umbral, o cada pliego descargado y embebido dos veces.
    PyYAML lee la clave `on` como True."""
    disparadores = yaml.safe_load((_WORKFLOWS / workflow).read_text(encoding="utf-8"))[True]
    assert "schedule" not in disparadores
    assert "workflow_dispatch" in disparadores
