"""F1.2 (búsqueda global de la paleta) y F3.3 (socios de UTE).

Las dos comparten la regla de no rellenar: la paleta declara qué tipos buscó
—sin organización **no busca** oportunidades, que no es lo mismo que no
encontrarlas— y el buscador de socios devuelve lista vacía con motivo en vez
de las empresas más grandes del corpus.
"""

from __future__ import annotations

from typing import Any

import pandas as pd
import pytest

from services.busqueda_global import MIN_LONGITUD, buscar_global, es_nif
from services.competitive.socios import MIN_CONTRATOS, sugerir_socios


class _RepoFalso:
    """Repositorio de búsqueda en memoria, para probar el servicio sin BD."""

    def __init__(self, **respuestas: Any) -> None:
        self._r = respuestas
        self.llamadas: list[str] = []

    def expedientes(self, termino: str, limite: int) -> list[dict[str, Any]]:
        self.llamadas.append("expediente")
        return list(self._r.get("expedientes", []))

    def empresas(self, termino: str, limite: int) -> list[dict[str, Any]]:
        self.llamadas.append("empresa")
        return list(self._r.get("empresas", []))

    def organos(self, termino: str, limite: int) -> list[dict[str, Any]]:
        self.llamadas.append("organo")
        return list(self._r.get("organos", []))

    def oportunidades(self, termino: str, org: int, limite: int) -> list[dict[str, Any]]:
        self.llamadas.append("oportunidad")
        return list(self._r.get("oportunidades", []))

    def empresa_por_nif(self, nif: str) -> dict[str, Any] | None:
        self.llamadas.append("nif")
        return self._r.get("nif")


@pytest.fixture
def repo(monkeypatch: pytest.MonkeyPatch) -> Any:
    """Inyecta el repositorio falso en el import diferido del servicio."""

    def _instalar(**respuestas: Any) -> _RepoFalso:
        falso = _RepoFalso(**respuestas)
        import db.repositories.busqueda as mod

        monkeypatch.setattr(mod, "BusquedaRepository", lambda: falso)
        return falso

    return _instalar


# ── F1.2 ────────────────────────────────────────────────────────────────────


class TestTerminoCorto:
    @pytest.mark.parametrize("q", ["", " ", "ab", "  a "])
    def test_no_busca_y_lo_dice(self, q: str) -> None:
        """200 con motivo, no 422: la paleta consulta en cada tecla."""
        respuesta = buscar_global(q)
        assert respuesta.resultados == []
        assert respuesta.sin_busqueda is not None
        assert str(MIN_LONGITUD) in respuesta.sin_busqueda


class TestTiposBuscados:
    def test_sin_organizacion_no_busca_oportunidades(self, repo: Any) -> None:
        """«No busqué» y «no encontré» son respuestas distintas."""
        falso = repo()
        respuesta = buscar_global("ejemplo")
        assert "oportunidad" not in respuesta.tipos_buscados
        assert "oportunidad" not in falso.llamadas

    def test_con_organizacion_si(self, repo: Any) -> None:
        falso = repo()
        respuesta = buscar_global("ejemplo", organization_id=7)
        assert "oportunidad" in respuesta.tipos_buscados
        assert "oportunidad" in falso.llamadas

    def test_busca_siempre_los_tres_publicos(self, repo: Any) -> None:
        respuesta = buscar_global("ejemplo")
        assert respuesta.tipos_buscados == ["expediente", "empresa", "organo"]


class TestResultados:
    def test_agrupa_por_tipo(self, repo: Any) -> None:
        repo(
            expedientes=[{"id": "EXP-1", "titulo": "Servicios SAP", "subtitulo": "Ayto"}],
            empresas=[{"id": 5, "titulo": "Empresa Ejemplo", "subtitulo": "Z9999999R"}],
        )
        respuesta = buscar_global("ejemplo")
        assert respuesta.por_tipo == {"expediente": 1, "empresa": 1}

    def test_el_id_viaja_siempre_como_texto(self, repo: Any) -> None:
        """La empresa tiene id numérico y el expediente no; la paleta navega
        con una sola forma."""
        repo(empresas=[{"id": 5, "titulo": "Empresa Ejemplo", "subtitulo": None}])
        respuesta = buscar_global("ejemplo")
        assert respuesta.resultados[0].id == "5"

    def test_sin_titulo_se_usa_el_id(self, repo: Any) -> None:
        repo(expedientes=[{"id": "EXP-1", "titulo": None, "subtitulo": None}])
        assert buscar_global("exp").resultados[0].titulo == "EXP-1"

    def test_subtitulo_vacio_no_deja_hueco(self, repo: Any) -> None:
        repo(empresas=[{"id": 5, "titulo": "Empresa Ejemplo", "subtitulo": ""}])
        assert buscar_global("ejemplo").resultados[0].subtitulo is None


