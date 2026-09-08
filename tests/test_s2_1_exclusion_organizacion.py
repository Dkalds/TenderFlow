"""S2.1 — «contra quién» deja de contar a la propia organización.

`IdentidadFiscal.reconoce` existía y estaba probada desde #274, pero ningún
módulo de competencia la llamaba: el parámetro `excluir` de `sugerir_socios`
no lo alimentaba nadie y la lista de líderes del segmento —el «contra quién se
va»— no filtraba nada. Estos tests fijan las tres piezas del cableado:

1. la traducción identidad fiscal → clave analítica de empresa,
2. que esa clave sale de las sugerencias **y** de los líderes,
3. que sin identidad declarada no se excluye a nadie (y se dice).

Sin Postgres: se sustituyen `load_for_competitors` y el repositorio de
`organization_nifs`, que es todo lo que baja a la BD en esta cadena.
"""

from __future__ import annotations

from typing import Any
from unittest.mock import patch

import pandas as pd
import pytest

from services.competitive.socios import (
    claves_de_la_organizacion,
    socios_del_segmento,
    sugerir_socios,
)
from services.organizations import OrganizationAccessError
from services.pursuit_awards import IdentidadFiscal

_NIF_PROPIO = "B12345678"  # pragma: allowlist secret
_NIF_AJENO = "A87654321"  # pragma: allowlist secret

_PROPIA = IdentidadFiscal(nifs=frozenset({_NIF_PROPIO}))  # pragma: allowlist secret
_PROPIA_EN_MAESTRO = IdentidadFiscal(
    nifs=frozenset({_NIF_PROPIO}), empresa_ids=frozenset({41})
)  # pragma: allowlist secret

_CARGA = "services.competitive.socios.cargar_adjudicaciones_resueltas"


def _resueltas(filas: list[dict[str, Any]]) -> pd.DataFrame:
    """El shape que deja `cargar_adjudicaciones_resueltas`, con identidad."""
    base: dict[str, Any] = {
        "id": 0,
        "titulo": "Servicios SAP",
        "cpv": "72220000",
        "ccaa": "Madrid",
        "importe_adjudicado": 100_000.0,
        "empresa_key": "acme",
        "nombre_canonico": "ACME",
        "organo_contratacion": "Ayto A",
        "es_ute": 0,
        "es_pyme": 0,
        "_nif_key": None,
        "_empresa_id_key": None,
    }
    return pd.DataFrame([{**base, **fila} for fila in filas])


# ── La traducción que faltaba ──────────────────────────────────────────────


class TestClavesDeLaOrganizacion:
    def test_traduce_el_nif_declarado_a_la_clave_analitica(self) -> None:
        """La organización sabe su NIF; la lista de competidores usa otra clave."""
        df = _resueltas([{"id": i, "_nif_key": _NIF_PROPIO} for i in range(3)])
        assert claves_de_la_organizacion(df, _PROPIA) == {"acme"}

    def test_traduce_tambien_por_empresa_id_del_maestro(self) -> None:
        """El enlace NIF↔`empresa_id` es lo que el plan pide de S2.1."""
        df = _resueltas([{"id": 0, "_empresa_id_key": 41}])
        assert claves_de_la_organizacion(df, _PROPIA_EN_MAESTRO) == {"acme"}

    def test_basta_una_fila_del_grupo_con_nuestro_nif(self) -> None:
        """La agrupación junta UTEs y variantes: si una fila somos nosotros, lo es el grupo."""
        df = _resueltas(
            [
                {"id": 0, "_nif_key": _NIF_AJENO},
                {"id": 1, "_nif_key": _NIF_PROPIO},
            ]
        )
        assert claves_de_la_organizacion(df, _PROPIA) == {"acme"}

    def test_el_nif_publicado_se_normaliza_antes_de_comparar(self) -> None:
        df = _resueltas([{"id": 0, "_nif_key": "b-12345678"}])
        assert claves_de_la_organizacion(df, _PROPIA) == {"acme"}

    def test_sin_identidad_declarada_no_se_excluye_a_nadie(self) -> None:
        df = _resueltas([{"id": 0, "_nif_key": _NIF_PROPIO}])
        assert claves_de_la_organizacion(df, IdentidadFiscal()) == set()

    def test_las_ausencias_de_pandas_no_revientan_la_comparacion(self) -> None:
        """`_nif_key`/`_empresa_id_key` llegan como `NA`, no como `None`."""
        df = _resueltas([{"id": 0}, {"id": 1, "empresa_key": "otra"}])
        df["_nif_key"] = pd.Series([pd.NA, pd.NA], dtype="string")
        df["_empresa_id_key"] = pd.Series([pd.NA, pd.NA], dtype="Int64")
        assert claves_de_la_organizacion(df, _PROPIA_EN_MAESTRO) == set()

    def test_un_dataframe_sin_resolver_no_se_adivina(self) -> None:
        """Sin las columnas de identidad se declara que no se excluyó nada."""
        df = _resueltas([{"id": 0, "_nif_key": _NIF_PROPIO}]).drop(columns=["_nif_key"])
        assert claves_de_la_organizacion(df, _PROPIA) == set()

    def test_sin_adjudicaciones_no_hay_nada_que_excluir(self) -> None:
        assert claves_de_la_organizacion(pd.DataFrame(), _PROPIA) == set()


