"""Tests de ``POST /api/v1/publico/solicitudes-acceso``.

Es el único endpoint público de escritura de la API, así que lo que se fija
aquí no es tanto el camino feliz como los que impiden que se convierta en un
problema: nunca un 5xx (``scripts/fuzz_api_contract.py`` mantiene ``KNOWN_5XX``
a cero), nada guardado sin consentimiento explícito, y el campo trampa
respondiendo como si todo hubiera ido bien para no enseñarle al bot dónde está.
"""

from __future__ import annotations

import pytest

RUTA = "/api/v1/publico/solicitudes-acceso"
FORM = {"Content-Type": "application/x-www-form-urlencoded"}


def _contar() -> int:
    from db.solicitudes_acceso import contar_pendientes

    return contar_pendientes()


def _con_origenes(monkeypatch, origenes: set[str]) -> None:
    """Fija los orígenes aceptados sin depender de la configuración del entorno."""
    import api.routes.publico_solicitudes as modulo

    monkeypatch.setattr(modulo, "_origenes_validos", lambda: origenes)


def test_envio_valido_redirige_y_persiste(client):
    antes = _contar()

    r = client.post(
        RUTA,
        content="email=ana%40empresa.example&empresa=Empresa&consentimiento=si&origen=landing",
        headers=FORM,
        follow_redirects=False,
    )

    assert r.status_code == 303
    assert r.headers["location"] == "/solicitud-recibida"
    assert _contar() == antes + 1


def test_sin_consentimiento_no_guarda(client):
    """Sin la casilla marcada no hay base para guardar un dato de contacto."""
    antes = _contar()

    r = client.post(RUTA, content="email=b%40e.example", headers=FORM, follow_redirects=False)

    assert r.status_code == 303
    assert "estado=consentimiento" in r.headers["location"]
    assert _contar() == antes


@pytest.mark.parametrize("email", ["", "noesunemail", "sin@arroba", "a@b", "@dominio.example"])
def test_email_invalido_no_guarda(client, email):
    antes = _contar()

    r = client.post(
        RUTA,
        content=f"email={email}&consentimiento=si",
        headers=FORM,
        follow_redirects=False,
    )

    assert r.status_code == 303
    assert "estado=email" in r.headers["location"]
    assert _contar() == antes


def test_el_motivo_del_rechazo_viaja_pero_los_datos_no(client):
    """El estado dice qué falló; el email no vuelve en la URL.

    Diferenciar el motivo es lo que permite a la página de gracias decir
    "revisa esto" en vez de "vuelve a intentarlo". Devolver además lo escrito
    ahorraría reescribir el formulario, pero pondría un dato personal en una
    query string —logs de acceso, `Referer`, historial— y eso no se hace.
    """
    r = client.post(
        RUTA,
        content="email=ana%40empresa.example",  # válido, pero sin consentimiento
        headers=FORM,
        follow_redirects=False,
    )

    destino = r.headers["location"]

    assert "estado=consentimiento" in destino
    assert "ana" not in destino
    assert "empresa.example" not in destino


def test_reenviar_no_duplica_la_cola(client):
    """Un doble clic o un reintento no pueden crear tres filas iguales.

    Es el caso probable, no el raro: tras agotar el rate limit —cinco por
    minuto— lo que hace cualquiera es volver a darle al botón. Quien paga los
    duplicados es la persona que revisa la cola a mano.
    """
    antes = _contar()
    cuerpo = "email=repe%40empresa.example&empresa=Uno&consentimiento=si"

    primera = client.post(RUTA, content=cuerpo, headers=FORM, follow_redirects=False)
    segunda = client.post(RUTA, content=cuerpo, headers=FORM, follow_redirects=False)

    assert primera.status_code == 303
    assert segunda.status_code == 303
    assert segunda.headers["location"] == "/solicitud-recibida"
    assert _contar() == antes + 1


def test_reenviar_actualiza_lo_que_llega_mejor_contado(client):
    """La segunda vez es la misma petición mejor explicada, no otra distinta."""
    client.post(
        RUTA,
        content="email=mejora%40empresa.example&consentimiento=si",
        headers=FORM,
        follow_redirects=False,
    )
    client.post(
        RUTA,
        content="email=mejora%40empresa.example&empresa=Acme&mensaje=Con+detalle&consentimiento=si",
        headers=FORM,
        follow_redirects=False,
    )

    from db.solicitudes_acceso import listar_solicitudes

    filas = [f for f in listar_solicitudes(limit=100) if f["email"] == "mejora@empresa.example"]

    assert len(filas) == 1
    assert filas[0]["empresa"] == "Acme"
    assert filas[0]["mensaje"] == "Con detalle"


