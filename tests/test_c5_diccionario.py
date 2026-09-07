"""El diccionario de tecnologías como dato (C5.6, D28).

`config/keywords.py` era código: añadir «SAP BTP» exigía commit, revisión, merge
y despliegue, para una lista de palabras que decide qué ve el producto entero.
"""

from __future__ import annotations

import inspect

import pytest


@pytest.fixture(autouse=True)
def _sin_cache():
    """Cada test parte de la caché vacía.

    El módulo cachea el diccionario 60 s a propósito (el scraper lo consulta
    cientos de miles de veces por pasada); sin limpiar entre tests, el primero
    decidiría lo que ven los demás.
    """
    from services.tecnologias_diccionario import invalidar

    invalidar()
    yield
    invalidar()


class TestFuenteVigente:
    """La tabla manda; la semilla es el suelo."""

    def test_sin_tabla_se_usa_la_semilla(self, monkeypatch) -> None:
        """Quedarse sin diccionario no degradaría el filtro: lo apagaría."""
        import services.tecnologias_diccionario as mod

        monkeypatch.setattr(mod, "_leer", lambda: (mod.semilla(), mod._hash_de(mod.semilla())))
        diccionario, _version = mod.vigente()
        assert diccionario == mod.semilla()
        assert "SAP" in diccionario

    def test_un_fallo_de_lectura_cae_a_la_semilla_y_no_revienta(self, monkeypatch) -> None:
        import db.repositories.tecnologias_keywords as repo_mod
        import services.tecnologias_diccionario as mod

        def _boom(self):
            raise RuntimeError("BD caída")

        monkeypatch.setattr(
            repo_mod.TecnologiasKeywordsRepository, "diccionario_activo", _boom, raising=True
        )
        diccionario, version = mod.vigente(forzar=True)
        assert diccionario == mod.semilla()
        assert version.startswith("keywords-")

    def test_la_tabla_gana_a_la_semilla(self, monkeypatch) -> None:
        import db.repositories.tecnologias_keywords as repo_mod
        import services.tecnologias_diccionario as mod

        monkeypatch.setattr(
            repo_mod.TecnologiasKeywordsRepository,
            "diccionario_activo",
            lambda self: {"SAP": ["sap s/4hana"]},
            raising=True,
        )
        diccionario, _ = mod.vigente(forzar=True)
        assert diccionario == {"SAP": ["sap s/4hana"]}


class TestVersion:
    """`filter_version` sigue siendo el hash del contenido."""

    def test_la_version_es_el_hash_del_contenido(self) -> None:
        import services.tecnologias_diccionario as mod

        uno = mod._hash_de({"SAP": ["sap"]})
        otro = mod._hash_de({"SAP": ["sap", "sap hana"]})
        assert uno.startswith("keywords-")
        assert uno != otro

    def test_el_orden_y_las_mayusculas_no_cambian_el_hash(self) -> None:
        """Dos formas de escribir lo mismo no pueden invalidar el linaje entero."""
        import services.tecnologias_diccionario as mod

        assert mod._hash_de({"SAP": ["SAP", "Sap Hana"]}) == mod._hash_de(
            {"SAP": ["sap hana", "sap"]}
        )

    def test_la_regla_de_universo_entra_en_el_hash(self) -> None:
        """Las series de antes y después de `cpv_ti_universe` no son comparables."""
        import services.tecnologias_diccionario as mod

        assert "__universo__" in inspect.getsource(mod._hash_de)

    def test_current_filter_version_lee_el_vigente(self, monkeypatch) -> None:
        """El acoplamiento que hace que editar desde /ops cambie el linaje."""
        import db.repositories.tecnologias_keywords as repo_mod
        from scraper.lineage import current_filter_version

        monkeypatch.setattr(
            repo_mod.TecnologiasKeywordsRepository,
            "diccionario_activo",
            lambda self: {"SAP": ["sap"]},
            raising=True,
        )
        from services.tecnologias_diccionario import invalidar

        invalidar()
        con_una = current_filter_version()

        monkeypatch.setattr(
            repo_mod.TecnologiasKeywordsRepository,
            "diccionario_activo",
            lambda self: {"SAP": ["sap", "sap btp"]},
            raising=True,
        )
        invalidar()
        assert current_filter_version() != con_una

    def test_el_calculo_del_hash_vive_en_un_solo_sitio(self) -> None:
        """Tenerlo en dos lo dejaría divergir sin que nada fallase."""
        from scraper.lineage import current_filter_version

        fuente = inspect.getsource(current_filter_version)
        assert "hashlib" not in fuente
        assert "from services.tecnologias_diccionario import version" in fuente


