"""La credencial de administración de la base no llega al proceso que sirve HTTP.

`DATABASE_ADMIN_URL` es el DSN del rol DUEÑO del schema: el único con DDL y el
único que bypassa la RLS de `v52_rls_lockdown`. Existe (O0.4) para que
`alembic upgrade` deje de correr con la misma credencial que la app.

Un «solo para migraciones» escrito en un comentario es una convención que nadie
comprueba: basta con que alguien añada el secret al servicio de Render, o llame
a la función desde una ruta, para que el cutover entero quede anulado sin que
falle nada. Este fichero fija las tres propiedades que lo impiden por
construcción:

1. Con ``APP_PROFILE=api`` la función no devuelve ``None`` —eso sería un fallo
   recuperable, y el llamante seguiría adelante—, sino que **levanta**.
2. Lo mismo con cualquier perfil que no sea el que migra: sin ``APP_PROFILE``
   declarado, con el ``worker`` que introduce S5 o con un valor mal escrito. La
   función decide con una allowlist (`scraper`), no con una lista de
   prohibidos, que es lo que hace que un perfil nuevo falle cerrado en vez de
   heredar la credencial por omisión.
3. ``DATABASE_ADMIN_URL`` **no es un atributo de ``Settings``**. Es lo que hace
   que no exista ni la posibilidad de leerla por descuido desde la API.

No necesita base de datos: solo lee el entorno del proceso.
"""

from __future__ import annotations

import os
from unittest.mock import patch

import pytest

from config.settings import (
    _ADMIN_DB_URL_ENV,
    _PERFIL_POR_DEFECTO,
    _PERFILES_CON_CREDENCIAL_ADMIN,
    Settings,
    database_admin_url,
)

# DSN de mentira, con la forma justa para distinguirlo de una cadena vacía.
_DSN_FALSO = "postgresql://duenyo:secreta@localhost:5432/postgres"  # pragma: allowlist secret


def _entorno(**overrides: str) -> dict[str, str]:
    """Entorno limpio de las dos variables que gobiernan la función.

    ``patch.dict(..., clear=False)`` conserva el resto del entorno del runner;
    lo que hace falta es que ni ``APP_PROFILE`` ni ``DATABASE_ADMIN_URL``
    arrastren un valor de fuera del test.
    """
    base = {k: v for k, v in os.environ.items() if k not in {"APP_PROFILE", _ADMIN_DB_URL_ENV}}
    base.update(overrides)
    return base


# ---------------------------------------------------------------------------
# 1. La API no puede leerla
# ---------------------------------------------------------------------------


def test_perfil_api_levanta_aunque_la_credencial_exista() -> None:
    """El caso que importa: el secret está puesto y aun así no se entrega."""
    entorno = _entorno(APP_PROFILE="api", DATABASE_ADMIN_URL=_DSN_FALSO)

    with patch.dict(os.environ, entorno, clear=True), pytest.raises(RuntimeError) as exc:
        database_admin_url()

    # El mensaje es parte del contrato: quien se topa con esto tiene que saber
    # en el acto qué credencial usar en su lugar.
    assert _ADMIN_DB_URL_ENV in str(exc.value)
    assert "DATABASE_URL" in str(exc.value)


def test_perfil_api_levanta_tambien_sin_credencial_configurada() -> None:
    """No es «no hay valor»: es «no te lo puedo dar». Son errores distintos.

    Si sin secret devolviera ``None``, el llamante de la API pasaría de largo y
    el fallo aparecería el día en que alguien configure la variable.
    """
    with (
        patch.dict(os.environ, _entorno(APP_PROFILE="api"), clear=True),
        pytest.raises(RuntimeError),
    ):
        database_admin_url()


@pytest.mark.parametrize("perfil", ["API", "  api  ", "Api"])
def test_el_perfil_se_normaliza_antes_de_decidir(perfil: str) -> None:
    """Un espacio o una mayúscula en el entorno no abren la puerta."""
    entorno = _entorno(APP_PROFILE=perfil, DATABASE_ADMIN_URL=_DSN_FALSO)

    with patch.dict(os.environ, entorno, clear=True), pytest.raises(RuntimeError):
        database_admin_url()


