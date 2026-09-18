"""C3.1 — la imagen de la API arranca, y sirve, sin las dependencias del pipeline.

`docker/Dockerfile.api` instala `requirements-api.txt`, que no trae lxml,
scikit-learn, scipy, statsmodels ni networkx. Este módulo es el smoke de import
**por entrypoint** que el backlog pedía para que el corte no se descubra en el
primer despliegue:

- **API** (`APP_PROFILE=api`, `uvicorn api.app:app`): arranca en un proceso
  aparte cuyo `MetaPathFinder` solo deja importar lo que fija
  `requirements-api.txt` —lo más parecido a la imagen sin construirla—, y sin
  haber intentado siquiera importar un paquete del pipeline.
- **Worker** (`APP_PROFILE=worker`): la misma imagen construida con
  `REQUIREMENTS_FILE=requirements-pipeline.txt`; lo que importan su cola y su
  plano de cron está en ese lockfile.
- **Caminos de request que usaban el pipeline**: con los paquetes vetados, cada
  uno falla de la forma que su ruta sabe traducir a 503 (o degrada), y no con
  un 500.

Por qué un subproceso y no `sys.modules`: `tests/test_unit_dockerfile_api.py`
documenta lo caro que sale descargar y recargar `api.app` dentro del proceso de
pytest. Aquí el proceso hijo nace limpio y muere con lo que haya importado.
"""

from __future__ import annotations

import asyncio
import json
import os
import re
import subprocess
import sys
from pathlib import Path
from typing import Any

import pytest
from fastapi import HTTPException

from api.dependencias_pipeline import PAQUETES_DEL_PIPELINE, paquete_del_pipeline_ausente

ROOT = Path(__file__).resolve().parent.parent

#: Paquetes de primer nivel del propio repositorio: no vienen de ningún lockfile.
_PRIMERA_PARTE = frozenset(
    {"api", "config", "db", "llm", "observability", "scheduler", "scraper", "services", "shared"}
)

#: Lo que corre el proceso hijo. Solo deja importar la biblioteca estándar, el
#: propio repositorio y las distribuciones que fija el lockfile de la imagen:
#: todo lo demás que el entorno de desarrollo tenga instalado (pytest, rich,
#: scikit-learn…) se comporta como en la imagen, es decir, no existe. Así los
#: `try: import x` opcionales toman la misma rama que en producción.
#:
#: Importa el entrypoint y, si se le pide, ejercita los caminos de request que
#: usaban el pipeline. Imprime en la última línea un JSON con lo que pasó.
_SONDA = r"""
import importlib, importlib.abc, json, re, sys
from importlib.metadata import packages_distributions

PERMITIDAS = frozenset(json.loads(sys.argv[1]))
PRIMERA_PARTE = frozenset(json.loads(sys.argv[2]))
ENTRADAS = json.loads(sys.argv[3])
CAMINOS = sys.argv[4] == "1"
_POR_MODULO = packages_distributions()
_NORM = re.compile(r"[-_.]+")
vetados = set()

class _SoloElLockfile(importlib.abc.MetaPathFinder):
    def find_spec(self, name, path, target=None):
        raiz = name.split(".", 1)[0]
        if raiz in sys.stdlib_module_names or raiz in PRIMERA_PARTE:
            return None
        distribuciones = _POR_MODULO.get(raiz)
        if not distribuciones:
            return None
        if any(_NORM.sub("-", d).lower() in PERMITIDAS for d in distribuciones):
            return None
        vetados.add(raiz)
        raise ModuleNotFoundError(f"No module named {name!r} (fuera del lockfile)", name=name)

sys.meta_path.insert(0, _SoloElLockfile())
previos = {m.split(".", 1)[0] for m in sys.modules}

for entrada in ENTRADAS:
    importlib.import_module(entrada)

# Foto del arranque, antes de ejercitar los caminos de request (que SÍ intentan
# importar el pipeline, y es lo que se quiere comprobar de ellos).
modulos_arranque = sorted({m.split(".", 1)[0] for m in sys.modules} - previos)
vetados_arranque = sorted(vetados)

caminos = {}
if CAMINOS:
    import asyncio
    from starlette.responses import Response

    from api.dependencias_pipeline import paquete_del_pipeline_ausente

    # /publico/cobertura: sin lxml, el inventario tiene que leerse igual.
    from api.routes.publico import cobertura
    caminos["cobertura_fuentes"] = len(asyncio.run(cobertura(Response())).fuentes)

    # /explain: la carga del clasificador falla por una dependencia del pipeline.
    import api.model_cache as mc
    mc._resolve_artifact = lambda name: None
    try:
        mc._cargar()
        caminos["explain"] = "cargo"
    except Exception as exc:
        caminos["explain"] = paquete_del_pipeline_ausente(exc) or repr(exc)

    # /analytics/clusters: TF-IDF es scikit-learn.
    from services.analytics.clusters import _tfidf_embeddings
    try:
        _tfidf_embeddings(["uno dos tres cuatro"])
        caminos["clusters"] = "calculo"
    except Exception as exc:
        caminos["clusters"] = paquete_del_pipeline_ausente(exc) or repr(exc)

    # /analytics/forecast: Holt-Winters cae a regresión lineal y lo declara.
    import pandas as pd
    from services.analytics import forecast
    hist = pd.DataFrame({"mes": pd.date_range("2025-01-01", periods=6, freq="MS"),
                         "valor": [1.0, 2.0, 3.0, 4.0, 5.0, 6.0]})
    tabla = forecast.forecast_volume_from_monthly(hist, months_ahead=3)
    caminos["forecast"] = sorted(set(tabla["modelo"]))

    # Partners: sin networkx no hay comunidades, pero la respuesta sale.
    from services.partners import _detect_communities
    aristas = [{"source": a, "target": b, "contratos": 1}
               for a, b in (("a", "b"), ("b", "c"), ("c", "d"))]
    caminos["partners_comunidades"] = len(_detect_communities({"a", "b", "c", "d"}, aristas))

print(json.dumps({
    "modulos": modulos_arranque,
    "vetados": vetados_arranque,
    "caminos": caminos,
}))
"""


