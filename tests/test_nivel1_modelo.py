"""Modelo de nivel 1, «¿es TI?» (plan de tres niveles, F3, §4): features,
dataset y entrenamiento, sin BD.

Lo que se fija:

- en PLACSP la ``descripcion`` es el ``<summary>`` (metadatos) y no entra;
- el CPV entra jerárquico y **sin** ``CPV_TI``, que en la población puntuada
  vale siempre lo mismo;
- manda la etiqueta humana; la del LLM solo si su acuerdo es apto; una fila
  sin etiqueta no es un negativo;
- el golden (tune y holdout) no entrena, ni por id ni como convocatoria casi
  idéntica con otro id;
- el candidato A entrena, calibra y separa en datos sintéticos, y la
  comparación de punta a punta aplica el gate.

Los datos de entrenamiento de abajo son **sintéticos** y solo prueban el
código: no son etiquetas, y ninguno se parece al golden real.
"""

from __future__ import annotations

import random
from dataclasses import replace

import pytest

from db.repositories.tecnologia_pliego import (
    ES_TI_SENTINEL,
    NO_ES_TI_SENTINEL,
    SIN_EVIDENCIA_SENTINEL,
    es_ti_de_version_vigente,
)
from services.ml.golden_ti import EjemploGoldenTi
from services.ml.nivel1 import (
    DatosInsuficientes,
    FilaNivel1,
    codigos_cpv,
    comparar_candidatos,
    cpv_es_ti,
    dataset_entrenamiento,
    entrenar_candidato,
    estructura_nivel1,
    etiqueta_nivel1,
    fila_desde_golden,
    idioma_aproximado,
    texto_nivel1,
    tokens_cpv,
)

_SUMMARY = (
    "Id licitación: 2026/123; Órgano de Contratación: Instituto Nacional de "
    "Ciberseguridad; Importe: 1000 EUR; Estado: PUB"
)


class TestTexto:
    def test_en_placsp_el_summary_no_entra(self) -> None:
        assert texto_nivel1("Limpieza de oficinas", _SUMMARY, "placsp") == "Limpieza de oficinas"
        assert texto_nivel1("Limpieza", "lo que sea", "bulk_202609") == "Limpieza"

    def test_en_otra_fuente_entra_la_descripcion_real(self) -> None:
        assert texto_nivel1("Llicències", "Programari de gestió", "pscp") == (
            "Llicències Programari de gestió"
        )

    def test_algo_con_forma_de_summary_no_entra_venga_de_donde_venga(self) -> None:
        assert texto_nivel1("Limpieza", _SUMMARY, "ted") == "Limpieza"


class TestCpvEIdioma:
    def test_tokens_jerarquicos_sin_cpv_ti(self) -> None:
        tokens = tokens_cpv("72267000-4||48000000")
        assert tokens == [
            "CPV2_72",
            "CPV3_722",
            "CPV4_7226",
            "CPV2_48",
            "CPV3_480",
            "CPV4_4800",
        ]
        assert not any("CPV_TI" in t for t in tokens)

    def test_sin_cpv(self) -> None:
        assert tokens_cpv(None) == ["CPV_NINGUNO"]
        assert codigos_cpv("sin código") == []

    def test_cpv_ti(self) -> None:
        assert cpv_es_ti("45000000||72000000")
        assert not cpv_es_ti("79000000-4")

    @pytest.mark.parametrize(
        ("texto", "idioma"),
        [
            ("Servicio de mantenimiento del sistema de gestión del ayuntamiento", "es"),
            ("Servei de manteniment dels equips amb suport", "ca"),
            ("Servizo de mantemento do sistema de xestión do concello", "gl"),
            ("Udalaren kudeaketa sistemaren mantentze zerbitzua eta hornidura", "eu"),
            ("SAP S/4HANA", "und"),
        ],
    )
    def test_idioma(self, texto: str, idioma: str) -> None:
        assert idioma_aproximado(texto) == idioma

    def test_la_estructura_junta_cpv_e_idioma(self) -> None:
        assert estructura_nivel1("72000000", "Servei de manteniment") == (
            "CPV2_72 CPV3_720 CPV4_7200 LANG_ca"
        )


