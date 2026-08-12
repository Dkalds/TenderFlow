"""Ratchet: ``getattr(settings, "X", default)`` sobre un campo que no existe.

``Settings.model_config`` usa ``extra="ignore"``, así que pydantic **descarta en
silencio** cualquier variable de entorno que la clase no declare. Combinado con
``getattr(settings, "X", default)`` el resultado es una palanca de configuración
fantasma: se documenta en el runbook, se exporta en el entorno, y no hace
absolutamente nada porque el ``getattr`` cae siempre al default.

No es hipotético. Ha ocurrido dos veces, encontradas de forma independiente:

* ``API_RATE_LIMIT_MAX_CALLS`` — documentada como palanca de operación,
  inexistente en ``Settings`` (cerrado el 2026-08-02).
* ``FORWARDED_ALLOW_IPS`` — peor, porque el campo gobierna qué proxies pueden
  fijar la IP del cliente. Al no existir, ``api/middleware.py`` caía siempre a
  ``127.0.0.1`` y la defensa no era configurable de ninguna manera; ni el
  ``"*"`` de ``render.yaml`` ni nada llegaba a leerse. Los tests no lo vieron
  porque mockean ``settings`` con un ``Mock``, al que cualquier atributo le
  existe.

Ese segundo caso es la razón de este guard: un mock nunca va a detectar un campo
que falta, así que hace falta comprobarlo contra la clase real.
"""

from __future__ import annotations

import ast
import re
from pathlib import Path

from config.settings import Settings

_RAIZ = Path(__file__).resolve().parent.parent

# Directorios sin código de producción: sus getattr no gobiernan nada desplegado.
_EXCLUIDOS = ("tests", "scripts", ".git", "node_modules", "web", "graphify-out")

# Acepta tanto ``settings`` como el alias ``_settings`` (shared/auth_core.py).
_PATRON = re.compile(r"getattr\(\s*_?settings\s*,\s*[\"']([A-Za-z_][A-Za-z0-9_]*)[\"']")

# Vestigios conocidos, **solo puede encoger** (mismo patrón que el ratchet
# TID251 y que scripts/check_openapi_contract.py). No añadir entradas: si un
# campo nuevo hace falta, se declara en Settings.
#
# Vaciado al migrar db/analytics.py a postgres_scanner: sus dos entradas
# (``DATABASE_PATH`` y ``SQLITE_PATH``) sostenían el resolutor de fichero
# SQLite, que desapareció con el camino que quedó muerto en ADR-021.
_VESTIGIOS_PERMITIDOS: frozenset[str] = frozenset()


def _campos_declarados() -> frozenset[str]:
    """Nombres que ``Settings`` expone de verdad (campos + properties)."""
    return frozenset(Settings.model_fields) | frozenset(
        nombre for nombre in dir(Settings) if not nombre.startswith("__")
    )


def _ficheros_de_produccion() -> list[Path]:
    return [
        ruta
        for ruta in _RAIZ.rglob("*.py")
        if not ruta.relative_to(_RAIZ).parts[0].startswith(_EXCLUIDOS)
    ]


def _referencias() -> dict[str, set[str]]:
    """Mapea cada nombre referenciado por getattr al fichero que lo usa.

    Las rutas se normalizan con ``as_posix()``: en Windows ``str()`` daría
    ``api\\middleware.py`` y las comparaciones de abajo esperan ``api/...``.
    """
    encontrados: dict[str, set[str]] = {}
    for ruta in _ficheros_de_produccion():
        texto = ruta.read_text(encoding="utf-8", errors="ignore")
        for coincidencia in _PATRON.finditer(texto):
            nombre = coincidencia.group(1)
            encontrados.setdefault(nombre, set()).add(ruta.relative_to(_RAIZ).as_posix())
    return encontrados


def test_ningun_getattr_de_settings_apunta_a_un_campo_inexistente() -> None:
    declarados = _campos_declarados()
    huerfanos = {
        nombre: sorted(ficheros)
        for nombre, ficheros in _referencias().items()
        if nombre not in declarados and nombre not in _VESTIGIOS_PERMITIDOS
    }

    assert not huerfanos, (
        "Estos getattr(settings, ...) apuntan a campos que Settings no declara, "
        "así que su variable de entorno se descarta en silencio y el default gana "
        f"siempre: {huerfanos}. Declaralos en config/settings.py."
    )


def test_la_allowlist_de_vestigios_no_crece() -> None:
    """El ratchet solo puede encoger: un vestigio resuelto sale de la lista."""
    declarados = _campos_declarados()
    referenciados = set(_referencias())

    obsoletos = {
        nombre
        for nombre in _VESTIGIOS_PERMITIDOS
        if nombre not in referenciados or nombre in declarados
    }

    assert not obsoletos, (
        f"Estas entradas de _VESTIGIOS_PERMITIDOS ya no hacen falta: {sorted(obsoletos)}. "
        "Borralas de la lista — el ratchet solo puede encoger."
    )


def test_forwarded_allow_ips_sigue_declarado() -> None:
    """Regresión directa del hallazgo crítico.

    ``api/middleware._trusted_client_ip`` lo lee con getattr; si alguien vuelve
    a quitar el campo, la única defensa contra que un cliente falsifique su IP
    deja de ser configurable sin que nada falle.
    """
    assert "FORWARDED_ALLOW_IPS" in Settings.model_fields


def test_settings_ignora_extras_que_es_lo_que_hace_peligroso_el_getattr() -> None:
    """Fija la premisa del guard: si esto cambiara, el riesgo sería otro.

    Con ``extra="ignore"`` una variable no declarada se descarta sin ruido. Si
    algún día pasa a ``forbid``, el arranque fallaría solo y este ratchet
    perdería su motivo — conviene enterarse por un test y no por sorpresa.
    """
    assert Settings.model_config.get("extra") == "ignore"


def test_el_guard_detecta_un_campo_inexistente() -> None:
    """El guard tiene que fallar con el bug presente, o no vale nada."""
    declarados = _campos_declarados()

    assert "CAMPO_QUE_NO_EXISTE_JAMAS" not in declarados

    referencias_simuladas = {"CAMPO_QUE_NO_EXISTE_JAMAS": {"api/inventado.py"}}
    huerfanos = {
        nombre: sorted(ficheros)
        for nombre, ficheros in referencias_simuladas.items()
        if nombre not in declarados and nombre not in _VESTIGIOS_PERMITIDOS
    }

    assert huerfanos, "El guard no detectaría un campo inexistente"


def test_el_escaner_encuentra_los_getattr_reales() -> None:
    """Si el regex dejara de casar, los dos tests de arriba pasarían vacíos.

    Un escáner que no encuentra nada es indistinguible de un repo limpio, así
    que hay que anclar que sigue viendo call sites de verdad.
    """
    referencias = _referencias()

    assert len(referencias) > 20, f"El escáner solo encontró {len(referencias)} referencias"
    assert "FORWARDED_ALLOW_IPS" in referencias
    assert "api/middleware.py" in referencias["FORWARDED_ALLOW_IPS"]


def test_los_ficheros_escaneados_son_python_parseable() -> None:
    """Descarta que el escáner esté leyendo basura y casando por accidente."""
    muestra = [r for r in _ficheros_de_produccion() if r.name == "middleware.py"]

    assert muestra, "No se encontró api/middleware.py en el barrido"
    for ruta in muestra:
        ast.parse(ruta.read_text(encoding="utf-8"))
