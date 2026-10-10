"""El matcher de keywords tolera la forma en que se escriben los títulos (2026-09-27).

Medido contra producción el 2026-09-27: el 16 % de los títulos de PSCP va en
mayúsculas y sin tildes, y el diccionario escribe las keywords con tildes. Con
el matcher anterior «ADMINISTRACION ELECTRONICA» no casaba con «administración
electrónica», «firewalls» no casaba con «firewall» y, como el patrón de un label
era una alternancia ordenada que se queda con la primera que casa, «Suport SAP
FI/CO i SAP MM» solo devolvía `sap` — una keyword ambigua que la puerta de PSCP
descarta si el CPV no la corrobora.

Lo que fija este módulo:

1. El patrón casa sin tildes, en plural, con espacios o saltos de línea de más,
   con guion o espacio y con el apóstrofo tipográfico.
2. Sin perder los límites de palabra que ya protegían («sap» no está en
   «desaparecer»).
3. `matches_technology` y `matches_sap` devuelven la forma **canónica** de la
   keyword (la del diccionario), y todas las que aparecen, no solo la primera:
   la puerta de PSCP compara con esa forma.
4. El tier `rules` del clasificador compila por el mismo sitio.
5. Cambiar el matcher cambia `filter_version`: las filas de antes y de después
   no se filtraron igual.
"""

from __future__ import annotations

import unicodedata
from collections.abc import Iterator

import pytest

from config.keywords import patron_de_keywords
from scraper.filters import matches_sap, matches_technology


@pytest.fixture(autouse=True)
def _desde_la_semilla(monkeypatch: pytest.MonkeyPatch) -> Iterator[None]:
    """Cada test ve la semilla, no la tabla, y parte de la caché vacía."""
    import services.tecnologias_diccionario as mod

    monkeypatch.setattr(mod, "_leer", lambda: (mod.semilla(), mod._hash_de(mod.semilla())))
    mod.invalidar()
    yield
    mod.invalidar()


# ── 1. El patrón ────────────────────────────────────────────────────────────


class TestPatron:
    @pytest.mark.parametrize(
        ("keyword", "texto"),
        [
            ("administración electrónica", "IMPLANTACION DE LA ADMINISTRACION ELECTRONICA"),
            ("administración electrónica", "Administracion electronica municipal"),
            ("gestió documental", "SERVEI DE GESTIO DOCUMENTAL"),
            ("historia clínica electrónica", "HISTORIA CLINICA ELECTRONICA"),
            ("migración", "MIGRACION DEL SISTEMA"),
        ],
    )
    def test_casa_sin_tildes(self, keyword: str, texto: str) -> None:
        assert patron_de_keywords([keyword]).search(texto), (keyword, texto)

    def test_casa_con_tildes_aunque_la_keyword_no_las_lleve(self) -> None:
        assert patron_de_keywords(["gestion documental"]).search("Gestión documental")

    @pytest.mark.parametrize(
        ("keyword", "texto"),
        [
            ("firewall", "Adquisición de firewalls de nueva generación"),
            ("servidor", "Suministro de servidores para el CPD"),
            ("copia de seguridad", "Servicio de copias de seguridad"),
            ("sede electrónica", "Mantenimiento de las sedes electrónicas municipales"),
            ("gestión", "Gestiones varias"),
        ],
    )
    def test_casa_el_plural(self, keyword: str, texto: str) -> None:
        assert patron_de_keywords([keyword]).search(texto), (keyword, texto)

    def test_casa_con_espacios_de_mas_y_saltos_de_linea(self) -> None:
        assert patron_de_keywords(["copia de seguridad"]).search("la copia  de\r\nseguridad")

    @pytest.mark.parametrize("texto", ["económico financiera", "económico-financiera"])
    def test_el_guion_y_el_espacio_valen_lo_mismo(self, texto: str) -> None:
        assert patron_de_keywords(["económico-financiera"]).search(texto)

    def test_casa_con_el_apostrofo_tipografico(self) -> None:
        assert patron_de_keywords(["d'aplicacions"]).search("desenvolupament d\u2019aplicacions")

    @pytest.mark.parametrize(
        ("keyword", "texto"),
        [
            ("sap", "El proyecto desapareció del portal"),
            ("gis", "Registro de entrada"),
            ("erp", "Servicio de interpretación"),
            ("api", "Capital social"),
            ("sap", "Sapiencia"),
        ],
    )
    def test_sigue_respetando_los_limites_de_palabra(self, keyword: str, texto: str) -> None:
        assert not patron_de_keywords([keyword]).search(texto), (keyword, texto)


# ── 2. Lo que devuelven los consumidores ────────────────────────────────────