def _sonda(
    entradas: list[str], *, lockfile: Path, perfil: str, caminos: bool = False
) -> dict[str, Any]:
    env = {
        **os.environ,
        "ENV": "dev",
        "APP_PROFILE": perfil,
        "PYTHONIOENCODING": "utf-8",
        # Sin BD: el arranque no la necesita, y un DATABASE_URL heredado del
        # entorno de quien corre los tests no debe decidir nada aquí.
        "DATABASE_URL": "",
    }
    proc = subprocess.run(
        [
            sys.executable,
            "-c",
            _SONDA,
            json.dumps(sorted(_permitidas(lockfile))),
            json.dumps(sorted(_PRIMERA_PARTE)),
            json.dumps(entradas),
            "1" if caminos else "0",
        ],
        cwd=ROOT,
        env=env,
        capture_output=True,
        text=True,
        encoding="utf-8",
        timeout=180,
    )
    assert proc.returncode == 0, (
        f"importar {entradas} solo con lo que instala {lockfile.name} falló — la "
        f"imagen reventaría igual al arrancar:\n{proc.stderr[-4000:]}"
    )
    ultima = [linea for linea in proc.stdout.splitlines() if linea.startswith("{")][-1]
    return json.loads(ultima)


_NORMALIZA = re.compile(r"[-_.]+")

#: Distribuciones que el entorno de desarrollo necesita por ser Windows y que el
#: lockfile, compilado para Linux, omite a propósito (ver `LOCK_TARGET` en el
#: Makefile). En la imagen no existen ni hacen falta: `tzdata` lo cubre la base
#: de zonas del sistema y `colorama` solo lo pide la consola de Windows.
_PLATAFORMA = frozenset({"tzdata", "colorama"})


def _pines(lockfile: Path) -> set[str]:
    nombres = set()
    for linea in lockfile.read_text(encoding="utf-8").splitlines():
        m = re.match(r"^([A-Za-z0-9][A-Za-z0-9._-]*)(?:\[[^\]]*\])?==", linea)
        if m:
            nombres.add(_NORMALIZA.sub("-", m.group(1)).lower())
    return nombres


