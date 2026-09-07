"""C5.6 / D28 — el diccionario de tecnologías deja de ser un deploy.

Sin BD: se ejercita la semilla, el respaldo, la huella y las reglas que viven en
el código. Lo que necesita Postgres —la tabla, el sembrado, el impacto— queda
cubierto por los tests de integración.
"""

from __future__ import annotations

import inspect
from unittest.mock import patch

import pytest

pytestmark = pytest.mark.unit


@pytest.fixture(autouse=True)
def _sin_cache() -> object:
    """El diccionario se cachea en memoria: sin limpiar, el orden decide."""
    from services.tech_dictionary import invalidar

    invalidar()
    yield
    invalidar()


class TestDeDondeSaleElDiccionario:
    def test_sin_tabla_manda_la_semilla(self) -> None:
        """Un diccionario vacío no es «no filtres nada»: es «no persistas nada»,
        y esa no puede ser la respuesta a una caída de BD."""
        from services.tech_dictionary import semilla, vigente

        with patch("services.tech_dictionary._desde_bd", return_value=None):
            assert vigente(refrescar=True) == semilla()

    def test_con_tabla_manda_la_tabla(self) -> None:
        """Es lo que hace que editar no requiera desplegar."""
        from services.tech_dictionary import vigente

        propio = {"SAP": ["sap", "hcm cloud"]}
        with patch("services.tech_dictionary._desde_bd", return_value=propio):
            assert vigente(refrescar=True) == propio

    def test_el_origen_se_puede_consultar(self) -> None:
        """Un panel que deja editar sin decir que se está aplicando la semilla
        hace perder una tarde a quien no entiende por qué su cambio no hace nada."""
        from services.tech_dictionary import origen, vigente

        with patch("services.tech_dictionary._desde_bd", return_value={"SAP": ["sap"]}):
            vigente(refrescar=True)
            assert origen() == "bd"
        with patch("services.tech_dictionary._desde_bd", return_value=None):
            vigente(refrescar=True)
            assert origen() == "semilla"


class TestSemillaYTabla:
    def test_la_semilla_y_la_tabla_coinciden_en_un_arranque_limpio(self) -> None:
        """Aceptación de C5.6: sembrar deja la tabla igual que el código.

        Se comprueba sobre el contrato del repositorio —qué filas se insertan—
        porque lo que importa es que no se pierda ni se invente ninguna, y eso
        no necesita una base para verificarse.
        """
        from services.tech_dictionary import sembrar_si_vacio, semilla

        insertadas: list[tuple[str, str]] = []

        class _RepoFalso:
            def sembrar(self, diccionario: dict[str, list[str]]) -> int:
                insertadas.extend((t, k) for t, keywords in diccionario.items() for k in keywords)
                return len(insertadas)

        with patch("db.repositories.tecnologias_keywords.TecnologiaKeywordRepository", _RepoFalso):
            sembrar_si_vacio()

        esperadas = {(t, k) for t, kws in semilla().items() for k in kws}
        assert set(insertadas) == esperadas
        assert len(insertadas) == len(esperadas), "la semilla no debe traer duplicados"

    def test_la_semilla_no_resucita_lo_retirado(self) -> None:
        """Si pudiera, cada despliegue desharía las decisiones del equipo."""
        import db.repositories.tecnologias_keywords as mod

        fuente = inspect.getsource(mod.TecnologiaKeywordRepository.sembrar)
        # Sólo la sentencia: el docstring nombra `DO UPDATE` para explicar por
        # qué NO se usa, y buscarlo en el módulo entero mediría el comentario.
        sentencia = fuente[fuente.index("INSERT INTO tecnologias_keywords") :]
        assert "ON CONFLICT DO NOTHING" in sentencia
        assert "DO UPDATE" not in sentencia


class TestHuellaYLinaje:
    def test_reordenar_no_cambia_la_version(self) -> None:
        """Un `filter_version` que cambia sin que cambie el filtro rompe la
        comparación de series históricas."""
        from services.tech_dictionary import huella

        a = huella({"SAP": ["sap", "abap"], "ORACLE": ["oracle"]})
        b = huella({"ORACLE": ["oracle"], "SAP": ["ABAP", "Sap"]})

        assert a == b

    def test_una_keyword_nueva_si_cambia_la_version(self) -> None:
        from services.tech_dictionary import huella

        antes = huella({"SAP": ["sap"]})
        despues = huella({"SAP": ["sap", "hcm cloud"]})

        assert antes != despues

    def test_filter_version_sigue_al_diccionario_efectivo(self) -> None:
        """Si hasheara la semilla, dos corpus filtrados con diccionarios
        distintos llevarían la misma versión."""
        from scraper.lineage import current_filter_version
        from services.tech_dictionary import invalidar

        with patch("services.tech_dictionary._desde_bd", return_value={"SAP": ["sap"]}):
            uno = current_filter_version()
        # La caché tiene TTL de 60 s **a propósito**: dentro de una pasada de
        # ingesta, el filtro y la versión que se estampa tienen que ver el mismo
        # diccionario, o una fila se filtraría con A y quedaría marcada como B.
        # Aquí se fuerza el cambio de versión como lo haría una edición real.
        invalidar()
        with patch("services.tech_dictionary._desde_bd", return_value={"SAP": ["sap", "s/4hana"]}):
            otro = current_filter_version()

        assert uno != otro
        assert uno.startswith("keywords-")


