"""Tests para dashboard/normalize.py — normalización de empresas y NIFs."""

from __future__ import annotations

from services.normalization import normalize_company, normalize_nif, parse_ute_members


class TestNormalizeCompany:
    # ── Eliminación de sufijos societarios ──────────────────────────────
    def test_elimina_sa(self):
        assert normalize_company("Empresa Ejemplo, S.A.") == "EMPRESA EJEMPLO"

    def test_elimina_sl(self):
        assert normalize_company("Tech Solutions S.L.") == "TECH SOLUTIONS"

    def test_elimina_sau(self):
        assert normalize_company("Holding Group, S.A.U.") == "HOLDING GROUP"

    def test_elimina_slu(self):
        assert normalize_company("Digital S.L.U.") == "DIGITAL"

    def test_elimina_sociedad_anonima(self):
        result = normalize_company("Constructora SOCIEDAD ANÓNIMA")
        assert "SOCIEDAD" not in result
        assert "ANONIMA" not in result

    def test_elimina_gmbh(self):
        assert normalize_company("SAP Deutschland GmbH") == "SAP DEUTSCHLAND"

    def test_elimina_ltd(self):
        assert normalize_company("Oracle Ltd") == "ORACLE"

    # ── Normalización de tildes y mayúsculas ─────────────────────────────
    def test_mayusculas(self):
        result = normalize_company("empresa ejemplo")
        assert result == result.upper()

    def test_sin_tildes(self):
        result = normalize_company("Información y Tecnología")
        assert "Á" not in result
        assert "ó" not in result

    # ── Deduplicación: misma empresa, variantes distintas ───────────────
    def test_misma_empresa_variantes(self):
        assert normalize_company("IBM España, S.A.") == normalize_company("IBM ESPAÑA SA")

    def test_misma_empresa_con_y_sin_puntos(self):
        assert normalize_company("Accenture S.L.") == normalize_company("Accenture SL")

    # ── Entradas inválidas ───────────────────────────────────────────────
    def test_none_devuelve_none(self):
        assert normalize_company(None) is None

    def test_string_vacio_devuelve_none(self):
        assert normalize_company("") is None

    def test_solo_sufijo_devuelve_none(self):
        # Una empresa que es solo "S.A." debería resultar en None o vacío
        result = normalize_company("S.A.")
        assert result is None or result == ""

    def test_no_string_devuelve_none(self):
        assert normalize_company(123) is None  # type: ignore[arg-type]


class TestNormalizeNif:
    # ── Normalización básica ─────────────────────────────────────────────
    def test_elimina_espacios(self):
        assert normalize_nif("A 12345678") == "A12345678"  # pragma: allowlist secret

    def test_elimina_guiones(self):
        assert normalize_nif("A-12345678") == "A12345678"  # pragma: allowlist secret

    def test_elimina_puntos(self):
        assert normalize_nif("A.12345678") == "A12345678"  # pragma: allowlist secret

    def test_mayusculas(self):
        assert normalize_nif("a12345678") == "A12345678"  # pragma: allowlist secret

    def test_combina_transformaciones(self):
        assert normalize_nif(" a-123.456-78 ") == "A12345678"  # pragma: allowlist secret

    # ── Consistencia: mismos NIF, distintos formatos ─────────────────────
    def test_mismo_nif_formatos_distintos(self):
        assert normalize_nif("B-12345678") == normalize_nif(
            "B 12345678"
        )  # pragma: allowlist secret

    # ── Entradas inválidas ───────────────────────────────────────────────
    def test_none_devuelve_none(self):
        assert normalize_nif(None) is None

    def test_vacio_devuelve_none(self):
        assert normalize_nif("") is None

    def test_solo_separadores_devuelve_none(self):
        assert normalize_nif("- . -") is None


class TestParseUteMembers:
    def test_no_es_ute(self):
        assert parse_ute_members("Empresa Ejemplo, S.A.") == []

    def test_none(self):
        assert parse_ute_members(None) == []

    def test_ute_dos_miembros_guion(self):
        assert parse_ute_members("UTE SEIDOR SOLUTIONS SL - SBS SEIDOR SL") == [
            "SEIDOR SOLUTIONS",
            "SBS SEIDOR",
        ]

    def test_ute_puntos(self):
        assert parse_ute_members("U.T.E. NTT DATA SPAIN, S.L.U. - NTT DATA SPAIN INFRA S.L.U.") == [
            "NTT DATA SPAIN",
            "NTT DATA SPAIN INFRA",
        ]

    def test_ute_compacto_guion(self):
        # Sin espacios alrededor del guion no se puede separar con seguridad
        # (podría ser un nombre tipo "Coca-Cola"); se devuelve como un único miembro.
        assert parse_ute_members("UTE ZEUS-EXETECO") == ["ZEUS EXETECO"]

    def test_ute_con_lote_paren(self):
        members = parse_ute_members("Ute Vass T4s (L5 Sda 25/2022)")
        assert members and all("(" not in m for m in members)

    def test_ute_y_separador(self):
        assert parse_ute_members("UTE Capgemini Y Babel") == ["CAPGEMINI", "BABEL"]

    def test_dedupe(self):
        assert parse_ute_members("UTE EMPRESA - EMPRESA SA") == ["EMPRESA"]


class TestFoldText:
    def test_strips_accents_and_case(self):
        from services.normalization import fold_text

        assert fold_text("Informática") == "informatica"
        assert fold_text("INFORMÁTICA") == fold_text("informatica")

    def test_enie(self):
        from services.normalization import fold_text

        assert fold_text("Señalización") == "senalizacion"

    def test_plain_ascii_unchanged(self):
        from services.normalization import fold_text

        assert fold_text("c++") == "c++"