def _permitidas(lockfile: Path) -> set[str]:
    """Los pines del lockfile más sus dependencias obligatorias *instaladas aquí*.

    Lo que este test vigila es el código del repositorio, no los metadatos de
    terceros. Si el entorno que corre la suite tiene otra versión de un paquete
    —un venv local con pandas 2, que exige `pytz`, frente al pandas 3 del
    lock—, vetar sus dependencias haría fallar el import por un motivo que en
    la imagen no existe. Se cierra el conjunto con los `Requires-Dist` sin
    extra de lo instalado; un import directo del repositorio a algo que no está
    en el lock sigue vetado.
    """
    from importlib.metadata import PackageNotFoundError, requires

    from packaging.requirements import Requirement

    permitidas = _pines(lockfile) | _PLATAFORMA
    pendientes = list(permitidas)
    while pendientes:
        nombre = pendientes.pop()
        try:
            dependencias = requires(nombre) or []
        except PackageNotFoundError:
            continue
        for linea in dependencias:
            req = Requirement(linea)
            if req.marker is not None and not req.marker.evaluate({"extra": ""}):
                continue
            dep = _NORMALIZA.sub("-", req.name).lower()
            if dep not in permitidas:
                permitidas.add(dep)
                pendientes.append(dep)
    return permitidas


# ── Entrypoint API ───────────────────────────────────────────────────────────


@pytest.fixture(scope="module")
def sonda_api() -> dict[str, Any]:
    return _sonda(["api.app"], lockfile=ROOT / "requirements-api.txt", perfil="api", caminos=True)


def test_la_api_arranca_solo_con_su_lockfile(sonda_api: dict[str, Any]) -> None:
    """`_sonda` ya falla si el import revienta; aquí se mira qué se quedó fuera.

    Lo vetado solo puede ser un import opcional que degradó (p. ej. `rich` en
    el renderizador de structlog). Uno del pipeline, en cambio, significaría que
    el arranque lo intentó: hoy funciona porque alguien lo protegió con un
    `try`, y mañana es un 500.
    """
    intentados = set(sonda_api["vetados"]) & PAQUETES_DEL_PIPELINE
    assert not intentados, f"api.app intentó importar {sorted(intentados)} al arrancar"
    cargados = set(sonda_api["modulos"]) & PAQUETES_DEL_PIPELINE
    assert not cargados, f"api.app cargó {sorted(cargados)} al arrancar"


def test_el_lockfile_de_la_api_no_trae_el_pipeline() -> None:
    fuera = {"scikit-learn", "scipy", "joblib", "statsmodels", "networkx", "lxml"}
    colados = _pines(ROOT / "requirements-api.txt") & fuera
    assert not colados, f"requirements-api.txt vuelve a instalar {sorted(colados)}"


def test_cobertura_se_sirve_sin_lxml(sonda_api: dict[str, Any]) -> None:
    """`/publico/cobertura` arrastraba lxml vía `scraper.connectors` (500 en la imagen)."""
    assert sonda_api["caminos"]["cobertura_fuentes"] > 0


def test_explain_y_clusters_fallan_por_una_dependencia_del_pipeline(
    sonda_api: dict[str, Any],
) -> None:
    """Sin sklearn, el error es uno que sus rutas traducen a 503, no un 500."""
    assert sonda_api["caminos"]["explain"] in PAQUETES_DEL_PIPELINE
    assert sonda_api["caminos"]["clusters"] in PAQUETES_DEL_PIPELINE


def test_forecast_y_partners_degradan_sin_statsmodels_ni_networkx(
    sonda_api: dict[str, Any],
) -> None:
    """El forecast declara que es lineal; los partners salen sin comunidades."""
    from services.analytics.forecast import MODELO_LINEAL

    assert sonda_api["caminos"]["forecast"] == [MODELO_LINEAL]
    assert sonda_api["caminos"]["partners_comunidades"] == 0


# ── Entrypoint worker ────────────────────────────────────────────────────────


def test_el_worker_arranca_con_el_lockfile_del_pipeline() -> None:
    """La cola y el plano de cron importan solo lo que instala su variante."""
    _sonda(
        ["api.app", "scheduler.worker", "scheduler.cron_plane", "scheduler.jobs"],
        lockfile=ROOT / "requirements-pipeline.txt",
        perfil="worker",
    )


