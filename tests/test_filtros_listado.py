"""F1.1 — los ocho filtros que faltaban en el listado.

Dos clases de test, y la segunda es la que importa:

- :class:`TestClausulas` comprueba el SQL que se genera, sin BD. Barato y
  suficiente para las reglas que se pueden leer (prefijo en el CPV, códigos
  normalizados, NULL fuera del rango de importe).
- :class:`TestParidad` compara **listado por offset, cursor y rama FTS** con
  los mismos filtros. Es el criterio de aceptación del plan y el que protege
  contra la avería real: `list_cursor` tenía sus propias cláusulas y comparaba
  `tecnologia` por igualdad cuando la columna guarda un CSV, así que el
  endpoint «recomendado para datasets grandes» enseñaba un universo distinto
  del que decía sustituir. Necesita Postgres.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Any

import pytest
from sqlalchemy import and_, select

from db.models import compile_query, licitaciones
from db.repositories.licitaciones import (
    LicitacionRepository,
    _codigo_en,
    _normaliza_codigo,
)

_repo = LicitacionRepository()


def _sql(**filtros: Any) -> str:
    """El WHERE que produce `_base_filters`, como texto, para poder afirmar."""
    clauses = _repo._base_filters(**filtros)
    stmt = select(licitaciones.c.id_externo).where(and_(*clauses))
    sql, _params = compile_query(stmt)
    return sql


class TestNormalizacionDeCodigos:
    def test_quita_ceros_a_la_izquierda(self) -> None:
        assert _normaliza_codigo("01") == "1"
        assert _normaliza_codigo(" 009 ") == "9"

    def test_deja_los_no_numericos_como_estan(self) -> None:
        assert _normaliza_codigo("ABC") == "ABC"

    def test_el_cero_sobrevive(self) -> None:
        """`ltrim('0','0')` deja cadena vacía, que no es ningún código."""
        assert _normaliza_codigo("0") == "0"
        assert _normaliza_codigo("000") == "0"

    def test_lista_vacia_no_filtra_nada(self) -> None:
        """Un multi-valor con sólo espacios no puede vaciar el listado."""
        sql, _ = compile_query(
            select(licitaciones.c.id_externo).where(
                _codigo_en(licitaciones.c.procedimiento, ["", "  "])
            )
        )
        assert "1=1" in sql


class TestClausulas:
    def test_sin_filtros_nuevos_el_where_no_cambia(self) -> None:
        """Todos son aditivos: el listado de siempre sigue igual."""
        antes = _sql()
        despues = _sql(
            importe_min=None,
            importe_max=None,
            cpv=None,
            organo=None,
            provincia=None,
            procedimiento=None,
            tramitacion=None,
            tipo_contrato=None,
            dias_restantes_max=None,
        )
        assert antes == despues

    def test_importe_acota_por_los_dos_lados(self) -> None:
        sql = _sql(importe_min=100_000, importe_max=500_000)
        assert "importe >=" in sql
        assert "importe <=" in sql

    def test_cpv_es_prefijo_y_no_igualdad(self) -> None:
        """`72` tiene que traer los servicios de TI enteros."""
        sql = _sql(cpv="72")
        assert "LIKE" in sql.upper()
        assert "cpv =" not in sql

    def test_cpv_multivalor(self) -> None:
        sql = _sql(cpv="72,48")
        assert sql.upper().count("LIKE") >= 2

    def test_organo_pliega_acentos(self) -> None:
        """«Cataluña» y «Cataluna» no pueden ser dos órganos distintos."""
        sql = _sql(organo="Ayuntamiento de Alcalá")
        assert "translate" in sql.lower()

    def test_procedimiento_compara_normalizado_en_los_dos_lados(self) -> None:
        """Sin el `ltrim` en SQL, las filas guardadas como `01` se pierden."""
        sql = _sql(procedimiento="1")
        assert "ltrim" in sql.lower()

    def test_dias_restantes_excluye_terminales(self) -> None:
        """Un adjudicado con fecha límite futura no «vence en 5 días»."""
        sql = _sql(dias_restantes_max=5)
        assert "estado" in sql
        assert "fecha_limite" in sql

    def test_dias_restantes_pone_suelo_en_hoy(self) -> None:
        """«Vence en 30 días» no puede incluir lo que venció ayer."""
        sql = _sql(dias_restantes_max=30)
        assert sql.count("fecha_limite") >= 2


@pytest.mark.usefixtures("tmp_db")
class TestParidad:
    """El mismo filtro devuelve el mismo universo en las tres rutas."""

    @staticmethod
    def _sembrar(conn: Any) -> None:
        base = datetime.now(UTC)
        filas = [
            # (id, titulo, importe, cpv, organo, provincia, proc, tram, tipo, dias)
            (
                "E1",
                "Mantenimiento SAP",
                250_000.0,
                "72220000",
                "Ayuntamiento de Alcalá",
                "Madrid",
                "1",
                "1",
                "2",
                10,
            ),
            (
                "E2",
                "Licencias SAP y soporte",
                900_000.0,
                "48000000",
                "Diputación de Cádiz",
                "Cádiz",
                "9",
                "2",
                "2",
                40,
            ),
            (
                "E3",
                "Obra menor",
                50_000.0,
                "45000000",
                "Ayuntamiento de Alcalá",
                "Madrid",
                "01",
                "1",
                "3",
                90,
            ),
        ]
        for id_ext, titulo, importe, cpv, organo, prov, proc, tram, tipo, dias in filas:
            conn.execute(
                "INSERT INTO licitaciones (id_externo, titulo, importe, cpv, "
                "organo_contratacion, provincia, procedimiento, tramitacion, "
                "tipo_contrato, tecnologia, estado, fecha_publicacion, fecha_limite) "
                "VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)",
                (
                    id_ext,
                    titulo,
                    importe,
                    cpv,
                    organo,
                    prov,
                    proc,
                    tram,
                    tipo,
                    "SAP",
                    "PUB",
                    (base - timedelta(days=5)).date().isoformat(),
                    (base + timedelta(days=dias)).date().isoformat(),
                ),
            )

    @pytest.fixture(autouse=True)
    def _datos(self, tmp_db: Any) -> None:
        from db.database import connect

        with connect() as c:
            self._sembrar(c)

    @staticmethod
    def _ids_offset(**filtros: Any) -> set[str]:
        items, _total = _repo.list_paginated(limit=200, **filtros)
        return {str(i["id_externo"]) for i in items}

    @staticmethod
    def _ids_cursor(**filtros: Any) -> set[str]:
        return {str(i["id_externo"]) for i in _repo.list_cursor(limit=200, **filtros)}

    @pytest.mark.parametrize(
        "filtros",
        [
            {},
            {"importe_min": 100_000},
            {"importe_max": 100_000},
            {"importe_min": 100_000, "importe_max": 500_000},
            {"cpv": "72"},
            {"cpv": "72,48"},
            {"organo": "alcala"},
            {"provincia": "Madrid"},
            {"procedimiento": "1"},
            {"tramitacion": "2"},
            {"tipo_contrato": "2"},
            {"dias_restantes_max": 30},
            {"cpv": "72", "importe_min": 100_000, "procedimiento": "1"},
        ],
    )
    def test_offset_y_cursor_devuelven_lo_mismo(self, filtros: dict[str, Any]) -> None:
        assert self._ids_offset(**filtros) == self._ids_cursor(**filtros)

    def test_el_texto_libre_no_descarta_los_filtros(self) -> None:
        """La rama FTS reescribe el WHERE en SQL crudo: si se queda atrás,
        escribir en la caja de búsqueda anula los filtros en silencio."""
        con_texto = self._ids_offset(q="SAP", importe_min=500_000)
        assert con_texto == {"E2"}

    def test_el_prefijo_de_cpv_no_es_igualdad(self) -> None:
        assert self._ids_offset(cpv="722") == {"E1"}

    def test_el_codigo_con_cero_a_la_izquierda_casa(self) -> None:
        """E3 está guardado como `01`; pedir `1` tiene que traerlo."""
        assert "E3" in self._ids_offset(procedimiento="1")

    def test_importe_nulo_queda_fuera_del_rango(self) -> None:
        from db.database import connect

        with connect() as c:
            c.execute(
                "INSERT INTO licitaciones (id_externo, titulo, tecnologia, estado, "
                "fecha_publicacion) VALUES (%s, %s, %s, %s, %s)",
                ("E4", "Sin importe", "SAP", "PUB", "2026-09-01"),
            )
        assert "E4" not in self._ids_offset(importe_min=0)
        assert "E4" in self._ids_offset()

    def test_dias_restantes_no_trae_los_terminales(self) -> None:
        from db.database import connect

        with connect() as c:
            c.execute("UPDATE licitaciones SET estado = 'ADJ' WHERE id_externo = 'E1'")
        assert "E1" not in self._ids_offset(dias_restantes_max=30)