def test_la_unicidad_no_bloquea_pedir_acceso_otra_vez(client):
    """El índice es parcial: sólo hay una pendiente por email, no una histórica.

    Si se atendió o se descartó, volver a pedir acceso es legítimo y tiene que
    poder entrar; un UNIQUE a secas convertiría el histórico en un muro.
    """
    from db.solicitudes_acceso import actualizar_estado, listar_solicitudes

    client.post(
        RUTA,
        content="email=vuelve%40empresa.example&consentimiento=si",
        headers=FORM,
        follow_redirects=False,
    )
    [primera] = [f for f in listar_solicitudes(limit=100) if f["email"] == "vuelve@empresa.example"]
    actualizar_estado(primera["id"], "descartada")

    antes = _contar()
    client.post(
        RUTA,
        content="email=vuelve%40empresa.example&consentimiento=si",
        headers=FORM,
        follow_redirects=False,
    )

    assert _contar() == antes + 1


def test_una_solicitud_nueva_avisa_al_operador(client, monkeypatch):
    """El embudo no puede terminar en una fila que nadie mira.

    El aviso sale por el sistema de webhooks que ya existe, y **sin el email**:
    un webhook sale del sistema y el aviso no necesita el dato personal para
    cumplir su función. La dirección se lee en el panel, que exige ser admin.
    """
    import api.routes.publico_solicitudes as modulo

    emitidos: list[tuple[str, dict[str, object]]] = []
    monkeypatch.setattr(
        modulo, "trigger_event", lambda evento, payload: emitidos.append((evento, payload)) or 1
    )

    client.post(
        RUTA,
        content="email=avisa%40empresa.example&empresa=Acme&mensaje=secreto&consentimiento=si",
        headers=FORM,
        follow_redirects=False,
    )

    assert len(emitidos) == 1
    evento, payload = emitidos[0]
    assert evento == "solicitud_acceso.creada"
    assert payload["empresa"] == "Acme"
    assert "avisa@empresa.example" not in str(payload)
    assert "secreto" not in str(payload)


def test_un_webhook_roto_no_rompe_el_formulario(client, monkeypatch):
    """El aviso es un efecto lateral: no puede tumbar un formulario público."""
    import api.routes.publico_solicitudes as modulo

    def _revienta(*_a, **_k):
        raise RuntimeError("endpoint del operador caído")

    monkeypatch.setattr(modulo, "trigger_event", _revienta)
    antes = _contar()

    respuesta = client.post(
        RUTA,
        content="email=roto%40empresa.example&consentimiento=si",
        headers=FORM,
        follow_redirects=False,
    )

    assert respuesta.status_code == 303
    assert respuesta.headers["location"] == "/solicitud-recibida"
    assert _contar() == antes + 1


def test_honeypot_finge_exito_pero_no_guarda(client):
    """Un bot que rellena el campo trampa recibe el mismo 303 de éxito.

    Devolver un error le diría exactamente qué campo evitar la próxima vez.
    """
    antes = _contar()

    r = client.post(
        RUTA,
        content="email=bot%40spam.example&consentimiento=si&website=http%3A%2F%2Fspam",
        headers=FORM,
        follow_redirects=False,
    )

    assert r.status_code == 303
    assert r.headers["location"] == "/solicitud-recibida"
    assert _contar() == antes


def test_json_no_es_un_formulario(client):
    """El endpoint sirve a un `<form>` HTML; nada más entra."""
    antes = _contar()

    r = client.post(RUTA, json={"email": "x@y.example"}, follow_redirects=False)

    assert r.status_code == 303
    assert "estado=error" in r.headers["location"]
    assert _contar() == antes


def test_cuerpo_basura_no_da_5xx(client):
    """Entrada de internet, salida limpia: el fuzzer del contrato exige 0 5xx."""
    r = client.post(RUTA, content=b"\xff\xfe%%%=&&&", headers=FORM, follow_redirects=False)

    assert r.status_code < 500