# ── Lo que ve el usuario ───────────────────────────────────────────────────


class TestExclusionEnLaRespuesta:
    def test_la_propia_organizacion_no_se_propone_como_socia(self) -> None:
        df = _resueltas([{"id": i, "_nif_key": _NIF_PROPIO} for i in range(5)])
        assert sugerir_socios(df, identidad=_PROPIA).socios == []

    def test_la_propia_organizacion_no_sale_entre_los_lideres(self) -> None:
        """`lideres` es el «contra quién se va»: verse ahí es el bug de S2.1."""
        filas = [{"id": i, "_nif_key": _NIF_PROPIO} for i in range(6)]
        filas += [
            {"id": 100 + i, "empresa_key": "rival", "nombre_canonico": "Rival"} for i in range(6)
        ]
        resultado = sugerir_socios(_resueltas(filas), identidad=_PROPIA)

        claves = {lider.empresa_key for lider in resultado.lideres}
        assert "acme" not in claves
        assert "rival" in claves

    def test_sin_identidad_la_lista_sale_como_antes(self) -> None:
        """El degradado: sin NIFs declarados el segmento entero sigue dentro."""
        filas = [{"id": i, "_nif_key": _NIF_PROPIO} for i in range(5)]
        resultado = sugerir_socios(_resueltas(filas))
        assert [s.empresa_key for s in resultado.socios] == ["acme"]
        assert {lider.empresa_key for lider in resultado.lideres} == {"acme"}

    def test_excluirse_no_promociona_a_quien_no_llegaba_al_minimo(self) -> None:
        """El corte por `MIN_CONTRATOS` se hace sobre el universo real."""
        filas = [{"id": i, "_nif_key": _NIF_PROPIO} for i in range(5)]
        filas += [{"id": 100, "empresa_key": "pequena", "nombre_canonico": "Pequeña"}]
        resultado = sugerir_socios(_resueltas(filas), identidad=_PROPIA)
        assert [s.empresa_key for s in resultado.socios] == []

    def test_la_cuota_de_los_lideres_sigue_siendo_la_del_mercado(self) -> None:
        """Se descarta la fila, no el denominador: la cuota es un dato medido."""
        filas = [{"id": i, "_nif_key": _NIF_PROPIO} for i in range(6)]
        filas += [
            {"id": 100 + i, "empresa_key": "rival", "nombre_canonico": "Rival"} for i in range(6)
        ]
        resultado = sugerir_socios(_resueltas(filas), identidad=_PROPIA)
        rival = next(lider for lider in resultado.lideres if lider.empresa_key == "rival")
        assert rival.cuota_pct == pytest.approx(50.0)

    def test_la_exclusion_explicita_y_la_de_identidad_se_suman(self) -> None:
        filas = [{"id": i, "_nif_key": _NIF_PROPIO} for i in range(5)]
        filas += [
            {"id": 100 + i, "empresa_key": "vetada", "nombre_canonico": "Vetada"} for i in range(5)
        ]
        resultado = sugerir_socios(_resueltas(filas), identidad=_PROPIA, excluir={"vetada"})
        assert resultado.socios == []