class TestFiltroDinamico:
    def test_el_filtro_aplica_el_diccionario_de_la_tabla(self) -> None:
        from scraper.filters import matches_technology

        with patch("services.tech_dictionary._desde_bd", return_value={"WORKDAY": ["hcm cloud"]}):
            _, encontrado = matches_technology("Servicio de HCM Cloud para RRHH")

        assert encontrado == {"WORKDAY": ["hcm cloud"]}

    def test_sigue_respetando_los_limites_de_palabra(self) -> None:
        """Sin los límites de palabra, «sap» casaría dentro de «desaparecer» y
        el corpus se llenaría de expedientes que no son."""
        from scraper.filters import matches_sap

        with patch("services.tech_dictionary._desde_bd", return_value={"SAP": ["sap"]}):
            assert matches_sap("el problema va a desaparecer") == (False, [])
            assert matches_sap("mantenimiento SAP")[0] is True

    def test_los_patrones_se_compilan_una_vez_por_version(self) -> None:
        """Compilar seis regex por aviso sería absurdo en el camino de ingesta."""
        import scraper.filters as mod

        fuente = inspect.getsource(mod._patrones)
        assert "_PATRONES_POR_HUELLA" in fuente
        assert "huella(diccionario)" in fuente


class TestEdicion:
    def test_el_cambio_queda_auditado_con_el_delta(self) -> None:
        """«Se añadió *hcm cloud*» no explica nada seis meses después; «+38
        expedientes en 90 días» sí."""
        import services.tech_dictionary as mod

        fuente = inspect.getsource(mod.guardar_keyword)
        assert "log_event(" in fuente
        assert '"impacto_90d": impacto' in fuente
        assert '"filter_version": version_nueva' in fuente

    def test_editar_invalida_la_cache(self) -> None:
        import services.tech_dictionary as mod

        assert "invalidar()" in inspect.getsource(mod.guardar_keyword)

    def test_retirar_no_borra(self) -> None:
        """Una keyword retirada explica los expedientes que entraron por ella."""
        import db.repositories.tecnologias_keywords as mod

        assert "DELETE FROM tecnologias_keywords" not in inspect.getsource(mod)

    def test_las_rutas_existen(self) -> None:
        from api.app import app

        rutas = {r.path for r in app.routes if hasattr(r, "path")}
        assert "/api/v1/tecnologias" in rutas
        assert "/api/v1/tecnologias/impacto" in rutas
        assert "/api/v1/tecnologias/keywords" in rutas

    def test_escribir_es_solo_de_admin(self) -> None:
        """Cambia el criterio con el que entra el dato de todo el mundo."""
        import api.routes.tecnologias as mod

        assert "require_admin" in inspect.getsource(mod.put_keyword)

    def test_el_impacto_separa_lo_nuevo_de_lo_ya_etiquetado(self) -> None:
        """Los que ya tienen tecnología no son ganancia."""
        import db.repositories.tecnologias_keywords as mod

        fuente = inspect.getsource(mod.TecnologiaKeywordRepository.impacto)
        assert "ya_etiquetados" in fuente and "nuevos" in fuente


# ---------------------------------------------------------------------------
# Diagnóstico de la ficha: por qué falla, medido contra producción (2026-09-07)
# ---------------------------------------------------------------------------


class TestPorQueFallaLaFicha:
    """Un stream vacío y una respuesta en prosa no se arreglan igual.

    Medido contra producción el 2026-09-07: 586 fichas, **todas** en `failed`.
    376 son históricas (el tope de 2000 caracteres, corregido el 2026-08-31 con
    el límite interno) y **203 siguen ocurriendo hoy** con `tender-facts-v4`,
    todas con el mismo texto: «El extractor no devolvió un objeto JSON». Con ese
    mensaje no se puede saber si el proveedor no contestó o si contestó en
    prosa, que son dos causas con dos arreglos distintos.
    """

    def test_un_stream_vacio_no_se_confunde_con_una_respuesta_en_prosa(self) -> None:
        from llm.json_utils import RespuestaVacia, extract_json_object

        with pytest.raises(RespuestaVacia, match="stream vacío"):
            extract_json_object("")
        with pytest.raises(RespuestaVacia):
            extract_json_object("   \n  ")

    def test_una_respuesta_sin_json_dice_por_donde_empieza(self) -> None:
        """Sin el extracto, «no devolvió JSON» obliga a reproducirlo para verlo."""
        from llm.json_utils import extract_json_object

        with pytest.raises(ValueError, match="Claro, aquí"):
            extract_json_object("Claro, aquí tienes la ficha del pliego:")

    def test_el_json_fenced_sigue_funcionando(self) -> None:
        from llm.json_utils import extract_json_object

        assert extract_json_object('```json\n{"a": 1}\n```') == {"a": 1}

    def test_el_fallo_de_la_ficha_anota_modelo_y_presupuesto(self) -> None:
        """Sin eso hay que ir a correlacionar con producción para saber la causa."""
        import services.rag.fact_sheet as mod

        fuente = inspect.getsource(mod)
        assert "except RespuestaVacia as exc:" in fuente
        assert "modelo={model} max_tokens=3500" in fuente