class TestEtiqueta:
    @pytest.mark.parametrize(
        ("humano", "llm", "usar_llm", "esperada"),
        [
            (1, False, True, (True, "humano")),  # manda el humano
            (0, True, True, (False, "humano")),
            (None, True, True, (True, "llm")),
            (None, False, True, (False, "llm")),
            (None, True, False, None),  # LLM no apto: no entrena
            (None, None, True, None),  # nadie se pronunció: no es un negativo
        ],
    )
    def test_prioridad(self, humano, llm, usar_llm, esperada) -> None:
        assert etiqueta_nivel1(humano, llm, usar_llm=usar_llm) == esperada

    def test_el_lector_del_llm_trata_sin_evidencia_como_no_se_pronuncio(self) -> None:
        """Nota de §6 para F3: aunque la versión traiga el marcador."""
        assert es_ti_de_version_vigente([ES_TI_SENTINEL, "ERP"]) is True
        assert es_ti_de_version_vigente([NO_ES_TI_SENTINEL]) is False
        assert es_ti_de_version_vigente([ES_TI_SENTINEL, SIN_EVIDENCIA_SENTINEL]) is None
        assert es_ti_de_version_vigente(["ERP"]) is None


def _golden(id_: str, titulo: str, *, es_ti: bool, split: str, fecha: str) -> EjemploGoldenTi:
    return EjemploGoldenTi(
        id_externo=id_,
        fuente="pscp",
        fecha=fecha,
        titulo=titulo,
        descripcion="",
        cpv="72000000",
        es_ti=es_ti,
        familias=(),
        fabricantes=(),
        etiquetado_por="humano",
        etiquetado_at="2026-10-24T00:00:00+00:00",
        split=split,  # type: ignore[arg-type]  # literal de test
    )


def _fila_db(id_: str, titulo: str, *, humano=None, llm=None, tecnologia=None) -> dict:
    return {
        "id_externo": id_,
        "fuente": "pscp",
        "fecha_publicacion": "2026-03-01",
        "titulo": titulo,
        "descripcion": None,
        "cpv": "72000000",
        "tecnologia": tecnologia,
        "humano_es_ti": humano,
        "llm_es_ti": llm,
    }


class TestDataset:
    def test_fuera_el_golden_y_lo_que_no_tiene_etiqueta(self) -> None:
        golden = [
            _golden(
                "G1",
                "Manteniment del gestor documental",
                es_ti=True,
                split="tune",
                fecha="2026-01-01",
            ),
            _golden(
                "G2",
                "Revista científica Wiley 2026",
                es_ti=False,
                split="holdout",
                fecha="2026-06-01",
            ),
        ]
        filas = [
            _fila_db("G1", "Manteniment del gestor documental", humano=1),  # mismo id
            _fila_db("X9", "Revista científica Wiley 2027", llm=False),  # misma convocatoria
            _fila_db(
                "T1", "Desarrollo de la sede electrónica", humano=1, tecnologia="ADMIN_ELECTRONICA"
            ),
            _fila_db("T2", "Hosting de la web municipal", llm=True),
            _fila_db("T3", "Limpieza de colegios"),  # sin etiqueta
        ]
        entrenamiento, resumen = dataset_entrenamiento(filas, golden, usar_llm=True)
        assert [f.id_externo for f in entrenamiento] == ["T1", "T2"]
        assert entrenamiento[0].tiene_keyword and not entrenamiento[1].tiene_keyword
        assert entrenamiento[1].origen == "llm"
        assert resumen.excluidas_golden_id == 1
        assert resumen.excluidas_golden_grupo == 1
        assert resumen.as_dict()["n_llm"] == 1

    def test_sin_acuerdo_apto_el_llm_no_entrena(self) -> None:
        filas = [_fila_db("T2", "Hosting de la web municipal", llm=True)]
        entrenamiento, resumen = dataset_entrenamiento(filas, [], usar_llm=False)
        assert entrenamiento == []
        assert resumen.usar_llm is False

    def test_el_golden_lleva_las_mismas_features(self) -> None:
        ejemplo = replace(
            _golden(
                "G1", "Servei de manteniment", es_ti=True, split="tune", fecha="2026-01-01T10:00"
            ),
            fuente="placsp",
            descripcion=_SUMMARY,
        )
        fila = fila_desde_golden(ejemplo, tiene_keyword=False)
        assert fila.texto == "Servei de manteniment"
        assert fila.estructura.endswith("LANG_ca")
        assert fila.fecha == "2026-01-01"
        assert fila.cpv_ti and not fila.tiene_keyword


# ── Entrenamiento con datos sintéticos ──────────────────────────────────────