class TestNif:
    @pytest.mark.parametrize("valor", ["Z9999999R", "X1111111P", "12345678Z"])
    def test_reconoce_un_nif(self, valor: str) -> None:
        assert es_nif(valor)

    @pytest.mark.parametrize("valor", ["indra", "A2859903", "Z99999999R", ""])
    def test_lo_que_no_es_nif(self, valor: str) -> None:
        assert not es_nif(valor)

    def test_el_nif_exacto_encabeza_y_se_marca(self, repo: Any) -> None:
        """Quien teclea un NIF no busca: identifica. La paleta abre el perfil."""
        repo(nif={"id": 5, "nombre_canonico": "Empresa Ejemplo", "nif": "Z9999999R"})
        respuesta = buscar_global("Z9999999R")
        assert respuesta.resultados[0].exacto is True
        assert respuesta.resultados[0].tipo == "empresa"

    def test_un_termino_normal_no_marca_exacto(self, repo: Any) -> None:
        repo(empresas=[{"id": 5, "titulo": "Empresa Ejemplo", "subtitulo": "Z9999999R"}])
        assert all(not r.exacto for r in buscar_global("ejemplo").resultados)


class TestDegradacion:
    def test_un_tipo_caido_no_tumba_los_demas(
        self, repo: Any, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Un fallo parcial visto como «no hay nada» es el peor resultado."""
        falso = repo(empresas=[{"id": 5, "titulo": "Empresa Ejemplo", "subtitulo": None}])

        def _revienta(*_a: Any, **_k: Any) -> list[dict[str, Any]]:
            raise RuntimeError("tabla caída")

        monkeypatch.setattr(falso, "expedientes", _revienta)
        respuesta = buscar_global("ejemplo")
        assert respuesta.por_tipo == {"empresa": 1}
        # El tipo caído sigue declarado como buscado: se intentó.
        assert "expediente" in respuesta.tipos_buscados


# ── F3.3 ────────────────────────────────────────────────────────────────────


def _adjudicaciones(filas: list[dict[str, Any]]) -> pd.DataFrame:
    base = {
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
    }
    return pd.DataFrame([{**base, **fila} for fila in filas])


class TestSociosVacio:
    def test_sin_adjudicaciones_lo_declara(self) -> None:
        assert sugerir_socios(pd.DataFrame()).sin_resultados is not None

    def test_por_debajo_del_minimo_no_propone(self) -> None:
        """Con dos contratos, la «especialización» es una casualidad."""
        df = _adjudicaciones([{"id": i} for i in range(MIN_CONTRATOS - 1)])
        resultado = sugerir_socios(df)
        assert resultado.socios == []
        assert resultado.sin_resultados is not None
        assert str(MIN_CONTRATOS) in resultado.sin_resultados


class TestSociosConMotivo:
    def test_toda_sugerencia_lleva_motivo(self) -> None:
        """Una sugerencia sin motivo es sólo un nombre en una lista."""
        df = _adjudicaciones([{"id": i, "organo_contratacion": f"Ayto {i}"} for i in range(5)])
        resultado = sugerir_socios(df)
        assert resultado.socios
        assert all(s.motivos for s in resultado.socios)

    def test_el_motivo_de_muchos_organos_cita_el_numero(self) -> None:
        df = _adjudicaciones([{"id": i, "organo_contratacion": f"Ayto {i}"} for i in range(5)])
        motivos = " ".join(sugerir_socios(df).socios[0].motivos)
        assert "5 órganos" in motivos

    def test_el_motivo_de_ute_aparece_cuando_toca(self) -> None:
        df = _adjudicaciones([{"id": i, "es_ute": 1} for i in range(5)])
        motivos = " ".join(sugerir_socios(df).socios[0].motivos)
        assert "UTE" in motivos

    def test_el_motivo_de_pyme(self) -> None:
        df = _adjudicaciones([{"id": i, "es_pyme": 1} for i in range(5)])
        motivos = " ".join(sugerir_socios(df).socios[0].motivos)
        assert "PYME" in motivos

    def test_siempre_hay_un_motivo_de_reserva(self) -> None:
        """Sin nada que la distinga, el motivo es el volumen: un hecho medido."""
        df = _adjudicaciones([{"id": i} for i in range(5)])
        motivos = " ".join(sugerir_socios(df).socios[0].motivos)
        assert "5 adjudicaciones" in motivos


class TestSociosExcluidos:
    def test_no_propone_a_los_excluidos(self) -> None:
        """La propia organización y los competidores marcados quedan fuera."""
        df = _adjudicaciones([{"id": i} for i in range(5)])
        resultado = sugerir_socios(df, excluir={"acme"})
        assert resultado.socios == []

    def test_excluir_no_promociona_a_quien_no_llegaba(self) -> None:
        """El corte por mínimo se hace sobre el universo real."""
        filas = [{"id": i} for i in range(5)]
        filas += [{"id": 100, "empresa_key": "pequena", "nombre_canonico": "Pequeña"}]
        resultado = sugerir_socios(_adjudicaciones(filas), excluir={"acme"})
        assert [s.empresa_key for s in resultado.socios] == []


class TestSociosUniverso:
    def test_declara_el_n(self) -> None:
        """ADR-014: la cifra viaja con el tamaño de la muestra."""
        df = _adjudicaciones([{"id": i} for i in range(5)])
        assert sugerir_socios(df).n_adjudicaciones == 5

    def test_respeta_el_limite(self) -> None:
        filas = [
            {"id": i, "empresa_key": f"e{i % 4}", "nombre_canonico": f"E{i % 4}"} for i in range(40)
        ]
        assert len(sugerir_socios(_adjudicaciones(filas), limit=2).socios) == 2