def test_render_construye_el_worker_con_la_variante_del_pipeline() -> None:
    """Sin el build arg, el worker saldría con la imagen de la API y su plano de
    cron (drift, clusters, DLQ de TACRC) fallaría en la primera pasada."""
    import yaml

    servicios = {
        s["name"]: s
        for s in yaml.safe_load((ROOT / "render.yaml").read_text(encoding="utf-8"))["services"]
    }
    variables = {
        v["key"]: v.get("value") for v in servicios["tenderflow-worker"].get("envVars", [])
    }
    assert variables.get("REQUIREMENTS_FILE") == "requirements-pipeline.txt"
    api = {v["key"] for v in servicios["tenderflow-api"].get("envVars", [])}
    assert "REQUIREMENTS_FILE" not in api, "la API usa el valor por defecto del Dockerfile"


# ── Traducción a 503 en las rutas ────────────────────────────────────────────


def test_paquete_del_pipeline_ausente_recorre_la_cadena_de_causas() -> None:
    try:
        try:
            raise ModuleNotFoundError("No module named 'sklearn.base'", name="sklearn.base")
        except ModuleNotFoundError as interno:
            raise RuntimeError("no se pudo cargar el artefacto") from interno
    except RuntimeError as exc:
        assert paquete_del_pipeline_ausente(exc) == "sklearn"


def test_un_modulo_ausente_que_no_es_del_pipeline_sigue_siendo_un_bug() -> None:
    exc = ModuleNotFoundError("No module named 'fastapi'", name="fastapi")
    assert paquete_del_pipeline_ausente(exc) is None
    assert paquete_del_pipeline_ausente(ValueError("otro")) is None


def test_explain_responde_503_sin_sklearn(monkeypatch: pytest.MonkeyPatch) -> None:
    from api.routes.licitaciones import analitica

    async def fake_run_db(fn: Any, *args: Any, **kwargs: Any) -> Any:
        return ("Implantación SAP S/4HANA", "Migración", "sap")

    async def fake_run_ml(fn: Any, *args: Any, **kwargs: Any) -> Any:
        return fn(*args, **kwargs)

    def sin_sklearn() -> Any:
        raise ModuleNotFoundError("No module named 'sklearn'", name="sklearn")

    monkeypatch.setattr(analitica, "run_db", fake_run_db)
    monkeypatch.setattr(analitica, "run_ml", fake_run_ml)
    monkeypatch.setattr(analitica, "_get_classifier", sin_sklearn)

    with pytest.raises(HTTPException) as info:
        asyncio.run(analitica.explain_licitacion("X-1", top_k=5, _ctx={}))
    assert info.value.status_code == 503


def test_explain_sigue_dando_500_ante_otro_error(monkeypatch: pytest.MonkeyPatch) -> None:
    from api.routes.licitaciones import analitica

    async def fake_run_db(fn: Any, *args: Any, **kwargs: Any) -> Any:
        return ("Implantación SAP S/4HANA", "Migración", "sap")

    async def fake_run_ml(fn: Any, *args: Any, **kwargs: Any) -> Any:
        return fn(*args, **kwargs)

    def roto() -> Any:
        raise ValueError("artefacto corrupto")

    monkeypatch.setattr(analitica, "run_db", fake_run_db)
    monkeypatch.setattr(analitica, "run_ml", fake_run_ml)
    monkeypatch.setattr(analitica, "_get_classifier", roto)

    with pytest.raises(HTTPException) as info:
        asyncio.run(analitica.explain_licitacion("X-1", top_k=5, _ctx={}))
    assert info.value.status_code == 500


def test_clusters_responde_503_sin_sklearn(monkeypatch: pytest.MonkeyPatch) -> None:
    from api.routes import analytics

    def sin_sklearn(_filters: Any) -> Any:
        raise ModuleNotFoundError("No module named 'sklearn'", name="sklearn")

    monkeypatch.setattr(analytics, "get_clusters", sin_sklearn)
    handler = analytics.clusters.__wrapped__  # sin la caché de respuesta

    with pytest.raises(HTTPException) as info:
        handler(
            n_clusters=None, auto_k=False, fecha_desde=None, fecha_hasta=None, ccaa=None, _user={}
        )
    assert info.value.status_code == 503
