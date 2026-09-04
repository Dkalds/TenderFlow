"""Aislamiento entre usuarios en la superficie de exports (issue #50).

**Reescrito el 2026-09-03.** La versión anterior sembraba trabajos en
``api.routes.exports._store`` —un ``dict`` de proceso— y comprobaba que un
usuario no pudiera leer el de otro. Ese store y los tres endpoints asíncronos
que lo usaban se retiraron al aplicar
``docs/rfc/2026-09-03-rfc-retirada-exports-asincronos.md``: la premisa que los
hacía aceptables («una instancia única que no se reinicia») no se sostiene en
el despliegue real, así que ``POST`` en un worker y ``GET`` en otro daba un 404
inexplicable.

La vulnerabilidad de #50 no se ha vuelto a arreglar: **desapareció con la
superficie**. Sin estado compartido entre peticiones no hay identificador ajeno
que adivinar. Pero el invariante que #50 defendía —nadie se descarga la
exportación de otro— sigue vivo, así que estos tests lo fijan sobre el diseño
de hoy en vez de desaparecer con el store.

Auto-marking: nombre ``test_unit_*`` → marker ``unit`` (conftest.py).
"""

from __future__ import annotations

import inspect

import api.routes.exports as exports_mod

# Nombres de los endpoints asíncronos retirados. Si reaparecen sin backend
# compartido, vuelve la superficie del issue #50.
_ENDPOINTS_RETIRADOS = ("create_export", "get_export", "delete_export", "download_export_job")

# Parámetros que convertirían la descarga en «dame el resultado con este id»,
# que es exactamente la forma que tenía el bug.
_PARAMS_PROHIBIDOS = frozenset({"job_id", "export_id", "owner", "user_id"})


def _estado_mutable_de_modulo() -> dict[str, object]:
    """Estructuras mutables de nivel de módulo que sobreviven entre peticiones.

    Las constantes en MAYÚSCULAS se excluyen: son configuración declarada, no
    estado acumulado. Lo que se persigue aquí es lo segundo.
    """
    return {
        nombre: valor
        for nombre, valor in vars(exports_mod).items()
        if isinstance(valor, (dict, list, set))
        and not nombre.startswith("__")
        and not nombre.isupper()
    }


def test_no_hay_almacen_de_trabajos_compartido() -> None:
    """El módulo no vuelve a acumular estado entre peticiones.

    Es la forma estructural de #50: el fallo no era la comprobación de dueño
    que faltaba, era que existiera un identificador global adivinable
    apuntando al resultado de otro usuario. Un contenedor mutable de nivel de
    módulo que sobrevive a la petición es la firma de ese patrón, y en un
    despliegue multi-instancia además no se comparte.
    """
    estado = _estado_mutable_de_modulo()
    assert not estado, (
        f"api/routes/exports.py acumula estado entre peticiones: {sorted(estado)}. "
        "Si hace falta estado compartido va a Redis con clave por usuario, no a un contenedor "
        "de módulo — ver el RFC de retirada de exports asíncronos."
    )


def test_los_endpoints_asincronos_siguen_retirados() -> None:
    """La máquina 202+poll no vuelve por la puerta de atrás.

    Se retiró por un motivo que no ha cambiado: el store vivía en un proceso y
    el despliegue tiene varios. Si vuelve, que vuelva con backend compartido y
    con este fichero reescrito a conciencia, no por descuido.
    """
    presentes = [nombre for nombre in _ENDPOINTS_RETIRADOS if hasattr(exports_mod, nombre)]
    assert not presentes, (
        f"han reaparecido endpoints asíncronos de export ({presentes}) sin backend compartido."
    )


def test_la_descarga_sincrona_no_acepta_identificador_ajeno() -> None:
    """``download_export`` se parametriza por filtros, nunca por id de trabajo.

    Mientras la exportación se genere desde los filtros de la propia petición
    no hay nada de otro usuario que pedir.
    """
    firma = inspect.signature(exports_mod.download_export)
    presentes = _PARAMS_PROHIBIDOS & set(firma.parameters)
    assert not presentes, (
        f"download_export acepta {sorted(presentes)}: la descarga vuelve a poder referirse al "
        "trabajo de otro usuario."
    )


def test_la_descarga_sincrona_exige_autenticacion() -> None:
    """Nadie descarga sin identificarse.

    Se comprueba sobre la firma real del handler: alguna de sus dependencias
    tiene que ser de autenticación.
    """
    firma = inspect.signature(exports_mod.download_export)
    defaults = " ".join(
        repr(p.default)
        for p in firma.parameters.values()
        if p.default is not inspect.Parameter.empty
    )
    assert "require_" in defaults, (
        "download_export ya no exige autenticación: cualquiera se lleva el corpus filtrado."
    )


def test_la_firma_del_calendario_es_por_usuario_y_no_transferible() -> None:
    """El enlace firmado de un usuario no vale para el calendario de otro.

    Es el equivalente vigente de #50: la URL de capacidad del calendario es la
    única entrada a este módulo sin sesión, así que su firma tiene que estar
    ligada al usuario y no ser transferible.
    """
    token_a = exports_mod._firma_calendario(1)
    token_b = exports_mod._firma_calendario(2)

    assert token_a != token_b, "dos usuarios distintos obtienen la misma firma"
    assert exports_mod._verificar_firma_calendario(1, token_a)
    assert exports_mod._verificar_firma_calendario(2, token_b)

    assert not exports_mod._verificar_firma_calendario(2, token_a), (
        "la firma del usuario 1 abre el calendario del usuario 2 (IDOR)"
    )
    assert not exports_mod._verificar_firma_calendario(1, token_b)
    assert not exports_mod._verificar_firma_calendario(1, "invalido")
    assert not exports_mod._verificar_firma_calendario(1, "")
