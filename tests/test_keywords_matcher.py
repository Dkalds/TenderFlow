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

    @pytest.mark.parametrize(
        ("keyword", "texto"),
        [
            # Títulos reales de PSCP etiquetados SAP (2026-10-11): «concurs» es
            # concurso en catalán, no el plural de SAP Concur.
            ("concur", "Concurs de Castells de la Bisbal del Penedès"),
            ("concur", "Pagament Jurat Concurs Pedralbes_PR"),
            ("sap", "Saps com reciclar? Campanya de sensibilització"),
            ("oracle", "Els oracles de l'antiga Grècia: conferències"),
            ("licencias sap", "Licencias saps"),
            # La Gerencia de Informática de la Seguridad Social no es un SIG.
            ("gis", "Mantenimiento de sistemas de información de la GISS para el INSS"),
        ],
    )
    def test_un_nombre_de_producto_no_tiene_plural(self, keyword: str, texto: str) -> None:
        assert not patron_de_keywords([keyword]).search(texto), (keyword, texto)

    @pytest.mark.parametrize(
        ("keyword", "texto"),
        [
            ("concur", "Suministro de licencias SAP CONCUR para el Grupo RENFE"),
            ("migración sap", "MIGRACION  SAP AL NUEVO ENTORNO"),
            ("s/4hana", "Llicències SAP S/4HANA"),
            ("gis", "Plataforma GIS corporativa del Ayuntamiento"),
        ],
    )
    def test_un_nombre_de_producto_sigue_casando_en_singular(
        self, keyword: str, texto: str
    ) -> None:
        assert patron_de_keywords([keyword]).search(texto), (keyword, texto)


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

    def test_un_concurso_en_catalan_no_es_sap_concur(self) -> None:
        assert matches_technology(
            "anunci de felicitació a la Colla Castellera La Bisbal del Penedès "
            "amb motiu de la seva victòria en el concurs de castells"
        ) == (False, {})

    def test_texto_con_tildes_descompuestas(self) -> None:
        """El texto extraído de un PDF llega a menudo en NFD (la tilde como signo
        aparte): la comprobación previa del label tampoco puede fallar ahí."""
        texto = unicodedata.normalize("NFD", "Implantación de la administración electrónica")
        _, por_tec = matches_technology(texto)
        assert "administración electrónica" in por_tec["ADMIN_ELECTRONICA"]


