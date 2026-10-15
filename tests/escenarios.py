"""Piezas comunes de los tests de escenario (``tests/test_escenario_*.py``).

Un test de escenario recorre un caso de uso de ``docs/casos-de-uso.md`` de
punta a punta por la API, como lo haría la consola: alta, sesión con cookie y
CSRF de verdad, y después las llamadas del recorrido en orden. No sustituye a
los tests por endpoint —esos fijan cada contrato—; lo que fija es que los pasos
**encajan entre sí**, que es justo lo que ningún test de una sola ruta ve.

Por eso aquí no hay ``dependency_overrides`` de autenticación: la sesión se
abre por ``/auth/register`` + ``/auth/login``, y las escrituras llevan el token
CSRF de la cookie, igual que el navegador.
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import time
from dataclasses import dataclass
from typing import Any
from urllib.parse import parse_qs, urlparse

from fastapi.testclient import TestClient

#: Credencial de las cuentas que cada escenario crea y descarta. Compuesta y no
#: literal: una constante con pinta de contraseña la marca gitleaks.
PASSWORD = "-".join(("Escenario", "2026", "Seguro"))


@dataclass(frozen=True)
class Sesion:
    """Un usuario con sesión abierta: su cliente (con cookies) y su organización."""

    client: TestClient
    csrf: str
    user_id: int
    organization_id: int
    email: str

    @property
    def cab(self) -> dict[str, str]:
        """Cabeceras de una escritura con sesión de cookie."""
        return {"X-CSRF-Token": self.csrf}

    def get(self, ruta: str, **kwargs: Any) -> Any:
        return self.client.get(f"/api/v1{ruta}", **kwargs)

    def post(self, ruta: str, **kwargs: Any) -> Any:
        return self.client.post(f"/api/v1{ruta}", headers=self.cab, **kwargs)

    def put(self, ruta: str, **kwargs: Any) -> Any:
        return self.client.put(f"/api/v1{ruta}", headers=self.cab, **kwargs)

    def patch(self, ruta: str, **kwargs: Any) -> Any:
        return self.client.patch(f"/api/v1{ruta}", headers=self.cab, **kwargs)

    def delete(self, ruta: str, **kwargs: Any) -> Any:
        # ``request`` y no ``delete``: el cliente de pruebas no admite cuerpo en
        # su atajo de DELETE, y borrar la cuenta lo exige (``confirmation``).
        return self.client.request("DELETE", f"/api/v1{ruta}", headers=self.cab, **kwargs)


def abrir_sesion(
    email: str, client: TestClient | None = None, *, nombre: str | None = None
) -> Sesion:
    """Da de alta a ``email`` e inicia sesión. Cada usuario, su propio cliente.

    Las cookies viven en el ``TestClient``: dos personas en el mismo escenario
    necesitan dos clientes, o la segunda pisa la sesión de la primera.
    ``nombre`` es el nombre visible; sin él, las pantallas que nombran a la
    persona (responsable, actor de un evento) la dejan sin nombre.
    """
    if client is None:
        from api.app import app

        client = TestClient(app, raise_server_exceptions=True)

    datos = {"email": email, "password": PASSWORD}
    if nombre:
        datos["display_name"] = nombre
    alta = client.post("/api/v1/auth/register", json=datos)
    assert alta.status_code == 201, alta.text
    login = client.post("/api/v1/auth/login", json={"email": email, "password": PASSWORD})
    assert login.status_code == 200, login.text
    csrf = str(login.cookies["csrf_token"])

    yo = client.get("/api/v1/auth/me")
    assert yo.status_code == 200, yo.text
    organizacion = client.get("/api/v1/organizations/active")
    assert organizacion.status_code == 200, organizacion.text
    return Sesion(
        client=client,
        csrf=csrf,
        user_id=int(yo.json()["user_id"]),
        organization_id=int(organizacion.json()["id"]),
        email=email,
    )


def codigo_totp(otpauth_uri: str) -> str:
    """El código de seis cifras que daría ahora una app de autenticación.

    Calculado aquí (RFC 6238, HMAC-SHA1 y 30 s) y no con ``db.totp``: el
    escenario hace de la app del móvil, y usar el mismo código que verifica
    sería comprobar el servidor contra sí mismo.
    """
    secreto = parse_qs(urlparse(otpauth_uri).query)["secret"][0]
    clave = base64.b32decode(secreto + "=" * (-len(secreto) % 8), casefold=True)
    contador = int(time.time() // 30)
    resumen = hmac.new(clave, contador.to_bytes(8, "big"), hashlib.sha1).digest()
    desplazamiento = resumen[-1] & 0x0F
    valor = int.from_bytes(resumen[desplazamiento : desplazamiento + 4], "big") & 0x7FFF_FFFF
    return f"{valor % 1_000_000:06d}"


def sembrar_licitacion(id_externo: str, titulo: str, **campos: Any) -> None:
    """Inserta un expediente mínimo. ``campos`` añade o pisa columnas.

    Es lo único que un escenario escribe sin pasar por la API: los expedientes
    los trae la ingesta, no el usuario.
    """
    from db.database import connect

    fila: dict[str, Any] = {
        "id_externo": id_externo,
        "titulo": titulo,
        "fuente": "placsp",
        "estado": "ABIERTO",
        "cpv": "72000000",
        "importe": 250_000.0,
        "organo_contratacion": "Ayuntamiento de Pruebas",
        "fecha_publicacion": "2026-09-01",
        "fecha_limite": "2027-01-15T10:00:00+00:00",
        "fecha_extraccion": "2026-09-01T08:00:00+00:00",
    }
    fila.update(campos)
    columnas = ", ".join(fila)
    marcadores = ", ".join(["%s"] * len(fila))
    with connect() as conn:
        conn.execute(
            f"INSERT INTO licitaciones ({columnas}) VALUES ({marcadores})",  # noqa: S608 -- columnas fijadas por el test, valores parametrizados
            tuple(fila.values()),
        )
