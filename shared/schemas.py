"""Esquemas pandera para validación de DataFrames en boundaries.

Define los contratos de datos entre capas. En prod se usa modo ``lazy``
(sólo columnas + dtypes); en dev/CI se valida estrictamente.

Uso:
    from shared.schemas import LicitacionSchema

    LicitacionSchema.validate(df, lazy=True)  # prod: sólo schema check
    LicitacionSchema.validate(df)             # dev: validación completa
"""

from __future__ import annotations

from typing import Any

import pandas as pd

try:
    import pandera as pa
    from pandera.typing import Series

    _PANDERA_AVAILABLE = True
except ImportError:
    _PANDERA_AVAILABLE = False


def _pandera_installed() -> bool:
    return _PANDERA_AVAILABLE


if _PANDERA_AVAILABLE:

    class LicitacionSchema(pa.DataFrameModel):
        """Schema del DataFrame base de licitaciones (post-enriquecimiento)."""

        id_externo: Series[str] = pa.Field(nullable=False)
        titulo: Series[str] = pa.Field(nullable=True)
        organo_contratacion: Series[str] = pa.Field(nullable=True)
        importe: Series[float] = pa.Field(nullable=True, ge=0)
        estado: Series[Any] = pa.Field(nullable=True)  # category
        fecha_publicacion: Series[Any] = pa.Field(nullable=True)  # datetime64
        ccaa: Series[Any] = pa.Field(nullable=True)  # category
        tecnologia: Series[str] = pa.Field(nullable=True)
        tipo_contrato: Series[Any] = pa.Field(nullable=True)  # category

        class Config:
            coerce = True
            strict = False  # allow extra columns

    class AdjudicacionSchema(pa.DataFrameModel):
        """Schema del DataFrame de adjudicaciones."""

        licitacion_id: Series[str] = pa.Field(nullable=False)
        nombre: Series[str] = pa.Field(nullable=True)
        importe_adjudicado: Series[float] = pa.Field(nullable=True, ge=0)
        fecha_adjudicacion: Series[Any] = pa.Field(nullable=True)

        class Config:
            coerce = True
            strict = False

    class KpiSnapshotSchema(pa.DataFrameModel):
        """Schema para datos pre-computados de KPI."""

        metric_name: Series[str] = pa.Field(nullable=False)
        metric_value: Series[float] = pa.Field(nullable=True)
        computed_at: Series[str] = pa.Field(nullable=False)

        class Config:
            coerce = True
            strict = False

else:
    # Stubs when pandera is not installed — validation is a no-op

    class _NoOpSchema:
        """Stub que no valida nada cuando pandera no está instalado."""

        @classmethod
        def validate(cls, df: pd.DataFrame, **kwargs: Any) -> pd.DataFrame:
            return df

    LicitacionSchema = _NoOpSchema  # type: ignore[assignment,misc]
    AdjudicacionSchema = _NoOpSchema  # type: ignore[assignment,misc]
    KpiSnapshotSchema = _NoOpSchema  # type: ignore[assignment,misc]


def validate_licitaciones(df: pd.DataFrame, *, lazy: bool = True) -> pd.DataFrame:
    """Valida el DataFrame de licitaciones contra el schema.

    Args:
        df: DataFrame a validar.
        lazy: Si True, sólo verifica columnas y dtypes (rápido, para prod).
              Si False, validación completa fila a fila (para dev/CI).
    """
    if not _PANDERA_AVAILABLE:
        return df
    return LicitacionSchema.validate(df, lazy=lazy)  # type: ignore[return-value]


def validate_adjudicaciones(df: pd.DataFrame, *, lazy: bool = True) -> pd.DataFrame:
    """Valida el DataFrame de adjudicaciones contra el schema."""
    if not _PANDERA_AVAILABLE:
        return df
    return AdjudicacionSchema.validate(df, lazy=lazy)  # type: ignore[return-value]