class TestPatrones:
    """Lo derivado se memoiza por versión, no por tiempo."""

    def test_los_patrones_respetan_limites_de_palabra(self, monkeypatch) -> None:
        """Sin `\\b`, «sap» casa dentro de «desaparecer»."""
        import db.repositories.tecnologias_keywords as repo_mod
        from services.tecnologias_diccionario import invalidar, patrones

        monkeypatch.setattr(
            repo_mod.TecnologiasKeywordsRepository,
            "diccionario_activo",
            lambda self: {"SAP": ["sap"]},
            raising=True,
        )
        invalidar()
        patron = patrones()["SAP"]
        assert patron.search("migración a SAP")
        assert not patron.search("van a desaparecer")

    def test_cambiar_el_diccionario_recompila(self, monkeypatch) -> None:
        import db.repositories.tecnologias_keywords as repo_mod
        from services.tecnologias_diccionario import invalidar, patrones

        monkeypatch.setattr(
            repo_mod.TecnologiasKeywordsRepository,
            "diccionario_activo",
            lambda self: {"SAP": ["sap"]},
            raising=True,
        )
        invalidar()
        assert "BTP" not in patrones()

        monkeypatch.setattr(
            repo_mod.TecnologiasKeywordsRepository,
            "diccionario_activo",
            lambda self: {"SAP": ["sap"], "BTP": ["sap btp"]},
            raising=True,
        )
        invalidar()
        assert "BTP" in patrones()

    def test_los_dos_consumidores_piden_al_mismo_sitio(self) -> None:
        """Antes cada uno compilaba los suyos; con la tabla podían divergir."""
        import scraper.filters as filtros
        import services.tech_signal as senal

        for modulo in (filtros, senal):
            fuente = inspect.getsource(modulo._tech_patterns)
            assert "from services.tecnologias_diccionario import patrones" in fuente

    def test_ya_no_hay_patrones_congelados_al_importar(self) -> None:
        """Un `dict` de nivel de módulo se quedaría con el diccionario del arranque."""
        import scraper.filters as filtros
        import services.tech_signal as senal

        assert not hasattr(filtros, "_TECH_PATTERNS")
        assert not hasattr(senal, "_TECH_PATTERNS")


class TestSemillaYTabla:
    """El criterio de aceptación: semilla y tabla coinciden en un arranque limpio."""

    def test_la_siembra_reproduce_la_semilla(self, monkeypatch) -> None:
        import db.repositories.tecnologias_keywords as repo_mod
        import services.tecnologias_diccionario as mod

        escritas: dict[str, list[str]] = {}

        def _sembrar(self, semilla):
            escritas.update({k: list(v) for k, v in semilla.items()})
            return sum(len(v) for v in semilla.values())

        monkeypatch.setattr(
            repo_mod.TecnologiasKeywordsRepository, "sembrar", _sembrar, raising=True
        )
        insertadas = mod.sembrar_desde_semilla()
        assert escritas == mod.semilla()
        assert insertadas == sum(len(v) for v in mod.semilla().values())

    def test_la_semilla_sigue_siendo_la_de_config(self) -> None:
        from config.keywords import TECHNOLOGY_KEYWORDS
        from services.tecnologias_diccionario import semilla

        assert semilla() == {t: list(k) for t, k in TECHNOLOGY_KEYWORDS.items()}

    def test_config_declara_que_es_semilla(self) -> None:
        """Sin decirlo, alguien añadiría una keyword ahí y esperaría que entrase."""
        from pathlib import Path

        texto = (Path(__file__).resolve().parent.parent / "config" / "keywords.py").read_text(
            encoding="utf-8"
        )
        assert "SEMILLA, no fuente de verdad" in texto

    def test_resembrar_no_reactiva_lo_desactivado(self) -> None:
        """Si lo hiciera, cada despliegue desharía una decisión del equipo."""
        from db.repositories.tecnologias_keywords import TecnologiasKeywordsRepository

        assert "DO NOTHING" in inspect.getsource(TecnologiasKeywordsRepository.sembrar)


class TestRetiradaYAuditoria:
    """Quitar una keyword es revisable, y cada cambio deja su delta."""

    def test_retirar_desactiva_y_no_borra(self) -> None:
        from db.repositories.tecnologias_keywords import TecnologiasKeywordsRepository

        # El cuerpo, no el docstring: el docstring explica justo por qué no hay
        # `DELETE`, así que buscarlo en la fuente entera siempre lo encontraría.
        cuerpo = inspect.getsource(TecnologiasKeywordsRepository.desactivar).split('"""')[-1]
        assert "SET activa = false" in cuerpo
        assert "DELETE" not in cuerpo

    def test_el_impacto_cuenta_solo_lo_que_aniade(self) -> None:
        """«SAP» aparece en miles que ya están dentro: ese número no decide nada."""
        from db.repositories.tecnologias_keywords import TecnologiasKeywordsRepository

        assert "tecnologia IS NULL" in inspect.getsource(TecnologiasKeywordsRepository.impacto)

    def test_el_impacto_se_mide_antes_de_escribir(self) -> None:
        """Después, la siguiente ingesta ya habría asignado tecnología."""
        import api.routes.tecnologias_keywords as mod

        fuente = inspect.getsource(mod.put_keyword)
        assert fuente.index("_repo.impacto") < fuente.index("_repo.upsert")

    def test_el_audit_log_lleva_el_delta_y_las_dos_versiones(self) -> None:
        import api.routes.tecnologias_keywords as mod

        fuente = inspect.getsource(mod.put_keyword)
        assert "expedientes_nuevos_estimados" in fuente
        assert "filter_version_antes" in fuente
        assert "filter_version_despues" in fuente

    def test_editar_exige_admin(self) -> None:
        import api.routes.tecnologias_keywords as mod

        for fn in (mod.put_keyword, mod.delete_keyword, mod.post_sembrar, mod.get_impacto):
            assert "require_admin" in inspect.getsource(fn)

    @pytest.mark.parametrize(
        "ruta",
        [
            "/api/v1/tecnologias/keywords",
            "/api/v1/tecnologias/keywords/impacto",
            "/api/v1/tecnologias/keywords/sembrar",
        ],
    )
    def test_las_rutas_existen(self, ruta: str) -> None:
        from api.app import app

        assert ruta in {r.path for r in app.routes if hasattr(r, "path")}

    def test_la_ruta_estatica_no_queda_ensombrecida(self) -> None:
        """`/impacto` y `/sembrar` cuelgan del mismo prefijo que el listado."""
        from api.app import app

        rutas = [getattr(r, "path", "") for r in app.routes]
        assert "/api/v1/tecnologias/keywords/impacto" in rutas
