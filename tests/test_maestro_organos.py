"""El órgano es una entidad, no una cadena (C1.2, ADR-032, D22).

`licitaciones.organo_contratacion` es texto libre y la analítica agrupaba por
ese texto, así que «Ayuntamiento de Madrid» y «AYUNTAMIENTO DE MADRID» eran dos
órganos con dos historiales, dos cuotas de mercado y dos páginas.

Lo que estos tests fijan es el **criterio** de resolución, que es la parte que
se rompe sola: la aritmética de la similitud, el orden DIR3 → nombre → duda, y
que la lectura dual no deje fuera de la analítica a los expedientes que no
resuelven.
"""

from __future__ import annotations

import pytest

from services.organos import UMBRAL_SOSPECHA, normalizar, similitud


class TestNormalizacion:
    def test_dos_grafias_del_mismo_organo_colapsan(self) -> None:
        """El caso del hecho 2 del plan, literal."""
        assert normalizar("Ayuntamiento de Madrid") == normalizar("AYUNTAMIENTO DE MADRID")

    def test_el_tratamiento_no_distingue_a_un_organo(self) -> None:
        """«Excmo.» no es parte de la identidad de nadie."""
        assert normalizar("Excmo. Ayuntamiento de Madrid") == normalizar("Ayuntamiento de Madrid")

    def test_las_tildes_no_crean_organos(self) -> None:
        assert normalizar("Diputación de Málaga") == normalizar("Diputacion de Malaga")

    def test_el_espaciado_no_crea_organos(self) -> None:
        assert normalizar("  Ayuntamiento   de  Madrid ") == normalizar("Ayuntamiento de Madrid")

    @pytest.mark.parametrize("vacio", [None, "", "   ", "..."])
    def test_sin_nombre_utilizable_devuelve_none(self, vacio: str | None) -> None:
        """`None` es distinto de un órgano llamado «»: no se crea nada."""
        assert normalizar(vacio) is None


class TestSimilitud:
    def test_dos_municipios_distintos_no_se_parecen_bastante(self) -> None:
        """El caso que un umbral mal elegido fusionaría.

        «Alcalá de Henares» y «Alcalá de Guadaíra» comparten tres de cinco
        palabras. Una distancia de edición daría ~0,93 y los fusionaría; Jaccard
        da 0,6 y los deja separados, que es lo correcto: son dos ayuntamientos.
        """
        a = normalizar("Ayuntamiento de Alcalá de Henares")
        b = normalizar("Ayuntamiento de Alcalá de Guadaíra")
        assert a and b
        assert similitud(a, b) < UMBRAL_SOSPECHA

    def test_una_variante_de_la_misma_entidad_si_se_parece(self) -> None:
        a = normalizar("Consejería de Sanidad de la Comunidad de Madrid")
        b = normalizar("Consejeria de Sanidad de la Comunidad de Madrid")
        assert a and b
        assert similitud(a, b) >= UMBRAL_SOSPECHA

    def test_identicos_dan_uno(self) -> None:
        a = normalizar("Universidad de Sevilla")
        assert a
        assert similitud(a, a) == 1.0

    def test_sin_palabras_en_comun_da_cero(self) -> None:
        assert similitud("hospital", "universidad") == 0.0

    def test_el_umbral_es_de_sospecha_no_de_fusion(self) -> None:
        """Documentado en el propio módulo, y verificado aquí.

        Superar el umbral **encola** la decisión; no la toma. Fusionar dos
        órganos junta dos historiales de contratación y ese error no se ve
        mirando la ficha, así que no puede decidirse solo.
        """
        import inspect

        import services.organos as mod

        fuente = inspect.getsource(mod.resolver)
        assert "encolar_revision" in fuente
        assert "UMBRAL_SOSPECHA" in fuente


