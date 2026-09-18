"""La taxonomía tecnológica por categorías y en lenguas cooficiales (2026-09-14).

Fija cuatro cosas de `config/keywords.py`:

1. La forma: cada label tiene ≥ 5 keywords en minúsculas, sin duplicados dentro
   del label ni entre labels (salvo el conjunto intencional, que se declara).
2. Que los consumidores derivan de un único sitio: etiqueta legible, tipo,
   clasificador, LLM, ajustes de organización.
3. Que las categorías se detectan sobre títulos reales en catalán, euskera y
   gallego — el motivo por el que existen.
4. Que los fabricantes siguen detectando exactamente lo que detectaban: las
   categorías se suman, no reescriben.

Todo corre contra la **semilla** (`_leer` parcheado), sin base de datos: lo que
se prueba es el diccionario en código, que es lo que se vuelca en la tabla.
"""

from __future__ import annotations

import json
import re
from collections.abc import Iterator
from pathlib import Path

import pytest

from config.keywords import (
    TECH_CATEGORIAS,
    TECH_LABEL_TIPO,
    TECH_LABELS,
    TECHNOLOGY_KEYWORDS,
    patron_de_keywords,
)
from scraper.filters import matches_technology

#: Keywords que aparecen a propósito en más de un label. Hoy ninguna: cada
#: término pertenece a un único label. Si un día hace falta compartir una,
#: se declara aquí con sus labels y el test la deja pasar solo a ella.
DUPLICADOS_INTENCIONALES: frozenset[tuple[str, frozenset[str]]] = frozenset()

FABRICANTES = frozenset(
    {
        "SAP",
        "SALESFORCE",
        "ORACLE",
        "MICROSOFT",
        "SERVICENOW",
        "WORKDAY",
        "IBM",
        "OPENTEXT",
        "UNIT4",
        "META4",
        "SOPRA",
        "SAGE",
        "INFOR",
    }
)
CATEGORIAS = frozenset(
    {
        "ERP",
        "CRM",
        "CLOUD_INFRA",
        "CIBERSEGURIDAD",
        "DATOS_IA",
        "DESARROLLO",
        "GIS",
        "SANIDAD_DIGITAL",
        "ADMIN_ELECTRONICA",
    }
)

_GOLDEN = Path(__file__).parent / "fixtures" / "golden_set_tech.jsonl"


@pytest.fixture(autouse=True)
def _desde_la_semilla(monkeypatch: pytest.MonkeyPatch) -> Iterator[None]:
    """Cada test ve la semilla, no la tabla, y parte de la caché vacía."""
    import services.tecnologias_diccionario as mod

    monkeypatch.setattr(mod, "_leer", lambda: (mod.semilla(), mod._hash_de(mod.semilla())))
    mod.invalidar()
    yield
    mod.invalidar()


def _detectadas(*textos: str) -> set[str]:
    _, por_tec = matches_technology(*textos)
    return set(por_tec)


# ── 1. Forma ────────────────────────────────────────────────────────────────


class TestForma:
    def test_los_labels_son_los_trece_fabricantes_y_las_nueve_categorias(self) -> None:
        assert set(TECH_LABELS) == FABRICANTES | CATEGORIAS
        assert {k for k, t in TECH_LABEL_TIPO.items() if t == "fabricante"} == FABRICANTES
        assert {k for k, t in TECH_LABEL_TIPO.items() if t == "categoria"} == CATEGORIAS

    def test_los_fabricantes_van_primero(self) -> None:
        """Los índices de los trece históricos no se mueven: el clasificador
        construye la matriz de labels por posición."""
        assert set(TECH_LABELS[: len(FABRICANTES)]) == FABRICANTES

    @pytest.mark.parametrize("label", TECH_LABELS)
    def test_cada_label_tiene_al_menos_cinco_keywords(self, label: str) -> None:
        assert len(TECHNOLOGY_KEYWORDS[label]) >= 5, label

    @pytest.mark.parametrize("label", TECH_LABELS)
    def test_las_keywords_van_en_minusculas_y_sin_espacios_sobrantes(self, label: str) -> None:
        for kw in TECHNOLOGY_KEYWORDS[label]:
            assert kw == kw.strip().lower(), (label, kw)
            assert kw, label

    @pytest.mark.parametrize("label", TECH_LABELS)
    def test_sin_duplicados_dentro_del_label(self, label: str) -> None:
        kws = TECHNOLOGY_KEYWORDS[label]
        assert len(kws) == len(set(kws)), sorted({k for k in kws if kws.count(k) > 1})

    def test_sin_duplicados_entre_labels_salvo_los_intencionales(self) -> None:
        duenos: dict[str, set[str]] = {}
        for label, kws in TECHNOLOGY_KEYWORDS.items():
            for kw in kws:
                duenos.setdefault(kw.casefold(), set()).add(label)
        compartidas = {(kw, frozenset(labels)) for kw, labels in duenos.items() if len(labels) > 1}
        assert compartidas == set(DUPLICADOS_INTENCIONALES)

    def test_los_tres_mapas_declaran_los_mismos_labels(self) -> None:
        assert set(TECH_CATEGORIAS) == set(TECH_LABELS) == set(TECH_LABEL_TIPO)

    def test_toda_keyword_compila_con_limites_de_palabra(self) -> None:
        """Toda keyword tiene que poder casar consigo misma.

        Se compila por `config.keywords.patron_de_keywords`, que es el mismo
        camino que usa `services.tecnologias_diccionario.patrones`: probar con
        una copia del patrón dejaría pasar justo la clase de fallo que este test
        encontró —`.net` en el diccionario desde el primer día, sin clasificar
        nada, porque `\\b` antes de un punto no casa tras un espacio—.
        """
        for label, kws in TECHNOLOGY_KEYWORDS.items():
            patron = patron_de_keywords(kws)
            for kw in kws:
                assert patron.search(f"objeto: {kw}."), (label, kw)


