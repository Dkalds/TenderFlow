"""Integridad del dataset y del split del clasificador SAP.

Cada test de este módulo fija un invariante que el código **violaba** antes:

- ``_build_dataset`` concatenaba positivos y luego negativos, destruyendo el
  orden por fecha; el split "temporal" de ``train()`` caía en silencio a un
  ``train_test_split`` aleatorio, así que ``temporal_split=True`` era
  inalcanzable y todas las métricas medían interpolación.
- El ``OR`` con ``raw_keywords`` revertía a positivo cualquier fila que un
  humano hubiera marcado como no relevante.
- Nada impedía que los lotes y republicaciones de un mismo expediente cayeran
  a los dos lados del corte.
"""

from __future__ import annotations

from datetime import date, timedelta

import pandas as pd
import pytest

from scraper.ml_pipeline import (
    TemporalSplitImposible,
    _clave_grupo,
    build_dataset_rows,
    split_dataset_rows,
)

_SAP = "Implantacion de SAP S/4HANA modulo financiero"
_NO_SAP = "Suministro de material de oficina para dependencias"


# Palabras que hacen que cada licitación sintética sea un expediente distinto:
# con títulos idénticos salvo un número, `_clave_grupo` los colapsa en un solo
# grupo (a propósito: así agrupa los lotes) y no habría nada que repartir.
_VARIANTES = [
    "central",
    "autonomico",
    "provincial",
    "municipal",
    "consorcio",
    "hospitalario",
    "universitario",
    "portuario",
    "tributario",
    "judicial",
]


