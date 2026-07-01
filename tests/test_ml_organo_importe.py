"""Tests de features estructurales en _augment_text: importe fino + token de órgano."""

from __future__ import annotations

from scraper.ml_pipeline import _augment_text


class TestImporteFineBucket:
    def test_emits_coarse_and_fine_buckets(self) -> None:
        out = _augment_text("servicio", importe=150_000)
        # 150k€ → log10 ≈ 5.18 → rango M (100k-1M) + bucket fino IMP_52.
        assert "IMPORTE_M" in out
        assert "IMP_52" in out

    def test_fine_bucket_distinguishes_within_coarse_range(self) -> None:
        # Dos importes dentro del mismo rango grueso (M) pero distinto bucket fino.
        low = _augment_text("x", importe=120_000)  # log10 ≈ 5.08 → IMP_51
        high = _augment_text("x", importe=900_000)  # log10 ≈ 5.95 → IMP_60
        assert "IMPORTE_M" in low and "IMPORTE_M" in high
        low_tokens = {t for t in low.split() if t.startswith("IMP_")}
        high_tokens = {t for t in high.split() if t.startswith("IMP_")}
        assert low_tokens != high_tokens

    def test_no_importe_no_token(self) -> None:
        out = _augment_text("servicio", importe=None)
        assert "IMP_" not in out
        assert "IMPORTE_" not in out


class TestOrganoToken:
    def test_emits_stable_token_when_provided(self) -> None:
        out = _augment_text("servicio", organo="Ayuntamiento de Madrid")
        org_tokens = [t for t in out.split() if t.startswith("ORG_")]
        assert org_tokens, "Debe emitir token de órgano"
        # Determinista: misma entrada → mismo bucket.
        out2 = _augment_text("otro texto", organo="Ayuntamiento de Madrid")
        assert {t for t in out2.split() if t.startswith("ORG_")} == set(org_tokens)

    def test_normalization_ignores_accents_and_case(self) -> None:
        a = {
            t
            for t in _augment_text("x", organo="Diputación Provincial").split()
            if t.startswith("ORG_")
        }
        b = {
            t
            for t in _augment_text("x", organo="diputacion  provincial").split()
            if t.startswith("ORG_")
        }
        assert a == b

    def test_different_organo_different_bucket(self) -> None:
        a = {
            t
            for t in _augment_text("x", organo="Ayuntamiento de Madrid").split()
            if t.startswith("ORG_")
        }
        b = {
            t
            for t in _augment_text("x", organo="Generalitat de Catalunya").split()
            if t.startswith("ORG_")
        }
        assert a != b

    def test_no_organo_no_token(self) -> None:
        out = _augment_text("servicio", organo=None)
        assert "ORG_" not in out

    def test_build_dataset_organo_gated_off_by_default(self, monkeypatch) -> None:
        # Por defecto (ML_USE_ORGANO_FEATURE=False) no debe emitir tokens de órgano.
        import pandas as pd

        from config import settings
        from scraper.ml_pipeline import _build_dataset

        monkeypatch.setattr(settings, "ML_USE_ORGANO_FEATURE", False)
        rows = [
            {
                "titulo": f"SAP {i}",
                "descripcion": "ERP",
                "raw_keywords": "SAP",
                "cpv": "72000000",
                "organo_contratacion": "Ayuntamiento X",
            }
            for i in range(10)
        ]
        rows += [
            {
                "titulo": f"Obra {i}",
                "descripcion": "reforma",
                "raw_keywords": None,
                "cpv": "45000000",
                "organo_contratacion": "Ayuntamiento Y",
            }
            for i in range(10)
        ]
        texts, _labels = _build_dataset(pd.DataFrame(rows))
        assert all("ORG_" not in t for t in texts)