# ── 2. Consumidores ─────────────────────────────────────────────────────────


class TestConsumidores:
    def test_la_etiqueta_legible_se_deriva_del_unico_mapa(self) -> None:
        from services.classification import TECHNOLOGY_LABELS, tecnologia_label

        assert TECHNOLOGY_LABELS == TECH_CATEGORIAS
        assert tecnologia_label("GIS") == "GIS y geoinformación"
        assert tecnologia_label("SAP") == "SAP"
        assert tecnologia_label("MICROSOFT") == "Microsoft Dynamics / Azure"

    def test_la_semilla_lleva_las_categorias(self) -> None:
        from services.tecnologias_diccionario import semilla

        assert set(semilla()) == set(TECH_LABELS)

    def test_los_ajustes_de_organizacion_ofrecen_las_categorias(self) -> None:
        from services.organizations import _tecnologias_disponibles

        assert set(_tecnologias_disponibles()) >= CATEGORIAS

    def test_el_vocabulario_cerrado_del_llm_las_incluye_y_sigue_cabiendo(self) -> None:
        from services.llm_tech_labeling import build_question

        pregunta = build_question()
        for label in TECH_LABELS:
            assert label in pregunta
        assert len(pregunta) <= 2000

    def test_el_clasificador_nace_con_las_categorias_en_tier_rules(self) -> None:
        """Sin positivos no hay modelo: la categoría clasifica por keywords con
        su umbral propio, y no tira el resto."""
        from scraper.tech_classifier import TechnologyClassifier

        clf = TechnologyClassifier()
        assert clf.labels == TECH_LABELS
        assert set(clf._fallback_keywords) >= CATEGORIAS
        clf._trained = True  # sin entrenar: todo label cae al tier rules
        salida = clf.predict_one("Servicio de SOC 24x7 e implantación de un SIEM corporativo")
        assert "CIBERSEGURIDAD" in salida["predicted"]
        assert salida["principal"] == "CIBERSEGURIDAD"

    def test_el_tier_rules_respeta_limites_de_palabra(self) -> None:
        """«gis» no está en «registro» ni «erp» en «interpretación»: con las
        categorías el tier rules es casi todo acrónimos cortos."""
        from scraper.ml_pipeline import _keyword_fallback_score

        assert _keyword_fallback_score("registro de interpretación", ["gis", "erp"]) == 0.0
        assert _keyword_fallback_score("Implantación de un ERP", ["gis", "erp"]) == 0.5
        assert _keyword_fallback_score("Implantación de SAP S/4HANA", ["sap", "s/4hana"]) == 1.0

    def test_el_gating_de_ingesta_no_cambia(self) -> None:
        """Añadir labels al diccionario no los convierte en criterio de
        aceptación: eso lo decide `ML_TECH_GATING_PRACTICES`."""
        from config import settings

        assert not (set(settings.ML_TECH_GATING_PRACTICES) & CATEGORIAS)


# ── 3. Versión ──────────────────────────────────────────────────────────────


class TestVersion:
    def test_anadir_una_keyword_a_la_semilla_cambia_el_hash(self) -> None:
        """`filter_version` es el hash del contenido: la resiembra del
        2026-09-14 corta la serie sola, sin contador que tocar."""
        import services.tecnologias_diccionario as mod

        base = mod.semilla()
        con_una_mas = {k: list(v) for k, v in base.items()}
        con_una_mas["GIS"].append("visor de mapas")
        assert mod._hash_de(base) != mod._hash_de(con_una_mas)

    def test_la_version_servida_es_la_de_la_semilla_cuando_no_hay_tabla(self) -> None:
        import services.tecnologias_diccionario as mod

        assert mod.version() == mod._hash_de(mod.semilla())