class TestSenalDePliegos:
    def test_texto_de_pdf_con_tildes_descompuestas(self) -> None:
        from services.tech_signal import score_documents

        texto = unicodedata.normalize(
            "NFD", "Implantación de la administración electrónica y de la sede electrónica."
        )
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

    def test_un_concurso_en_catalan_no_es_sap(self) -> None:
        assert matches_sap("Concurs de Castells de la Bisbal del Penedès") == (False, [])


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

    @pytest.mark.parametrize(
        ("titulo", "cpv"),
        [
            # Las tres filas de producción que destaparon el fallo (2026-10-11).
            ("Concurs de Castells de la Bisbal del Penedès", "79952100-3"),
            (
                "anunci de felicitació a la Colla Castellera La Bisbal del Penedès "
                "amb motiu de la seva victòria en el concurs de castells",
                "79341000-6",
            ),
            ("Pagament Jurat Concurs Pedralbes_PR", "71210000-3"),
        ],
    )
    def test_un_concurso_no_entra_como_sap(self, titulo: str, cpv: str) -> None:
        from scraper.connectors.pscp import MOTIVO_SIN_SENAL, senal_tecnologica

        assert senal_tecnologica(titulo, cpv).motivo == MOTIVO_SIN_SENAL

    def test_un_concurso_de_software_entra_por_cpv_y_sin_etiqueta_sap(self) -> None:
        """Con CPV 72 la fila es TI, pero «concurs» no la hace SAP."""
        from scraper.connectors.pscp import MOTIVO_CPV_TI, senal_tecnologica

        senal = senal_tecnologica("Concurs de projectes per a la nova web", "72413000-8")
        assert senal.motivo == MOTIVO_CPV_TI
        assert senal.tecnologias == ()

    @pytest.mark.parametrize(
        ("titulo", "cpv"),
        [
            # «Concurs» sin la ese (pscp:F240000036) y partido por un guion de
            # final de línea (PLACSP 2023/000169): `concur` a secas es ambigua.
            ("Concur monòlegs alumnat escola Rec Comtal.Tr.Vella", "98300000-6"),
            (
                "Servicios y suministros necesarios para el desarrollo de la activi-dad "
                "(exhibiciones, competiciones y concur-sos deportivos)",
                "92600000",
            ),
        ],
    )
    def test_concur_a_secas_necesita_un_cpv_de_software(self, titulo: str, cpv: str) -> None:
        from scraper.connectors.pscp import MOTIVO_AMBIGUA_SIN_CPV_TI, senal_tecnologica

        assert senal_tecnologica(titulo, cpv).motivo == MOTIVO_AMBIGUA_SIN_CPV_TI

    @pytest.mark.parametrize(
        ("titulo", "cpv"),
        [
            # Concur nombrado sin «SAP», corroborado por el CPV (PLACSP 2024-02032).
            (
                "Servicio de desarrollo y configuración de dietas para viajes "
                "internacionales en la aplicación Concur.",
                "72267100",
            ),
            # CPV de ingeniería, pero «SAP Concur» es `sap concur`, que no es
            # ambigua (pscp:CONTR/2020/0000000680).
            (
                "Servei d'implantació del mòdul de gestió de despeses de viatges "
                "SAP Concur Expenses i aprovisionament de les llicències",
                "71356200-0",
            ),
        ],
    )
    def test_sap_concur_de_verdad_sigue_entrando(self, titulo: str, cpv: str) -> None:
        from scraper.connectors.pscp import MOTIVO_ADMITIDA, senal_tecnologica

        senal = senal_tecnologica(titulo, cpv)
        assert senal.motivo == MOTIVO_ADMITIDA
        assert senal.tecnologias == ("SAP",)

    def test_una_ambigua_no_anade_etiqueta_a_una_fila_con_senal_firme(self) -> None:
        """«mantenimiento correctivo» es la frase del contrato de ascensores:
        junto a `s/4hana` no convierte la fila en DESARROLLO."""
        from scraper.connectors.pscp import MOTIVO_ADMITIDA, senal_tecnologica

        senal = senal_tecnologica(
            "Mantenimiento correctivo de la plataforma SAP S/4HANA", "72267000-4"
        )
        assert senal.motivo == MOTIVO_ADMITIDA
        assert senal.tecnologias == ("SAP",)
        assert "mantenimiento correctivo" not in senal.keywords

    def test_si_todo_es_ambiguo_decide_el_cpv_como_antes(self) -> None:
        from scraper.connectors.pscp import MOTIVO_ADMITIDA, senal_tecnologica

        senal = senal_tecnologica("Ampliació de la cabina de backup del CPD", "30233000-1")
        assert senal.motivo == MOTIVO_ADMITIDA
        assert senal.tecnologias == ("CLOUD_INFRA",)


class TestEtiquetasConSenalFirme:
    def test_quita_la_etiqueta_que_solo_sostiene_una_ambigua(self) -> None:
        from config.keywords import etiquetas_con_senal_firme

        assert etiquetas_con_senal_firme(
            {"SAP": ["s/4hana", "sap"], "DESARROLLO": ["mantenimiento correctivo"]}
        ) == {"SAP": ["s/4hana", "sap"]}

    def test_si_todas_son_ambiguas_no_toca_nada(self) -> None:
        from config.keywords import etiquetas_con_senal_firme

        coincidencias = {"CLOUD_INFRA": ["cpd", "backup"], "CRM": ["crm"]}
        assert etiquetas_con_senal_firme(coincidencias) == coincidencias

    def test_las_ambiguas_viven_en_config(self) -> None:
        """`services/` las necesita y no puede importar de `scraper/`."""
        from config.keywords import KEYWORDS_AMBIGUAS
        from scraper.puerta_tecnologica import KEYWORDS_AMBIGUAS as de_la_puerta

        assert de_la_puerta is KEYWORDS_AMBIGUAS


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

    def test_solo_ambiguas_necesitan_cpv_ti(self) -> None:
        """Mismo criterio que la puerta: «cpd» a secas es la limpieza de la sala."""
        from services.ml.classifier_pipeline import _augment_text, _keyword_fallback_score

        kws = ["cpd", "kubernetes"]
        sin_ti = _augment_text("Limpieza de la sala del CPD", cpv="90910000")
        con_ti = _augment_text("Ampliación del CPD", cpv="72000000")
        assert _keyword_fallback_score(sin_ti, kws) == 0.0
        assert _keyword_fallback_score("Limpieza de la sala del CPD", kws) == 0.0
        assert _keyword_fallback_score(con_ti, kws) == 0.5
        assert _keyword_fallback_score("CPD con Kubernetes", kws) == 1.0


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
