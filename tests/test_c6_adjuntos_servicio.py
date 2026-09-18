"""C6.3 — los caminos de `services/pursuit_attachments.py` que tocan el almacén.

`tests/test_c6_captura.py::TestAdjuntosPropios` fija las reglas puras —lista
blanca, topes, saneado del nombre, firma y caducidad— leyendo el código. Aquí se
**ejecutan** las cuatro funciones que orquestan repositorio y almacén, con los
dos simulados, porque lo que deciden es un orden y qué hacen cuando algo falla:

- el binario se escribe **antes** que la fila, y si la fila no se puede crear
  —el pursuit no era de esa organización— el objeto recién escrito se borra;
- al borrar **no** hay orden que fijar desde v131: la fila se marca y el
  binario se conserva, porque borrarlo haría irreversible el borrado lógico;
- sin bucket la subida se rechaza en vez de prometer una descarga imposible;
- una fila cuyo binario ya no está en el almacén no devuelve bytes vacíos.

Ninguno necesita Postgres: son decisiones del servicio, no consultas.
"""

from __future__ import annotations

from contextlib import contextmanager
from typing import Any
from unittest.mock import patch

import pytest


class _AlmacenFalso:
    """Almacén en memoria con la interfaz de `shared/object_store.py`."""

    backend = "fake"

    def __init__(self, *, enabled: bool = True) -> None:
        self._enabled = enabled
        self.objetos: dict[str, bytes] = {}
        self.borrados: list[str] = []

    @property
    def enabled(self) -> bool:
        return self._enabled

    def put(self, key: str, data: bytes, *, content_type: str | None = None) -> None:
        self.objetos[key] = data

    def get(self, key: str) -> bytes | None:
        return self.objetos.get(key)

    def delete(self, key: str) -> bool:
        self.borrados.append(key)
        return self.objetos.pop(key, None) is not None

    def stats(self, *, prefix: str = "") -> Any:  # pragma: no cover - no se usa
        raise NotImplementedError


class _RepoFalso:
    """Lo justo de `PursuitAttachmentsRepository` que usa el servicio."""

    def __init__(self, *, crea: bool = True, ocupado: int = 0) -> None:
        self.crea = crea
        self.ocupado = ocupado
        self.filas: dict[int, dict[str, Any]] = {}
        self.creadas: list[dict[str, Any]] = []

    def ocupacion(self, organization_id: int) -> dict[str, int]:
        return {"n": len(self.filas), "bytes": self.ocupado}

    def create(self, **kwargs: Any) -> dict[str, Any] | None:
        self.creadas.append(kwargs)
        if not self.crea:
            return None
        fila = {"id": 1, **kwargs}
        self.filas[1] = fila
        return fila

    def get(self, attachment_id: int, *, organization_id: int) -> dict[str, Any] | None:
        fila = self.filas.get(attachment_id)
        return None if fila is None or fila.get("deleted_at") else fila

    def delete(self, attachment_id: int, *, organization_id: int) -> str | None:
        """Borrado **lógico** desde v131: marca, no saca la fila del diccionario.

        El doble replica lo que hace el repositorio de verdad, o el test diría
        que el objeto quedó huérfano cuando en realidad su fila sigue ahí
        apuntándolo — que es la diferencia entera entre las dos versiones.
        """
        fila = self.filas.get(attachment_id)
        if fila is None or fila.get("deleted_at") is not None:
            return None
        fila["deleted_at"] = "2026-09-15T00:00:00+00:00"
        return str(fila["blob_key"])

    def keys_de_organizacion(self, organization_id: int) -> list[str]:
        # Incluye las borradas a propósito: su objeto sigue en el almacén y la
        # purga de la organización tiene que llevárselo igual.
        return [str(f["blob_key"]) for f in self.filas.values()]


PDF = b"%PDF-1.7 contenido de prueba"