# ── 4. Detección en lenguas cooficiales ──────────────────────────────────────

TITULOS_CATALAN: list[tuple[str, set[str]]] = [
    (
        "Servei de desenvolupament de programari a mida per a la gestió d'expedients "
        "de l'Ajuntament",
        {"DESARROLLO", "ADMIN_ELECTRONICA"},
    ),
    (
        "Contracte de serveis de ciberseguretat i centre d'operacions de seguretat (SOC) "
        "per a la Generalitat de Catalunya",
        {"CIBERSEGURIDAD"},
    ),
    (
        "Implantació de la seu electrònica i el registre electrònic del Consell Comarcal",
        {"ADMIN_ELECTRONICA"},
    ),
    (
        "Subministrament de serveis al núvol i còpies de seguretat per als sistemes corporatius",
        {"CLOUD_INFRA"},
    ),
    (
        "Plataforma d'intel·ligència artificial i analítica de dades per a l'atenció ciutadana",
        {"DATOS_IA"},
    ),
    (
        "Manteniment evolutiu i correctiu de l'aplicació web de gestió tributària",
        {"DESARROLLO"},
    ),
    (
        "Sistema d'informació geogràfica corporatiu i visor cartogràfic municipal",
        {"GIS"},
    ),
    (
        "Implantació de la història clínica electrònica compartida i la recepta electrònica",
        {"SANIDAD_DIGITAL"},
    ),
]

TITULOS_EUSKERA: list[tuple[str, set[str]]] = [
    (
        "Udalaren egoitza elektronikoa eta erregistro elektronikoa ezartzeko zerbitzua",
        {"ADMIN_ELECTRONICA"},
    ),
    (
        "Zibersegurtasun zerbitzuak eta segurtasun auditoretza Eusko Jaurlaritzarentzat",
        {"CIBERSEGURIDAD"},
    ),
    (
        "Aplikazioen garapena eta mantentze ebolutiboa udal kudeaketarako",
        {"DESARROLLO"},
    ),
    (
        "Hodeiko zerbitzuak eta segurtasun kopiak kontratatzea",
        {"CLOUD_INFRA"},
    ),
    (
        "Adimen artifiziala eta datuen analitika osasun sistemarako",
        {"DATOS_IA"},
    ),
    (
        "Historia kliniko elektronikoa eta errezeta elektronikoa integratzeko zerbitzua",
        {"SANIDAD_DIGITAL"},
    ),
    (
        "Informazio geografikoko sistema korporatiboa eta geoportala",
        {"GIS"},
    ),
    (
        "Kudeaketa ekonomiko-finantzarioa eta aurrekontu kontabilitatea kudeatzeko sistema",
        {"ERP"},
    ),
]

TITULOS_GALEGO: list[tuple[str, set[str]]] = [
    (
        "Servizo de desenvolvemento de software á medida para a Xunta de Galicia",
        {"DESARROLLO"},
    ),
    (
        "Contratación de servizos de ciberseguridade e auditoría de seguridade",
        {"CIBERSEGURIDAD"},
    ),
    (
        "Implantación da sede electrónica e do rexistro electrónico do Concello",
        {"ADMIN_ELECTRONICA"},
    ),
    (
        "Subministración de servizos na nube e copias de seguranza",
        {"CLOUD_INFRA"},
    ),
    (
        "Plataforma de intelixencia artificial e analítica de datos para a administración",
        {"DATOS_IA"},
    ),
    (
        "Mantemento evolutivo e correctivo das aplicacións web corporativas",
        {"DESARROLLO"},
    ),
    (
        "Sistema de información xeográfica e cartografía dixital municipal",
        {"GIS"},
    ),
    (
        "Historia clínica electrónica e receita electrónica do Servizo Galego de Saúde",
        {"SANIDAD_DIGITAL"},
    ),
]

TITULOS_CASTELLANO: list[tuple[str, set[str]]] = [
    ("Implantación de un ERP para la gestión económico-financiera", {"ERP"}),
    ("Plataforma CRM de atención ciudadana", {"CRM"}),
    ("Servicios en la nube y copias de seguridad del CPD", {"CLOUD_INFRA"}),
    ("Adecuación al ENS y auditoría de seguridad de los sistemas", {"CIBERSEGURIDAD"}),
    ("Cuadro de mando e inteligencia artificial para la gestión del agua", {"DATOS_IA"}),
    ("Mantenimiento evolutivo de la aplicación web de subvenciones", {"DESARROLLO"}),
    ("Sistema de información geográfica y geoportal municipal", {"GIS"}),
    ("Historia clínica electrónica y receta electrónica", {"SANIDAD_DIGITAL"}),
    ("Sede electrónica, registro electrónico y gestor de expedientes", {"ADMIN_ELECTRONICA"}),
]