# ── El punto de entrada del endpoint ───────────────────────────────────────


class TestSociosDelSegmento:
    def _df(self) -> pd.DataFrame:
        return _resueltas([{"id": i, "_nif_key": _NIF_PROPIO} for i in range(5)])

    def test_sin_usuario_no_se_resuelve_ninguna_organizacion(self) -> None:
        """Un job sin contexto no tiene identidad fiscal: no se inventa una."""
        with (
            patch(_CARGA, return_value=self._df()),
            patch("services.competitive.socios.resolve_organization") as resolver,
        ):
            resultado = socios_del_segmento()

        resolver.assert_not_called()
        assert [s.empresa_key for s in resultado.socios] == ["acme"]

    def test_con_usuario_se_excluye_su_organizacion(self) -> None:
        with (
            patch(_CARGA, return_value=self._df()),
            patch(
                "services.competitive.socios.resolve_organization", return_value=(7, "owner")
            ) as resolver,
            patch("services.competitive.socios.identidad_fiscal", return_value=_PROPIA),
        ):
            resultado = socios_del_segmento(user_id=3, organization_id=7)

        resolver.assert_called_once_with(3, 7)
        assert resultado.socios == []

    def test_un_fallo_leyendo_la_identidad_no_tumba_la_pantalla(self) -> None:
        """Sin exclusión la lista sigue sirviendo; sin lista, no."""
        with (
            patch(_CARGA, return_value=self._df()),
            patch("services.competitive.socios.resolve_organization", return_value=(7, "owner")),
            patch(
                "services.competitive.socios.identidad_fiscal",
                side_effect=RuntimeError("BD caída"),
            ),
        ):
            resultado = socios_del_segmento(user_id=3)

        assert [s.empresa_key for s in resultado.socios] == ["acme"]

    def test_pedir_una_organizacion_ajena_sigue_siendo_un_403(self) -> None:
        """Tragarse el permiso convertiría un 403 en una respuesta distinta."""
        with (
            patch(_CARGA, return_value=self._df()),
            patch(
                "services.competitive.socios.resolve_organization",
                side_effect=OrganizationAccessError("No perteneces a esta organización."),
            ),
            pytest.raises(OrganizationAccessError),
        ):
            socios_del_segmento(user_id=3, organization_id=99)


# ── El contrato con la resolución de identidad de `competitors.py` ─────────


_FILAS_CRUDAS = [
    {
        "licitacion_id": f"L{i}",
        "nombre": "Casa Propia SL",
        "nif": _NIF_PROPIO,
        "empresa_id": 41,
        "empresa_nombre_master": "Casa Propia",
        "empresa_nif_master": _NIF_PROPIO,
        "ccaa": "Madrid",
        "importe_adjudicado": 100_000.0,
        "importe_licitacion": 120_000.0,
        "n_ofertas_recibidas": 2,
        "fecha_adjudicacion": f"2026-05-0{i + 1}",
        "organo_contratacion": f"Min {i}",
        "tecnologia": "SAP",
        "estado": "adjudicada",
        "es_pyme": 0,
    }
    for i in range(5)
]


def test_la_carga_resuelta_conserva_las_columnas_de_identidad() -> None:
    """`_prepare_company_identity` descarta columnas: estas dos tienen que quedar.

    Es el contrato entre `services/analytics/competitors.py` y este módulo. Si
    alguien las añade a la lista de `drop`, la exclusión dejaría de encontrar a
    nadie **en silencio** — y sin este test nadie se enteraría.
    """
    from services.analytics.competitors import cargar_adjudicaciones_resueltas

    with patch("services.analytics.competitors.load_for_competitors", return_value=_FILAS_CRUDAS):
        df = cargar_adjudicaciones_resueltas()

    assert {"empresa_key", "_nif_key", "_empresa_id_key"} <= set(df.columns)
    assert claves_de_la_organizacion(df, _PROPIA) == set(df["empresa_key"].astype(str))