@contextmanager
def _alcance_falso(user_id: Any, organization_id: Any = None, *, write: bool = False):
    """Doble de ``alcance_resuelto``: la organización 7, sin base de datos.

    Context manager y no función porque el real lo es: acota el bloque con el
    ámbito de tenencia y lo suelta al salir (ADR-034). Un doble que devolviera
    la tupla a secas haría pasar el test sin ejercitar la forma que el servicio
    usa —``with ... as (resuelta, rol)``— y el día que alguien la cambiara aquí
    no se enteraría nadie.
    """
    yield 7, "owner"


def _entorno(mod: Any, almacen: _AlmacenFalso, repo: _RepoFalso, *, pursuit_existe: bool = True):
    """Parchea organización, pursuit, repositorio y almacén."""
    return (
        patch.object(mod, "alcance_resuelto", _alcance_falso),
        patch.object(
            mod,
            "_require_pursuit",
            side_effect=(None if pursuit_existe else mod.PursuitNotFoundError("no existe")),
        ),
        patch.object(mod, "get_object_store", return_value=almacen),
        patch.object(mod, "PursuitAttachmentsRepository", return_value=repo),
    )


class TestSubir:
    def test_guarda_el_binario_y_registra_la_fila(self) -> None:
        import services.pursuit_attachments as mod

        almacen, repo = _AlmacenFalso(), _RepoFalso()
        with (a := _entorno(mod, almacen, repo))[0], a[1], a[2], a[3]:
            fila = mod.subir(
                1, 42, filename="propuesta.pdf", content_type="application/pdf", data=PDF
            )

        assert fila is not None
        assert list(almacen.objetos.values()) == [PDF]
        # La clave lleva organización y expediente: ver `blob_key`.
        clave = next(iter(almacen.objetos))
        assert "/7/42/" in clave
        assert repo.creadas[0]["size_bytes"] == len(PDF)

    def test_sin_bucket_no_acepta_la_subida(self) -> None:
        """`NullObjectStore.put` no lanza: aceptar sería prometer una descarga."""
        import services.pursuit_attachments as mod

        almacen, repo = _AlmacenFalso(enabled=False), _RepoFalso()
        with (a := _entorno(mod, almacen, repo))[0], a[1], a[2], a[3]:
            with pytest.raises(mod.AttachmentStoreUnavailable):
                mod.subir(1, 42, filename="p.pdf", content_type="application/pdf", data=PDF)
        assert almacen.objetos == {}

    def test_un_rechazo_no_deja_bytes_en_el_bucket(self) -> None:
        """Si el pursuit no era de esa organización, el objeto escrito se borra."""
        import services.pursuit_attachments as mod

        almacen, repo = _AlmacenFalso(), _RepoFalso(crea=False)
        with (a := _entorno(mod, almacen, repo))[0], a[1], a[2], a[3]:
            fila = mod.subir(1, 42, filename="p.pdf", content_type="application/pdf", data=PDF)

        assert fila is None
        assert almacen.objetos == {}, "quedaron bytes de un intento rechazado"
        assert almacen.borrados, "no se limpió el objeto huérfano"

    def test_el_tope_por_organizacion_frena_antes_de_escribir(self) -> None:
        import services.pursuit_attachments as mod

        almacen = _AlmacenFalso()
        repo = _RepoFalso(ocupado=mod.MAX_BYTES_POR_ORGANIZACION)
        with (a := _entorno(mod, almacen, repo))[0], a[1], a[2], a[3]:
            with pytest.raises(mod.AttachmentTooLarge):
                mod.subir(1, 42, filename="p.pdf", content_type="application/pdf", data=PDF)
        assert almacen.objetos == {}

    def test_un_tipo_fuera_de_la_lista_no_llega_al_almacen(self) -> None:
        import services.pursuit_attachments as mod

        almacen, repo = _AlmacenFalso(), _RepoFalso()
        with (a := _entorno(mod, almacen, repo))[0], a[1], a[2], a[3]:
            with pytest.raises(mod.AttachmentTypeRejected):
                mod.subir(
                    1,
                    42,
                    filename="virus.exe",
                    content_type="application/x-msdownload",
                    data=PDF,
                )
        assert almacen.objetos == {}


