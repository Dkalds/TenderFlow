"""Tests para services/classification — clasificadores de datos."""

from __future__ import annotations

from services.classification import (
    cpv_label,
    detect_modules,
    detect_project_type,
    estado_label,
    nuts_to_ccaa,
    tipo_contrato_label,
)


class TestNutsToCcaa:
    def test_codigo_nuts3_exacto(self):
        assert nuts_to_ccaa("ES300") == "Madrid"

    def test_codigo_nuts3_pais_vasco(self):
        assert nuts_to_ccaa("ES211") == "País Vasco"

    def test_codigo_nuts3_andalucia(self):
        assert nuts_to_ccaa("ES611") == "Andalucía"

    def test_codigo_en_minusculas(self):
        assert nuts_to_ccaa("es300") == "Madrid"

    def test_codigo_con_espacios(self):
        assert nuts_to_ccaa(" ES300 ") == "Madrid"

    def test_none_devuelve_none(self):
        assert nuts_to_ccaa(None) is None

    def test_codigo_inexistente_devuelve_none(self):
        assert nuts_to_ccaa("XX999") is None

    def test_string_vacio_devuelve_none(self):
        assert nuts_to_ccaa("") is None

    def test_todos_los_nuts3_conocidos_mapeados(self):
        from services.classification import NUTS3_TO_CCAA

        for code in NUTS3_TO_CCAA:
            assert nuts_to_ccaa(code) is not None


class TestDetectModules:
    def test_detecta_s4hana(self):
        mods = detect_modules("Migración S/4HANA al nuevo sistema")
        assert "S/4HANA" in mods

    def test_detecta_fiori(self):
        mods = detect_modules("Desarrollo Fiori para portal empleados")
        assert "Fiori/UI5" in mods

    def test_detecta_abap(self):
        mods = detect_modules("Consultoría ABAP especializada")
        assert "ABAP" in mods

    def test_detecta_modulo_fi(self):
        mods = detect_modules("Implantación SAP FI módulo financiero")
        assert "FI (Finanzas)" in mods

    def test_detecta_modulo_mm(self):
        mods = detect_modules("Soporte módulo SAP MM")
        assert "MM (Materiales)" in mods

    def test_detecta_successfactors(self):
        mods = detect_modules("Proyecto SuccessFactors RRHH")
        assert "SuccessFactors" in mods

    def test_texto_generico_sap_devuelve_sap_generico(self):
        mods = detect_modules("Mantenimiento SAP genérico")
        assert "SAP (genérico)" in mods

    def test_texto_vacio_devuelve_lista_vacia(self):
        assert detect_modules("") == []

    def test_none_devuelve_lista_vacia(self):
        assert detect_modules(None) == []

    def test_multiples_modulos_detectados(self):
        mods = detect_modules("SAP FI y SAP MM para gestión integral")
        assert "FI (Finanzas)" in mods
        assert "MM (Materiales)" in mods


class TestDetectProjectType:
    def test_detecta_mantenimiento(self):
        assert detect_project_type("Servicio de mantenimiento SAP") == "Mantenimiento"

    def test_detecta_soporte(self):
        assert detect_project_type("Servicio de soporte técnico SAP") == "Mantenimiento"

    def test_detecta_implantacion(self):
        assert detect_project_type("Implantación SAP S/4HANA") == "Implantación"

    def test_detecta_migracion(self):
        assert detect_project_type("Migración a SAP S/4HANA") == "Implantación"

    def test_detecta_licencias(self):
        assert detect_project_type("Suministro de licencias SAP") == "Licencias"

    def test_detecta_consultoria(self):
        assert detect_project_type("Consultoría SAP especializada") == "Consultoría"

    def test_detecta_desarrollo(self):
        assert detect_project_type("Desarrollo de programación ABAP") == "Desarrollo"

    def test_detecta_formacion(self):
        assert detect_project_type("Formación en SAP para empleados") == "Formación"

    def test_texto_sin_tipo_devuelve_sin_clasificar(self):
        assert detect_project_type("Proyecto SAP genérico sin más") == "Sin clasificar"

    def test_none_devuelve_sin_clasificar(self):
        assert detect_project_type(None) == "Sin clasificar"

    def test_vacio_devuelve_sin_clasificar(self):
        assert detect_project_type("") == "Sin clasificar"


class TestEstadoLabel:
    def test_pub(self):
        assert estado_label("PUB") == "Publicada"

    def test_res(self):
        assert estado_label("RES") == "Resuelta"

    def test_adj(self):
        assert estado_label("ADJ") == "Adjudicada"

    def test_codigo_desconocido_devuelve_codigo(self):
        assert estado_label("XYZ") == "XYZ"

    def test_none_devuelve_desconocido(self):
        assert estado_label(None) == "Desconocido"

    def test_con_espacios(self):
        assert estado_label(" PUB ") == "Publicada"


class TestCpvLabel:
    def test_codigo_exacto(self):
        label = cpv_label("72000000")
        assert "72000000" in label
        assert "TI" in label or "consultoría" in label.lower() or "Servicios" in label

    def test_codigo_none_devuelve_dash(self):
        assert cpv_label(None) == "—"

    def test_codigo_vacio_devuelve_dash(self):
        assert cpv_label("") == "—"

    def test_codigo_desconocido_devuelve_codigo(self):
        assert cpv_label("99999999") == "99999999"


class TestTipoContratoLabel:
    def test_servicios(self):
        assert tipo_contrato_label("2") == "Servicios"

    def test_obras(self):
        assert tipo_contrato_label("3") == "Obras"

    def test_none_devuelve_dash(self):
        assert tipo_contrato_label(None) == "—"

    def test_codigo_desconocido(self):
        result = tipo_contrato_label("99")
        assert "99" in result