class TestDeteccionRegional:
    @pytest.mark.parametrize(("titulo", "esperadas"), TITULOS_CATALAN)
    def test_catalan(self, titulo: str, esperadas: set[str]) -> None:
        assert esperadas <= _detectadas(titulo), titulo

    @pytest.mark.parametrize(("titulo", "esperadas"), TITULOS_EUSKERA)
    def test_euskera(self, titulo: str, esperadas: set[str]) -> None:
        assert esperadas <= _detectadas(titulo), titulo

    @pytest.mark.parametrize(("titulo", "esperadas"), TITULOS_GALEGO)
    def test_gallego(self, titulo: str, esperadas: set[str]) -> None:
        assert esperadas <= _detectadas(titulo), titulo

    @pytest.mark.parametrize(("titulo", "esperadas"), TITULOS_CASTELLANO)
    def test_castellano(self, titulo: str, esperadas: set[str]) -> None:
        assert esperadas <= _detectadas(titulo), titulo

    def test_los_titulos_regionales_no_disparan_ningun_fabricante(self) -> None:
        """Ninguno nombra un producto: si un fabricante casa, es un falso
        positivo del vocabulario nuevo."""
        for titulo, _ in TITULOS_CATALAN + TITULOS_EUSKERA + TITULOS_GALEGO:
            assert not (_detectadas(titulo) & FABRICANTES), titulo

    @pytest.mark.parametrize(
        "texto",
        [
            "Registro de la interpretación de las asociaciones en la capital",
            "Suministro de contenedores de residuos y servicio de limpieza",
            "Consultar las bases en la página web del ayuntamiento",
            "Servicio de teleasistencia domiciliaria para personas mayores",
        ],
    )
    def test_palabras_sueltas_no_disparan_categorias(self, texto: str) -> None:
        """Lo que motivó preferir sintagmas: «gis» en «registro», «api» en
        «capital», «contenedores» de basura, «página web» en cualquier
        descripción, «teleasistencia» que es servicio social."""
        assert not (_detectadas(texto) & CATEGORIAS), texto


# ── 5. Los fabricantes siguen detectando lo mismo ────────────────────────────


def _patrones_solo_fabricantes() -> dict[str, re.Pattern[str]]:
    return {
        tec: patron_de_keywords(kws)
        for tec, kws in TECHNOLOGY_KEYWORDS.items()
        if TECH_LABEL_TIPO[tec] == "fabricante"
    }


def _golden_textos() -> list[tuple[str, str, str]]:
    filas = []
    for linea in _GOLDEN.read_text(encoding="utf-8").splitlines():
        # Mismo criterio que `services.ml.eval_tech.load_golden_tech_set`:
        # líneas vacías y comentarios `#` se ignoran.
        if not linea.strip() or linea.lstrip().startswith("#"):
            continue
        fila = json.loads(linea)
        filas.append(
            (str(fila["id"]), str(fila.get("titulo") or ""), str(fila.get("descripcion") or ""))
        )
    return filas


class TestFabricantesIntactos:
    def test_hay_golden_set(self) -> None:
        assert len(_golden_textos()) > 20

    @pytest.mark.parametrize(("id_", "titulo", "descripcion"), _golden_textos())
    def test_las_categorias_no_alteran_lo_que_ven_los_fabricantes(
        self, id_: str, titulo: str, descripcion: str
    ) -> None:
        """Sobre el golden set (`tests/fixtures/golden_set_tech.jsonl`), los
        fabricantes que detecta el diccionario completo son exactamente los que
        detectaría el diccionario de solo fabricantes."""
        solo_fabricantes = {
            tec
            for tec, patron in _patrones_solo_fabricantes().items()
            if patron.search(titulo) or patron.search(descripcion)
        }
        assert _detectadas(titulo, descripcion) & FABRICANTES == solo_fabricantes, id_

    @pytest.mark.parametrize(
        ("titulo", "fabricante"),
        [
            ("Mantenimiento SAP S/4HANA del Ministerio", "SAP"),
            ("Implantación de Salesforce Service Cloud", "SALESFORCE"),
            ("Licencias Oracle Database y soporte", "ORACLE"),
            ("Migración a Microsoft Dynamics 365", "MICROSOFT"),
            ("Soporte de ServiceNow ITSM", "SERVICENOW"),
            ("Mantenimiento de Meta4 PeopleNet", "META4"),
        ],
    )
    def test_los_fabricantes_siguen_casando(self, titulo: str, fabricante: str) -> None:
        assert fabricante in _detectadas(titulo)