class TestDescargarYBorrar:
    def test_descarga_devuelve_fila_y_bytes(self) -> None:
        import services.pursuit_attachments as mod

        almacen, repo = _AlmacenFalso(), _RepoFalso()
        with (a := _entorno(mod, almacen, repo))[0], a[1], a[2], a[3]:
            mod.subir(1, 42, filename="p.pdf", content_type="application/pdf", data=PDF)
            resultado = mod.descargar(1, 1)

        assert resultado is not None
        fila, contenido = resultado
        assert contenido == PDF
        assert fila["filename"] == "p.pdf"

    def test_una_fila_sin_binario_no_devuelve_bytes_vacios(self) -> None:
        """Mejor 404 que servir un fichero de cero bytes como si fuera el suyo."""
        import services.pursuit_attachments as mod

        almacen, repo = _AlmacenFalso(), _RepoFalso()
        with (a := _entorno(mod, almacen, repo))[0], a[1], a[2], a[3]:
            mod.subir(1, 42, filename="p.pdf", content_type="application/pdf", data=PDF)
            almacen.objetos.clear()  # el objeto desapareció del bucket
            assert mod.descargar(1, 1) is None

    def test_borrar_marca_la_fila_y_conserva_el_binario(self) -> None:
        """v131: borrado lógico, y el objeto del almacén **se queda**.

        Antes esto fijaba «primero la fila, después el binario». El orden ya no
        existe porque el segundo paso tampoco: borrar el objeto haría
        irreversible lo que la marca hace reversible, y restaurar la fila daría
        una descarga rota.
        """
        import services.pursuit_attachments as mod

        almacen, repo = _AlmacenFalso(), _RepoFalso()
        with (a := _entorno(mod, almacen, repo))[0], a[1], a[2], a[3]:
            mod.subir(1, 42, filename="p.pdf", content_type="application/pdf", data=PDF)
            assert mod.borrar(1, 1) is True
            # Fuera de las lecturas...
            assert repo.get(1, organization_id=1) is None
            # ...pero el binario sigue, y la fila que lo apunta también.
            assert almacen.objetos != {}
            assert almacen.borrados == []

    def test_borrar_lo_que_no_es_tuyo_devuelve_false(self) -> None:
        import services.pursuit_attachments as mod

        almacen, repo = _AlmacenFalso(), _RepoFalso()
        with (a := _entorno(mod, almacen, repo))[0], a[1], a[2], a[3]:
            assert mod.borrar(1, 999) is False
        assert almacen.borrados == []


class TestPurgaDeOrganizacion:
    def test_purga_todas_las_claves_de_la_organizacion(self) -> None:
        """ADR-030 §D: el adjunto es dato corporativo y muere con la organización."""
        import services.pursuit_attachments as mod

        almacen, repo = _AlmacenFalso(), _RepoFalso()
        with (a := _entorno(mod, almacen, repo))[0], a[1], a[2], a[3]:
            mod.subir(1, 42, filename="p.pdf", content_type="application/pdf", data=PDF)
            claves = repo.keys_de_organizacion(7)

        with (
            patch.object(mod, "PursuitAttachmentsRepository", return_value=repo),
            patch("shared.object_store.purge_keys", return_value=len(claves)) as purgar,
        ):
            assert mod.purgar_organizacion(7) == 1
        purgar.assert_called_once_with(claves)

    def test_sin_adjuntos_no_llama_al_almacen(self) -> None:
        import services.pursuit_attachments as mod

        repo = _RepoFalso()
        with (
            patch.object(mod, "PursuitAttachmentsRepository", return_value=repo),
            patch("shared.object_store.purge_keys") as purgar,
        ):
            assert mod.purgar_organizacion(7) == 0
        purgar.assert_not_called()