_TI = ["desarrollo", "aplicación", "software", "plataforma", "licencias", "servidores", "hosting"]
_NO_TI = ["limpieza", "jardinería", "obras", "revista", "catering", "mobiliario", "vigilancia"]
_RELLENO = ["servicio", "contrato", "municipal", "lote", "anual", "del", "para"]


def _sintetica(
    rng: random.Random, i: int, *, es_ti: bool, keyword: bool, cpv_ti: bool, fecha: str
) -> FilaNivel1:
    vocab = _TI if es_ti else _NO_TI
    palabras = rng.sample(vocab, 3) + rng.sample(_RELLENO, 2)
    texto = " ".join(palabras)
    cpv = "72000000" if cpv_ti else "90900000"
    return FilaNivel1(
        id_externo=f"S{i}",
        fuente="pscp",
        fecha=fecha,
        titulo=texto,
        texto=texto,
        estructura=estructura_nivel1(cpv, texto),
        es_ti=es_ti,
        origen="llm",
        tiene_keyword=keyword,
        cpv_ti=cpv_ti,
    )


def _conjunto(n: int, *, semilla: int, anio: int) -> list[FilaNivel1]:
    """Los cuatro tipos de caso del gate, repartidos en un año."""
    rng = random.Random(semilla)
    filas: list[FilaNivel1] = []
    tipos = [(True, True, True), (True, False, True), (False, True, False), (False, False, True)]
    for i in range(n):
        es_ti, keyword, cpv_ti = tipos[i % 4]
        fecha = f"{anio}-{1 + (i * 12) // n:02d}-{1 + i % 28:02d}"
        filas.append(
            _sintetica(
                rng, semilla * 10_000 + i, es_ti=es_ti, keyword=keyword, cpv_ti=cpv_ti, fecha=fecha
            )
        )
    return filas


class TestEntrenamiento:
    def test_a_separa_y_da_probabilidades(self) -> None:
        filas = _conjunto(200, semilla=1, anio=2024)
        modelo = entrenar_candidato("A", filas)
        prueba = _conjunto(40, semilla=2, anio=2026)
        p = modelo.predict_proba(prueba)
        assert all(0.0 <= v <= 1.0 for v in p)
        media_ti = sum(v for v, f in zip(p, prueba, strict=True) if f.es_ti) / 20
        media_no = sum(v for v, f in zip(p, prueba, strict=True) if not f.es_ti) / 20
        assert media_ti > 0.8 > 0.2 > media_no
        assert modelo.metadata["calibracion"] == "isotonic_temporal"
        assert modelo.metadata["n_calibracion"] == 40
        assert modelo.predict_proba([]) == []

    def test_pocas_filas_no_entrenan(self) -> None:
        with pytest.raises(DatosInsuficientes, match="< 50"):
            entrenar_candidato("A", _conjunto(20, semilla=1, anio=2024))

    def test_una_sola_clase_no_entrena(self) -> None:
        filas = [f for f in _conjunto(400, semilla=1, anio=2024) if f.es_ti]
        with pytest.raises(DatosInsuficientes, match="0 negativos"):
            entrenar_candidato("A", filas)

    def test_candidato_desconocido(self) -> None:
        with pytest.raises(ValueError, match="candidato desconocido"):
            entrenar_candidato("C", _conjunto(200, semilla=1, anio=2024))


class TestComparacion:
    def test_de_punta_a_punta_con_a_y_sin_embeddings(self, monkeypatch: pytest.MonkeyPatch) -> None:
        import services.ml.nivel1 as nivel1

        monkeypatch.setattr(nivel1, "embeddings_disponibles", lambda: False)
        entrenamiento = _conjunto(240, semilla=1, anio=2024)
        tune = _conjunto(80, semilla=2, anio=2025)
        holdout = _conjunto(80, semilla=3, anio=2026)
        resultado = comparar_candidatos(
            entrenamiento, tune, holdout, candidatos=("A", "B"), n_bootstrap=200
        )
        informe = resultado.informe
        assert set(resultado.modelos) == {"A"}
        assert informe.sin_evaluar == {"B": "sentence-transformers no está instalado"}
        assert informe.ganador == "A"
        assert informe.apto, informe.motivos
        assert resultado.modelos["A"].bandas is not None

    def test_sin_datos_de_entrenamiento_nadie_se_evalua(self) -> None:
        holdout = _conjunto(80, semilla=3, anio=2026)
        resultado = comparar_candidatos([], holdout, holdout, candidatos=("A",), n_bootstrap=50)
        assert resultado.modelos == {}
        assert "A" in resultado.informe.sin_evaluar
        assert not resultado.informe.apto