def _df_intercalado(n_pos: int, n_neg: int) -> pd.DataFrame:
    """Positivos y negativos repartidos a lo largo de todo el eje temporal."""
    filas: list[dict[str, object]] = []
    d0 = date(2024, 1, 1)
    total = n_pos + n_neg
    paso = max(1, total // max(1, n_pos))
    for i in range(total):
        es_pos = (i % paso) == 0 and sum(1 for f in filas if f["raw_keywords"]) < n_pos
        variante = " ".join(
            _VARIANTES[(i // len(_VARIANTES) ** k) % len(_VARIANTES)] for k in range(3)
        )
        filas.append(
            {
                "titulo": f"{_SAP if es_pos else _NO_SAP} {variante}",
                "descripcion": "",
                "raw_keywords": "SAP" if es_pos else None,
                "cpv": "72000000" if es_pos else "30000000",
                "importe": 100_000.0,
                "fecha_publicacion": (d0 + timedelta(days=i)).isoformat(),
            }
        )
    return pd.DataFrame(filas)


class TestOrdenPreservado:
    def test_las_filas_salen_en_el_orden_del_dataframe(self) -> None:
        # Antes: todos los 1 y después todos los 0, sin importar la fecha.
        filas = build_dataset_rows(_df_intercalado(40, 80))
        etiquetas = [f.label for f in filas]
        assert etiquetas, "el dataset no puede salir vacío"
        primer_cero = etiquetas.index(0)
        assert 1 in etiquetas[primer_cero:], (
            "tras el primer negativo no aparece ningún positivo: el dataset "
            "sigue viniendo en bloques y el split temporal no puede cortar"
        )

    def test_las_fechas_salen_no_decrecientes(self) -> None:
        filas = build_dataset_rows(_df_intercalado(40, 80))
        fechas = [f.fecha for f in filas if f.fecha]
        assert fechas == sorted(fechas)


class TestSplitTemporal:
    def test_corta_por_fecha_y_no_por_posicion(self) -> None:
        split = split_dataset_rows(build_dataset_rows(_df_intercalado(60, 120)))
        assert split.strategy == "temporal"
        assert split.fecha_corte is not None
        assert split.train and split.test

    def test_ninguna_fila_de_test_es_anterior_al_corte(self) -> None:
        filas = build_dataset_rows(_df_intercalado(60, 120))
        split = split_dataset_rows(filas)
        assert split.fecha_corte is not None
        for i in split.test:
            fecha = filas[i].fecha
            assert fecha is not None and fecha > split.fecha_corte

    def test_ambos_lados_tienen_las_dos_clases(self) -> None:
        filas = build_dataset_rows(_df_intercalado(60, 120))
        split = split_dataset_rows(filas)
        assert len({filas[i].label for i in split.train}) == 2
        assert len({filas[i].label for i in split.test}) == 2

    def test_sin_corte_valido_aborta_en_vez_de_caer_a_aleatorio(self) -> None:
        # Todos los positivos al principio del eje temporal: ningún corte deja
        # las dos clases a ambos lados. Antes esto degradaba en silencio a un
        # split aleatorio y publicaba las métricas con los mismos nombres.
        filas_df: list[dict[str, object]] = []
        d0 = date(2024, 1, 1)
        for i in range(120):
            es_pos = i < 40
            filas_df.append(
                {
                    "titulo": f"{_SAP if es_pos else _NO_SAP} {i}",
                    "descripcion": "",
                    "raw_keywords": "SAP" if es_pos else None,
                    "cpv": "72000000" if es_pos else "30000000",
                    "fecha_publicacion": (d0 + timedelta(days=i)).isoformat(),
                }
            )
        filas = build_dataset_rows(pd.DataFrame(filas_df))
        with pytest.raises(TemporalSplitImposible):
            split_dataset_rows(filas)


def _df_con_lotes(n_expedientes: int, lotes_por_expediente: int) -> pd.DataFrame:
    """``n_expedientes`` convocatorias distintas, cada una con varios lotes.

    Los lotes comparten título salvo el número, así que ``_clave_grupo`` los
    agrupa; los expedientes entre sí tienen palabras distintas, así que cada
    grupo es pequeño y no salta la guarda de ``_MAX_GROUP_SHARE``.
    """
    filas: list[dict[str, object]] = []
    d0 = date(2024, 1, 1)
    for e in range(n_expedientes):
        es_pos = e % 3 == 0
        base = _SAP if es_pos else _NO_SAP
        variante = " ".join(
            _VARIANTES[(e // len(_VARIANTES) ** k) % len(_VARIANTES)] for k in range(3)
        )
        for lote in range(lotes_por_expediente):
            filas.append(
                {
                    "titulo": f"{base} {variante} lote {lote}",
                    "descripcion": "",
                    "raw_keywords": "SAP" if es_pos else None,
                    "cpv": "72000000" if es_pos else "30000000",
                    "fecha_publicacion": (d0 + timedelta(days=e)).isoformat(),
                }
            )
    return pd.DataFrame(filas)


class TestIntegridadDeGrupo:
    def test_un_expediente_no_puede_estar_en_los_dos_lados(self) -> None:
        # Los lotes de un mismo expediente comparten título salvo el número.
        # Con el split anterior caían a ambos lados del corte e inflaban
        # F1/PR-AUC por memorización, no por generalización.
        filas = build_dataset_rows(_df_con_lotes(90, 3))
        split = split_dataset_rows(filas)
        grupos_train = {filas[i].grupo for i in split.train}
        grupos_test = {filas[i].grupo for i in split.test}
        assert split.test, "el split no dejó nada en test"
        assert not (grupos_train & grupos_test), (
            f"grupos en ambos lados: {sorted(grupos_train & grupos_test)[:3]}"
        )

    def test_la_clave_de_grupo_colapsa_lotes_y_prorrogas(self) -> None:
        assert _clave_grupo("Servicio SAP lote 3", "") == _clave_grupo("Servicio SAP lote 7", "")
        assert _clave_grupo("Servicio SAP 2024", "") == _clave_grupo("Servicio SAP 2025", "")
        assert _clave_grupo("Servicio SAP", "") != _clave_grupo("Obra de reforma", "")

    def test_un_grupo_gigante_no_bloquea_el_split(self) -> None:
        # Si la normalización colapsa medio dataset en una sola clave, no es un
        # expediente: es un artefacto. Tratarlo como indivisible dejaría el
        # corte temporal sin salida, así que la guarda lo desagrupa.
        filas = build_dataset_rows(_df_intercalado_titulo_unico(60, 120))
        split = split_dataset_rows(filas)
        assert split.strategy == "temporal"
        assert split.train and split.test

    def test_sin_fechas_el_split_sigue_respetando_los_grupos(self) -> None:
        df = _df_con_lotes(90, 3).drop(columns=["fecha_publicacion"])
        filas = build_dataset_rows(df)
        split = split_dataset_rows(filas)
        assert split.strategy == "grouped_random"
        grupos_train = {filas[i].grupo for i in split.train}
        grupos_test = {filas[i].grupo for i in split.test}
        assert not (grupos_train & grupos_test)


def _df_intercalado_titulo_unico(n_pos: int, n_neg: int) -> pd.DataFrame:
    """Todos los títulos idénticos salvo un número: dos grupos gigantes."""
    filas: list[dict[str, object]] = []
    d0 = date(2024, 1, 1)
    total = n_pos + n_neg
    paso = max(1, total // max(1, n_pos))
    for i in range(total):
        es_pos = (i % paso) == 0 and sum(1 for f in filas if f["raw_keywords"]) < n_pos
        filas.append(
            {
                "titulo": f"{_SAP if es_pos else _NO_SAP} num {i}",
                "descripcion": "",
                "raw_keywords": "SAP" if es_pos else None,
                "cpv": "72000000" if es_pos else "30000000",
                "fecha_publicacion": (d0 + timedelta(days=i)).isoformat(),
            }
        )
    return pd.DataFrame(filas)


class TestFeedbackHumanoNegativo:
    def test_un_no_relevante_humano_gana_a_las_keywords(self) -> None:
        # El caso típico: "mantenimiento de sistemas" hace match de keywords
        # pero un humano confirma que no es SAP. Antes el OR lo revertía a
        # positivo y el modelo nunca aprendía a corregir los falsos positivos
        # del filtro — su único techo posible era reproducirlo.
        df = pd.DataFrame(
            [
                {
                    "titulo": "Mantenimiento de sistemas de gestion",
                    "descripcion": "",
                    "raw_keywords": "SAP",
                    "es_relevante": 0,
                    "cpv": "72000000",
                },
                {
                    "titulo": _SAP,
                    "descripcion": "",
                    "raw_keywords": "SAP",
                    "es_relevante": 1,
                    "cpv": "72000000",
                },
                {
                    "titulo": _NO_SAP,
                    "descripcion": "",
                    "raw_keywords": None,
                    "es_relevante": 0,
                    "cpv": "30000000",
                },
            ]
        )
        filas = build_dataset_rows(df)
        por_titulo = {f.text.split(" CPV")[0].strip(): f.label for f in filas}
        etiqueta = next(v for k, v in por_titulo.items() if k.startswith("Mantenimiento"))
        assert etiqueta == 0, "el feedback humano negativo se está descartando"

    def test_sin_es_relevante_manda_la_keyword(self) -> None:
        df = pd.DataFrame(
            [
                {"titulo": _SAP, "descripcion": "", "raw_keywords": "SAP", "cpv": "72000000"},
                {"titulo": _NO_SAP, "descripcion": "", "raw_keywords": None, "cpv": "30000000"},
            ]
        )
        filas = build_dataset_rows(df)
        assert sorted(f.label for f in filas) == [0, 1]

    def test_es_relevante_nulo_cae_a_la_keyword(self) -> None:
        df = pd.DataFrame(
            [
                {
                    "titulo": _SAP,
                    "descripcion": "",
                    "raw_keywords": "SAP",
                    "es_relevante": None,
                    "cpv": "72000000",
                },
                {
                    "titulo": _NO_SAP,
                    "descripcion": "",
                    "raw_keywords": None,
                    "es_relevante": None,
                    "cpv": "30000000",
                },
            ]
        )
        filas = build_dataset_rows(df)
        assert sorted(f.label for f in filas) == [0, 1]


class TestPoblacionDeServing:
    def test_las_filas_marcan_si_su_cpv_es_ti(self) -> None:
        df = pd.DataFrame(
            [
                {"titulo": _SAP, "descripcion": "", "raw_keywords": "SAP", "cpv": "72000000"},
                {"titulo": _SAP, "descripcion": "", "raw_keywords": "SAP", "cpv": "48200000"},
                {"titulo": _NO_SAP, "descripcion": "", "raw_keywords": None, "cpv": "30000000"},
            ]
        )
        filas = build_dataset_rows(df)
        assert [f.cpv_ti for f in filas] == [True, True, False]