def test_campos_largos_se_recortan_sin_romper(client):
    antes = _contar()

    r = client.post(
        RUTA,
        content="email=larga%40e.example&consentimiento=si&empresa=" + "x" * 5000,
        headers=FORM,
        follow_redirects=False,
    )

    assert r.status_code == 303
    assert _contar() == antes + 1

    from db.solicitudes_acceso import listar_solicitudes

    guardada = listar_solicitudes(limit=1)[0]
    assert guardada["empresa"] is not None
    assert len(guardada["empresa"]) <= 200


def test_no_requiere_autenticacion(client):
    """La superficie pública no exige sesión: si la exigiera, el CTA moriría."""
    r = client.post(
        RUTA,
        content="email=anon%40e.example&consentimiento=si",
        headers=FORM,
        follow_redirects=False,
    )

    assert r.status_code != 401
    assert r.status_code != 403


def test_un_origen_ajeno_no_guarda(client, monkeypatch):
    """Un formulario alojado en otro dominio no puede sembrar la cola.

    No es una defensa contra un atacante decidido —puede omitir la cabecera—
    pero corta el envío cruzado casual, que es lo que la haría inútil.
    """
    _con_origenes(monkeypatch, {"https://tenderflow.example"})
    antes = _contar()

    r = client.post(
        RUTA,
        content="email=evil%40e.example&consentimiento=si",
        headers={**FORM, "Origin": "https://evil.example"},
        follow_redirects=False,
    )

    assert r.status_code == 303
    assert "estado=error" in r.headers["location"]
    assert _contar() == antes


def test_el_origen_propio_sigue_pasando(client, monkeypatch):
    _con_origenes(monkeypatch, {"https://tenderflow.example"})
    antes = _contar()

    r = client.post(
        RUTA,
        content="email=buena%40e.example&consentimiento=si",
        headers={**FORM, "Origin": "https://tenderflow.example"},
        follow_redirects=False,
    )

    assert r.status_code == 303
    assert r.headers["location"] == "/solicitud-recibida"
    assert _contar() == antes + 1


def test_un_referer_ilegible_no_bloquea(client, monkeypatch):
    """Una cabecera malformada no es prueba de origen ajeno, así que no corta."""
    _con_origenes(monkeypatch, {"https://tenderflow.example"})
    antes = _contar()

    r = client.post(
        RUTA,
        content="email=rara%40e.example&consentimiento=si",
        headers={**FORM, "Referer": "no-es-una-url"},
        follow_redirects=False,
    )

    assert r.status_code == 303
    assert _contar() == antes + 1


def test_un_fallo_de_base_de_datos_no_asoma_como_5xx(client, monkeypatch):
    """La API caída no puede devolver un error de servidor a una página pública."""
    import api.routes.publico_solicitudes as modulo

    def _revienta(**_kwargs):
        raise RuntimeError("base de datos caída")

    monkeypatch.setattr(modulo, "crear_solicitud", _revienta)

    r = client.post(
        RUTA,
        content="email=caida%40e.example&consentimiento=si",
        headers=FORM,
        follow_redirects=False,
    )

    assert r.status_code == 303
    assert "estado=error" in r.headers["location"]


def test_sin_origenes_configurados_no_se_bloquea_a_nadie(client, monkeypatch):
    """Un despliegue sin CORS_ALLOWED_ORIGINS no puede quedarse sin formulario.

    Sin lista no se puede afirmar que un origen sea ajeno; rechazar por defecto
    convertiría un olvido de configuración en un embudo roto. El rate limit y
    la trampa siguen en pie.
    """
    _con_origenes(monkeypatch, set())
    antes = _contar()

    r = client.post(
        RUTA,
        content="email=sinlista%40e.example&consentimiento=si",
        headers={**FORM, "Origin": "https://cualquiera.example"},
        follow_redirects=False,
    )

    assert r.status_code == 303
    assert _contar() == antes + 1


def test_los_origenes_salen_de_la_configuracion(monkeypatch):
    """La lista se lee del entorno, sin barras finales, y en dev añade localhost."""
    import api.routes.publico_solicitudes as modulo

    monkeypatch.setattr(
        modulo.settings, "CORS_ALLOWED_ORIGINS", "https://uno.example/, https://dos.example"
    )
    monkeypatch.setattr(modulo.settings, "ENV", "prod")

    assert modulo._origenes_validos() == {"https://uno.example", "https://dos.example"}

    monkeypatch.setattr(modulo.settings, "ENV", "dev")

    assert "http://localhost:3000" in modulo._origenes_validos()