class TestMatchesTechnology:
    def test_titulo_en_mayusculas_sin_tildes(self) -> None:
        _, por_tec = matches_technology(
            "SISTEMA DE GESTION ECONOMICO-FINANCIERA Y ADMINISTRACION ELECTRONICA"
        )
        assert "sistema de gestión económico-financiera" in por_tec["ERP"]
        assert "administración electrónica" in por_tec["ADMIN_ELECTRONICA"]

    def test_el_plural_devuelve_la_keyword_canonica(self) -> None:
        _, por_tec = matches_technology("Adquisición de firewalls de nueva generación")
        assert "firewall" in por_tec["CIBERSEGURIDAD"]
        assert "firewalls" not in por_tec["CIBERSEGURIDAD"]

    def test_devuelve_todas_las_keywords_presentes_no_solo_la_primera(self) -> None:
        _, por_tec = matches_technology("Suport SAP FI/CO i SAP MM")
        assert {"sap", "sap fi/co", "sap mm"} <= set(por_tec["SAP"])

    def test_no_repite_keywords(self) -> None:
        _, por_tec = matches_technology("SAP sap SAP", "mantenimiento SAP")
        assert por_tec["SAP"].count("sap") == 1

    def test_sin_texto_no_casa(self) -> None:
        assert matches_technology(None, "") == (False, {})

    def test_texto_con_tildes_descompuestas(self) -> None:
        """El texto extraído de un PDF llega a menudo en NFD (la tilde como signo
        aparte): la comprobación previa del label tampoco puede fallar ahí."""
        texto = unicodedata.normalize("NFD", "Implantación de la administración electrónica")
        _, por_tec = matches_technology(texto)
        assert "administración electrónica" in por_tec["ADMIN_ELECTRONICA"]


class TestSenalDePliegos:
    def test_texto_de_pdf_con_tildes_descompuestas(self) -> None:
        from services.tech_signal import score_documents

        texto = unicodedata.normalize("NFD", "Implantación de la administración electrónica.")
        paginas = [{"texto": texto, "tipo": "technical"}, {"texto": texto, "tipo": "technical"}]
        assert "ADMIN_ELECTRONICA" in score_documents(paginas)


class TestMatchesSap:
    def test_texto_con_tildes_descompuestas(self) -> None:
        _, kws = matches_sap(unicodedata.normalize("NFD", "Migración SAP"))
        assert "migración sap" in kws

    def test_devuelve_la_forma_canonica_sin_tildes_en_el_texto(self) -> None:
        found, kws = matches_sap("MIGRACION SAP AL NUEVO ENTORNO")
        assert found
        assert "migración sap" in kws

    def test_devuelve_la_keyword_corta_y_la_larga(self) -> None:
        _, kws = matches_sap("Soporte SAP ERP")
        assert {"sap", "sap erp"} <= set(kws)


# ── 3. La puerta de PSCP compara con la forma canónica ──────────────────────


class TestPuertaPscp:
    def test_una_ambigua_sin_tildes_sigue_siendo_ambigua(self) -> None:
        """Si la keyword volviera en la forma del texto («gestio»), no estaría en
        `KEYWORDS_AMBIGUAS` y la fila entraría por un sistema de calidad ISO."""
        from scraper.connectors.pscp import MOTIVO_AMBIGUA_SIN_CPV_TI, senal_tecnologica

        senal = senal_tecnologica("SISTEMA INTEGRAT DE GESTIO DE LA QUALITAT", "79132000-8")
        assert senal.motivo == MOTIVO_AMBIGUA_SIN_CPV_TI

    def test_sap_con_su_modulo_ya_no_es_solo_la_ambigua(self) -> None:
        from scraper.connectors.pscp import MOTIVO_ADMITIDA, senal_tecnologica

        senal = senal_tecnologica("Suport SAP FI/CO i SAP MM", "79411000-8")
        assert senal.motivo == MOTIVO_ADMITIDA
        assert "SAP" in senal.tecnologias


# ── 4. El tier `rules` del clasificador ─────────────────────────────────────


class TestTierRules:
    def test_casa_sin_tildes(self) -> None:
        from services.ml.classifier_pipeline import _keyword_fallback_score

        score = _keyword_fallback_score(
            "SISTEMA DE GESTION ECONOMICO-FINANCIERA",
            ["sistema de gestión económico-financiera", "erp"],
        )
        assert score == 0.5

    def test_casa_punto_net(self) -> None:
        """Con el `\\b…\\b` propio del tier, `.net` no podía casar nunca."""
        from services.ml.classifier_pipeline import _keyword_fallback_score

        assert _keyword_fallback_score("Desarrollo en plataforma .NET", [".net"]) == 1.0


# ── 5. Versión ──────────────────────────────────────────────────────────────


class TestVersion:
    def test_cambiar_el_matcher_cambia_filter_version(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        import config.keywords as kw
        import services.tecnologias_diccionario as mod

        antes = mod._hash_de(mod.semilla())
        monkeypatch.setattr(kw, "VERSION_MATCHER", "otra-version", raising=False)
        assert mod._hash_de(mod.semilla()) != antes