# ---------------------------------------------------------------------------
# 2. Fail-closed: solo el perfil que migra la recibe
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("perfil", ["worker", "apiv2", "cron", "scrapper"])
def test_cualquier_perfil_fuera_de_la_allowlist_queda_fuera(perfil: str) -> None:
    """La diferencia entre allowlist y lista de prohibidos, fijada como test.

    Con una lista de prohibidos (`{"api"}`), estos cuatro casos —el `worker` que
    introduce S5, dos erratas y un perfil inventado— habrían recibido el DSN con
    DDL sin que fallara nada. Un proceso que no es el que migra no tiene por qué
    poder alterar el schema, y menos por omisión.
    """
    entorno = _entorno(APP_PROFILE=perfil, DATABASE_ADMIN_URL=_DSN_FALSO)

    with patch.dict(os.environ, entorno, clear=True), pytest.raises(RuntimeError):
        database_admin_url()


def test_sin_perfil_declarado_se_comporta_como_la_api() -> None:
    """Un proceso que no declara perfil no recibe la credencial."""
    with (
        patch.dict(os.environ, _entorno(DATABASE_ADMIN_URL=_DSN_FALSO), clear=True),
        pytest.raises(RuntimeError),
    ):
        database_admin_url()


def test_perfil_vacio_tambien_es_fail_closed() -> None:
    """``APP_PROFILE=`` (definida y vacía) no es «cualquier perfil»."""
    entorno = _entorno(APP_PROFILE="", DATABASE_ADMIN_URL=_DSN_FALSO)

    with patch.dict(os.environ, entorno, clear=True), pytest.raises(RuntimeError):
        database_admin_url()


def test_el_default_de_la_funcion_es_el_mismo_que_el_de_settings() -> None:
    """Los dos defaults tienen que moverse juntos.

    ``database_admin_url`` lee ``APP_PROFILE`` del entorno con su propio default
    porque no puede depender del singleton ``Settings`` (un test o un job fija la
    variable sin reconstruirlo). El default no gobierna ya el fail-closed —lo
    hace la allowlist—, pero sí el perfil que nombra el mensaje de error: si los
    dos se separaran, el error diría que el proceso es algo que no es.
    """
    assert Settings.model_fields["APP_PROFILE"].default == _PERFIL_POR_DEFECTO


# ---------------------------------------------------------------------------
# 3. El perfil que sí la necesita la recibe
# ---------------------------------------------------------------------------


def test_el_perfil_de_migracion_recibe_la_credencial() -> None:
    """`migrate.yml` corre con ``APP_PROFILE=scraper``: si no, no habría cutover.

    Es el único de la allowlist, así que este test es también la garantía de que
    el endurecimiento de arriba no dejó la función inservible para su único uso.
    """
    entorno = _entorno(APP_PROFILE="scraper", DATABASE_ADMIN_URL=_DSN_FALSO)

    with patch.dict(os.environ, entorno, clear=True):
        assert database_admin_url() == _DSN_FALSO

    assert sorted(_PERFILES_CON_CREDENCIAL_ADMIN) == ["scraper"]


def test_sin_secret_configurado_devuelve_none_y_no_cadena_vacia() -> None:
    """El cutover pendiente se distingue con ``is None``, no con un ``if`` sobre ''.

    ``migrate.yml`` decide con esta ausencia si avisa del fallback; una cadena
    vacía sería un valor que alguien podría pasar a psycopg por error.
    """
    with patch.dict(os.environ, _entorno(APP_PROFILE="scraper"), clear=True):
        assert database_admin_url() is None

    entorno = _entorno(APP_PROFILE="scraper", DATABASE_ADMIN_URL="   ")
    with patch.dict(os.environ, entorno, clear=True):
        assert database_admin_url() is None


# ---------------------------------------------------------------------------
# 4. La variable no existe como campo de Settings
# ---------------------------------------------------------------------------


def test_database_admin_url_no_es_campo_de_settings() -> None:
    """La barrera estructural: no hay atributo que leer desde la API.

    Si algún día se declarara como campo, ``settings.DATABASE_ADMIN_URL``
    funcionaría desde cualquier ruta y las tres comprobaciones de arriba se
    volverían decorativas — la función dejaría de ser la única vía.
    """
    assert _ADMIN_DB_URL_ENV not in Settings.model_fields
    assert not hasattr(Settings, _ADMIN_DB_URL_ENV)


def test_una_instancia_de_settings_no_absorbe_la_variable_del_entorno() -> None:
    """``extra="ignore"`` la descarta al construir, con la variable presente.

    Es la mitad que el chequeo de ``model_fields`` no cubre: pydantic podría
    guardarla como extra y quedar accesible en el objeto.
    """
    entorno = _entorno(APP_PROFILE="scraper", DATABASE_ADMIN_URL=_DSN_FALSO, ENV="dev")

    with patch.dict(os.environ, entorno, clear=True):
        settings = Settings()

    assert not hasattr(settings, _ADMIN_DB_URL_ENV)
    assert _ADMIN_DB_URL_ENV not in settings.model_dump()
