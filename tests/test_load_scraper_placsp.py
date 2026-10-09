"""Tests de carga del scraper de PLACSP: un feed grande y un upsert masivo.

Ninguno mira el reloj. Los dos medían rendimiento con ``time.perf_counter()``
contra un suelo absoluto (10 000 entradas/s y 200 licitaciones/s), y eso mide el
runner: en CI corren dentro del check requerido, que no filtra por marker. Lo
que protegían se comprueba ahora por su causa, que es determinista.
"""

from __future__ import annotations

from contextlib import contextmanager

import pytest

from scraper.codice_parser import NS, parse_atom_bytes

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _entrada(i: int) -> str:
    """Una ``<entry>`` CODICE con los datos propios de la entrada ``i``."""
    expediente = f"CARGA-{i:05d}"
    return (
        "<entry>"
        f"<id>https://example.com/{expediente}</id>"
        f"<title>Mantenimiento SAP ERP {i}</title>"
        "<updated>2026-01-15T10:00:00Z</updated>"
        "<cacext:ContractFolderStatus>"
        f"<cbc:ContractFolderID>{expediente}</cbc:ContractFolderID>"
        "<cacext:LocatedContractingParty><cac:Party><cac:PartyName>"
        f"<cbc:Name>Organismo {i}</cbc:Name>"
        "</cac:PartyName></cac:Party></cacext:LocatedContractingParty>"
        "<cac:ProcurementProject>"
        f"<cbc:Name>Mantenimiento SAP ERP {i}</cbc:Name>"
        "<cac:RequiredCommodityClassification>"
        "<cbc:ItemClassificationCode>72267100</cbc:ItemClassificationCode>"
        "</cac:RequiredCommodityClassification>"
        "<cac:BudgetAmount>"
        f'<cbc:TaxExclusiveAmount currencyID="EUR">{100_000 + i}</cbc:TaxExclusiveAmount>'
        "</cac:BudgetAmount>"
        "</cac:ProcurementProject>"
        "</cacext:ContractFolderStatus>"
        "</entry>"
    )


def _feed(n: int) -> bytes:
    """Feed ATOM de ``n`` entradas, con los namespaces del propio parser."""
    espacios = " ".join(
        f'xmlns="{uri}"' if prefijo == "atom" else f'xmlns:{prefijo}="{uri}"'
        for prefijo, uri in NS.items()
    )
    entradas = "".join(_entrada(i) for i in range(n))
    return f'<?xml version="1.0" encoding="UTF-8"?><feed {espacios}>{entradas}</feed>'.encode()


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


class TestFeedGrande:
    """Un feed de N entradas sale entero, y cada licitación con SUS datos.

    Pasa por ``parse_atom_bytes``, el parser de verdad. La versión anterior
    cronometraba ``Element.find`` de la librería estándar sobre un feed de
    juguete: no ejercía código del proyecto, así que su suelo de entradas por
    segundo solo medía el runner.

    Comparar cada licitación con su entrada es lo que vigila el rendimiento sin
    reloj. El parseo se vuelve cuadrático cuando un XPath deja de ser relativo a
    la entrada y recorre el documento entero, y ese mismo fallo le da a todas
    las licitaciones los datos de la primera.
    """

    @pytest.mark.parametrize("n", [100, 500, 1000])
    def test_un_feed_de_n_entradas_sale_entero_y_cada_una_con_sus_datos(self, n: int) -> None:
        licitaciones = [lic for lic, _adjudicaciones in parse_atom_bytes(_feed(n))]

        assert [
            (lic.id_externo, lic.titulo, lic.organo_contratacion, lic.importe)
            for lic in licitaciones
        ] == [
            (f"CARGA-{i:05d}", f"Mantenimiento SAP ERP {i}", f"Organismo {i}", 100_000.0 + i)
            for i in range(n)
        ]


class TestUpsertMasivo:
    """Escribir N licitaciones cuesta un puñado de viajes a la BD, no uno por fila.

    Es lo que decide el rendimiento del upsert contra una BD remota (ver el
    comentario del ``executemany`` en ``upsert_licitaciones``), y se cuenta en
    vez de cronometrarse. Hoy son tres sentencias para cualquier N de hasta 500:
    las existentes, el catálogo de las sombras y el ``executemany``. El umbral es
    holgado a propósito, como el de ``test_ingesta_no_hace_un_round_trip_por_fila``:
    solo salta si vuelve el patrón fila a fila.

    El suelo de 200 licitaciones/s que había aquí no veía esa regresión: medido
    contra un Postgres local, escribir fila a fila seguía por encima de 1 500.
    """

    @pytest.mark.parametrize("n", [100, 500])
    def test_escribir_n_licitaciones_no_cuesta_un_viaje_por_fila(
        self, n: int, tmp_db, monkeypatch
    ) -> None:
        import db.upsert as up
        from db.database import Licitacion

        viajes: list[str] = []
        conectar_de_verdad = up.connect

        class _Contando:
            def __init__(self, conn) -> None:
                self._conn = conn

            def execute(self, sql, *args):
                viajes.append(sql)
                return self._conn.execute(sql, *args)

            def executemany(self, sql, seq):
                viajes.append(sql)
                return self._conn.executemany(sql, seq)

        @contextmanager
        def contando():
            with conectar_de_verdad() as conn:
                yield _Contando(conn)

        monkeypatch.setattr(up, "connect", contando)

        lics = [
            Licitacion(
                id_externo=f"BULK-{i:05d}",
                titulo=f"Bulk test {i}",
                organo_contratacion=f"Organo {i}",
                estado="En plazo",
                fecha_publicacion="2026-01-15",
                importe=100000.0 + i,
                cpv="72000000",
                url=f"https://example.com/{i}",
            )
            for i in range(n)
        ]

        nuevas, actualizadas = up.upsert_licitaciones(lics)

        assert (nuevas, actualizadas) == (n, 0)
        assert len(viajes) < n / 10, (
            f"{len(viajes)} viajes para {n} filas: el upsert volvió a escribir fila a fila"
        )
        assert up.count_licitaciones() == n
