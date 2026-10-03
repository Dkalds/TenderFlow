"""Puerta de `npm audit` con excepciones fechadas (`scripts/check_npm_audit.py`).

Lo que hace que una lista de excepciones sea una puerta y no un agujero son sus
tres modos de fallo: un aviso que no está en la lista, una excepción caducada y
una excepción que ya no tapa nada. Se comprueban contra el informe real del
2026-10-03 —recortado, sin red— porque su forma es justo la que engaña: cinco
paquetes «vulnerables» y un único aviso.
"""

from __future__ import annotations

from datetime import date, timedelta
from pathlib import Path

import pytest

from scripts import check_npm_audit as puerta

_ROOT = Path(__file__).resolve().parent.parent
_CI = _ROOT / ".github" / "workflows" / "ci.yml"
_SCRIPT = "scripts/check_npm_audit.py"

_BRACES = "GHSA-vfj7-8cjw-p6xm"
_EXCEPCION = puerta.Excepcion(
    ghsa=_BRACES,
    paquete="braces",
    alta=date(2026, 10, 3),
    caduca=date(2026, 11, 3),
    motivo="sin versión corregida",
)


def _hereda(paquete: str, de: str) -> dict:
    return {"name": paquete, "severity": "high", "via": [de]}


def _con_aviso(paquete: str, ghsa: str, severidad: str) -> dict:
    return {
        "name": paquete,
        "severity": severidad,
        "via": [
            {
                "source": 1240992,
                "name": paquete,
                "title": f"aviso de {paquete}",
                "url": f"https://github.com/advisories/{ghsa}",
                "severity": severidad,
            }
        ],
    }


def _informe(*vulnerables: dict) -> dict:
    return {"auditReportVersion": 2, "vulnerabilities": {v["name"]: v for v in vulnerables}}


#: La cadena del 2026-10-03: solo `braces` trae aviso, el resto lo hereda.
_INFORME_REAL = _informe(
    _hereda("eslint-config-next", "@next/eslint-plugin-next"),
    _hereda("@next/eslint-plugin-next", "fast-glob"),
    _hereda("fast-glob", "micromatch"),
    _hereda("micromatch", "braces"),
    _con_aviso("braces", _BRACES, "high"),
)


def test_los_paquetes_que_heredan_no_cuentan_como_avisos() -> None:
    assert list(puerta.avisos(_INFORME_REAL)) == [_BRACES]


def test_el_informe_real_pasa_con_la_excepcion_vigente() -> None:
    fallos, exceptuados = puerta.evaluar(_INFORME_REAL, (_EXCEPCION,), date(2026, 10, 3))

    assert fallos == []
    assert len(exceptuados) == 1
    assert "quedan 31 días" in exceptuados[0]


def test_la_excepcion_vale_el_dia_de_caducidad_y_falla_al_siguiente() -> None:
    ultimo_dia, _ = puerta.evaluar(_INFORME_REAL, (_EXCEPCION,), _EXCEPCION.caduca)
    dia_siguiente, _ = puerta.evaluar(
        _INFORME_REAL, (_EXCEPCION,), _EXCEPCION.caduca + timedelta(days=1)
    )

    assert ultimo_dia == []
    assert len(dia_siguiente) == 1
    assert "caducó el 2026-11-03" in dia_siguiente[0]


def test_un_aviso_alto_sin_excepcion_falla_aunque_otro_este_exceptuado() -> None:
    """El motivo de no quedarse con el rojo permanente: el segundo aviso se ve."""
    informe = _informe(
        _con_aviso("braces", _BRACES, "high"),
        _con_aviso("otro-paquete", "GHSA-aaaa-bbbb-cccc", "critical"),
    )

    fallos, exceptuados = puerta.evaluar(informe, (_EXCEPCION,), date(2026, 10, 3))

    assert len(fallos) == 1
    assert "GHSA-aaaa-bbbb-cccc [critical] otro-paquete" in fallos[0]
    assert len(exceptuados) == 1


def test_un_aviso_moderado_no_bloquea() -> None:
    """Mismo umbral que el `--audit-level=high` al que sustituye."""
    informe = _informe(_con_aviso("otro-paquete", "GHSA-aaaa-bbbb-cccc", "moderate"))

    assert puerta.evaluar(informe, (), date(2026, 10, 3)) == ([], [])


@pytest.mark.parametrize(
    "informe",
    [
        _informe(),
        # Rebajado a moderado: sigue en el informe, pero ya no hay nada que tapar.
        _informe(_con_aviso("braces", _BRACES, "moderate")),
    ],
    ids=["el-aviso-desaparecio", "el-aviso-ya-no-bloquea"],
)
def test_una_excepcion_que_no_tapa_nada_falla(informe: dict) -> None:
    fallos, exceptuados = puerta.evaluar(informe, (_EXCEPCION,), date(2026, 10, 3))

    assert len(fallos) == 1
    assert "la excepción sobra" in fallos[0]
    assert exceptuados == []


@pytest.mark.parametrize(
    "salida",
    [
        "",
        "npm error code ENOTFOUND",
        '{"error": {"code": "ENOAUDIT", "summary": "audit endpoint returned an error"}}',
        '{"auditReportVersion": 2}',
    ],
    ids=["vacia", "no-es-json", "error-del-registro", "sin-vulnerabilities"],
)
def test_lo_que_no_es_un_informe_no_se_cuenta_como_cero_avisos(salida: str) -> None:
    assert puerta._parsear(salida) is None


def test_sin_informe_la_puerta_falla(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.setattr(puerta, "_informe", lambda: None)

    assert puerta.main() == 1
    assert "NO MEDIDO" in capsys.readouterr().err


def test_main_aplica_las_excepciones_del_script(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.setattr(puerta, "_informe", lambda: _INFORME_REAL)
    monkeypatch.setattr(puerta, "EXCEPCIONES", (_EXCEPCION,))
    monkeypatch.setattr(puerta, "_hoy", lambda: date(2026, 10, 3))
    monkeypatch.delenv("GITHUB_ACTIONS", raising=False)

    assert puerta.main() == 0
    assert f"EXCEPTUADO {_BRACES}" in capsys.readouterr().out


def test_las_excepciones_declaradas_tienen_motivo_y_plazo_corto() -> None:
    """Sobre la lista de verdad: una excepción a 2099 es una desactivación."""
    for excepcion in puerta.EXCEPCIONES:
        assert puerta._GHSA.fullmatch(excepcion.ghsa), excepcion.ghsa
        assert excepcion.motivo.strip(), f"{excepcion.ghsa} sin motivo"
        vida = (excepcion.caduca - excepcion.alta).days
        assert 0 < vida <= puerta.MAX_DIAS_EXCEPCION, f"{excepcion.ghsa} dura {vida} días"


def test_ci_audita_npm_a_traves_de_la_puerta() -> None:
    """Cableado: un `npm audit` a secas en el job no conoce las excepciones."""
    yaml = pytest.importorskip("yaml")
    pasos = yaml.safe_load(_CI.read_text(encoding="utf-8"))["jobs"]["audit"]["steps"]
    comandos = [p["run"] for p in pasos if isinstance(p.get("run"), str)]

    assert any(_SCRIPT in c for c in comandos), f"el job audit de ci.yml no ejecuta {_SCRIPT}"
    assert not [c for c in comandos if "npm audit" in c]