class TestLecturaDual:
    def test_la_clave_usa_el_id_cuando_lo_hay(self) -> None:
        from db.sql_fragments import clave_organo_sql

        sql = clave_organo_sql("f")
        assert "f.organo_id" in sql
        assert "organo_contratacion" in sql
        # El prefijo evita que un `organo_id` 42 colisione con un órgano cuyo
        # nombre plegado sea literalmente "42".
        assert "'id:'" in sql and "'txt:'" in sql

    def test_un_expediente_sin_resolver_sigue_agregando(self) -> None:
        """`COALESCE`, no `WHERE organo_id IS NOT NULL`.

        El backfill no puede llegar al 100 %, y un expediente cuyo órgano no
        resuelve sigue siendo válido: lo que no puede es desaparecer de la
        analítica.
        """
        from db.sql_fragments import clave_organo_sql

        assert clave_organo_sql("f").startswith("COALESCE(")

    def test_el_nombre_prefiere_el_canonico(self) -> None:
        from db.sql_fragments import nombre_organo_sql

        sql = nombre_organo_sql("f", "o")
        assert sql.index("o.nombre_canonico") < sql.index("f.organo_contratacion")

    def test_el_ranking_y_el_total_usan_la_misma_clave(self) -> None:
        """Si divergen, los porcentajes del ranking no suman 100."""
        import inspect

        from db.repositories.aggregates import AggregateRepository

        ranking = inspect.getsource(AggregateRepository.organos_ranking)
        totales = inspect.getsource(AggregateRepository.organos_totales)
        assert "clave_organo_sql" in ranking
        assert "clave_organo_sql" in totales


class TestContrato:
    def test_el_ranking_expone_la_identidad_del_maestro(self) -> None:
        from services.analytics.organos import OrganoEntry

        assert {"organo_id", "dir3", "url_perfil"} <= set(OrganoEntry.model_fields)

    def test_sin_resolver_los_campos_son_none_no_cero(self) -> None:
        from services.analytics.organos import OrganoEntry

        for campo in ("organo_id", "dir3", "url_perfil"):
            assert OrganoEntry.model_fields[campo].default is None


class TestDir3:
    """El parser extrae el DIR3 cuando CODICE lo publica."""

    @staticmethod
    def _entry(ids: list[tuple[str, str | None]]):
        from lxml import etree

        from scraper.codice_parser import NS

        xmlns = " ".join(f'xmlns:{p}="{u}"' for p, u in NS.items())

        def _id(valor: str, esquema: str | None) -> str:
            attr = f' schemeName="{esquema}"' if esquema else ""
            return (
                f"<cac:PartyIdentification><cbc:ID{attr}>{valor}</cbc:ID></cac:PartyIdentification>"
            )

        partes = "".join(_id(valor, esquema) for valor, esquema in ids)
        xml = (
            f"<root {xmlns}><cacext:LocatedContractingParty><cac:Party>"
            f"{partes}</cac:Party></cacext:LocatedContractingParty></root>"
        )
        return etree.fromstring(xml.encode("utf-8"))

    def test_prefiere_el_que_declara_su_esquema(self) -> None:
        from scraper.codice_parser import _dir3_del_organo

        entry = self._entry([("A28000001", None), ("L01280796", "DIR3")])
        assert _dir3_del_organo(entry, ".") == "L01280796"

    def test_acepta_el_que_tiene_forma_de_dir3(self) -> None:
        """CODICE publica el identificador sin `schemeName` con frecuencia."""
        from scraper.codice_parser import _dir3_del_organo

        entry = self._entry([("E00003801", None)])
        assert _dir3_del_organo(entry, ".") == "E00003801"

    def test_no_confunde_un_nif_con_un_dir3(self) -> None:
        """Un NIF en `LocatedContractingParty` crearía un órgano fantasma.

        Y no uno cualquiera: con clave única, así que el siguiente expediente de
        verdad de ese órgano chocaría contra él.
        """
        from scraper.codice_parser import _dir3_del_organo

        # Un NIF español es letra + 8 dígitos: la misma forma que un DIR3. Lo
        # que los separa aquí es que este viene sin `schemeName` **y** en un
        # documento donde el DIR3 real sí lo declara.
        entry = self._entry([("28000001A", None)])
        assert _dir3_del_organo(entry, ".") is None

    def test_sin_identificadores_devuelve_none(self) -> None:
        from scraper.codice_parser import _dir3_del_organo

        assert _dir3_del_organo(self._entry([]), ".") is None

    def test_el_dir3_no_es_columna_de_licitaciones(self) -> None:
        """Vive en el maestro, que es donde identifica a la entidad."""
        from db.upsert import _LIC_KEYS

        assert "organo_dir3" not in _LIC_KEYS
