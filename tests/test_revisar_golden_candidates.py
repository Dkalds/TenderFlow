"""Tests de la herramienta de etiquetado del golden set.

Lo que importa fijar aquí no es la interacción por teclado sino las dos cosas
que, si fallan, corrompen el único conjunto con juicio humano del repo: que
anexar no cuela filas sin etiquetar ni duplica ids, y que el informe de estado
cuenta lo mismo que ``services.ml_eval`` contaría.
"""

from __future__ import annotations

import json

from scripts.revisar_golden_candidates import (
    _escribir_jsonl,
    _leer_jsonl,
    anexar,
    estado,
    informe_umbral,
    revisar,
)


def _fila(id_: str, label: int | None, keyword_match: bool = False) -> dict[str, object]:
    return {
        "id": id_,
        "titulo": f"Licitación {id_}",
        "descripcion": "",
        "label": label,
        "cpv": "72000000",
        "importe": 1000.0,
        "keyword_match": keyword_match,
        "split": "",
        "note": "",
    }


def _escribir(ruta, filas, cabecera=("# cabecera",)):
    _escribir_jsonl(ruta, list(cabecera), filas)


class TestLecturaEscritura:
    def test_conserva_la_cabecera_y_las_filas(self, tmp_path):
        ruta = tmp_path / "c.jsonl"
        _escribir(ruta, [_fila("a", 1), _fila("b", None)])

        cabecera, filas = _leer_jsonl(ruta)
        assert cabecera == ["# cabecera"]
        assert [f["id"] for f in filas] == ["a", "b"]

    def test_la_escritura_es_atomica(self, tmp_path):
        """No puede quedar un `.tmp` suelto: se guarda tras cada etiqueta."""
        ruta = tmp_path / "c.jsonl"
        _escribir(ruta, [_fila("a", 1)])
        assert not list(tmp_path.glob("*.tmp"))

    def test_un_fichero_inexistente_no_revienta(self, tmp_path):
        assert _leer_jsonl(tmp_path / "no-existe.jsonl") == ([], [])


class TestAnexar:
    def test_solo_anexa_lo_etiquetado(self, tmp_path):
        candidatos = tmp_path / "cand.jsonl"
        golden = tmp_path / "golden.jsonl"
        _escribir(candidatos, [_fila("a", 1), _fila("b", None), _fila("c", 0)])
        _escribir(golden, [])

        assert anexar(candidatos, golden) == 2
        _, filas = _leer_jsonl(golden)
        assert sorted(str(f["id"]) for f in filas) == ["a", "c"]

    def test_no_duplica_ids_que_ya_estaban(self, tmp_path):
        """Un duplicado en el golden sesga la métrica sin que nada falle."""
        candidatos = tmp_path / "cand.jsonl"
        golden = tmp_path / "golden.jsonl"
        _escribir(candidatos, [_fila("a", 1), _fila("b", 1)])
        _escribir(golden, [_fila("a", 1)])

        assert anexar(candidatos, golden) == 1
        _, filas = _leer_jsonl(golden)
        assert sorted(str(f["id"]) for f in filas) == ["a", "b"]

    def test_no_anexa_dos_veces_seguidas(self, tmp_path):
        """Es idempotente: reejecutarlo no vuelve a meter lo mismo."""
        candidatos = tmp_path / "cand.jsonl"
        golden = tmp_path / "golden.jsonl"
        _escribir(candidatos, [_fila("a", 1)])
        _escribir(golden, [])

        assert anexar(candidatos, golden) == 1
        assert anexar(candidatos, golden) == 0

    def test_deja_que_el_split_lo_asigne_el_hash(self, tmp_path):
        """`split` vacío o no: lo reparte `asignar_splits`, no este script."""
        candidatos = tmp_path / "cand.jsonl"
        golden = tmp_path / "golden.jsonl"
        fila = _fila("a", 1)
        fila["split"] = "tune"
        _escribir(candidatos, [fila])
        _escribir(golden, [])

        anexar(candidatos, golden)
        contenido = json.loads(golden.read_text(encoding="utf-8").splitlines()[-1])
        assert "split" not in contenido


class TestEstado:
    def test_un_golden_pequeno_no_cumple(self, tmp_path):
        golden = tmp_path / "golden.jsonl"
        _escribir(golden, [_fila(str(i), 1) for i in range(10)])
        assert estado(golden) is False

    def test_cuenta_solo_lo_etiquetado(self, tmp_path):
        """Una fila con `label: null` no puede contar como evidencia."""
        golden = tmp_path / "golden.jsonl"
        _escribir(golden, [_fila("a", None), _fila("b", 1)])
        # No cumple igualmente, pero lo que se comprueba es que no revienta
        # con nulos mezclados, que es el estado normal de un fichero a medias.
        assert estado(golden) is False

    def test_un_golden_suficiente_cumple(self, tmp_path):
        """Con las dos mitades llenas y positivos sin keyword de sobra, pasa."""
        golden = tmp_path / "golden.jsonl"
        # 400 ejemplos positivos sin keyword: el hash reparte ~50/50, así que
        # las dos mitades superan los 60 y el holdout los 30 positivos.
        filas = [_fila(f"ej-{i}", 1, keyword_match=False) for i in range(400)]
        _escribir(golden, filas)
        assert estado(golden) is True


# ── Bucle de etiquetado ──────────────────────────────────────────────────────


def _candidato(id_: str, organo: str = "Ayuntamiento de Prueba") -> dict[str, object]:
    fila = _fila(id_, None, keyword_match=True)
    fila["organo"] = organo
    fila["note"] = "PENDIENTE DE ETIQUETAR · estrato=frontera_modelo_indeciso · ml_proba=0.512"
    return fila


def _respuestas(*valores: str, al_final: type[BaseException] = EOFError):
    """Simula el teclado: devuelve las respuestas y luego corta como Ctrl-D."""
    cola = list(valores)

    def leer(_prompt: str) -> str:
        if not cola:
            raise al_final
        return cola.pop(0)

    return leer


class TestRevisar:
    def test_guarda_tras_cada_respuesta_y_se_reanuda(self, tmp_path):
        """Un corte a mitad no pierde lo etiquetado, y la siguiente sesión
        empieza por el primero que quedó pendiente."""
        ruta = tmp_path / "cand.jsonl"
        _escribir(ruta, [_candidato("a"), _candidato("b"), _candidato("c")])

        escritas = revisar(
            ruta, leer=_respuestas("1", al_final=KeyboardInterrupt), hoy="2026-10-25"
        )
        assert escritas == 1
        _, filas = _leer_jsonl(ruta)
        assert [f["label"] for f in filas] == [1, None, None]

        vistos: list[str] = []

        def leer(_prompt: str) -> str:
            vistos.append("x")
            return "0"

        assert revisar(ruta, leer=leer, hoy="2026-10-25") == 2
        _, filas = _leer_jsonl(ruta)
        assert [f["label"] for f in filas] == [1, 0, 0]
        assert len(vistos) == 2  # «a» no se volvió a preguntar

    def test_la_etiqueta_lleva_procedencia_y_fecha(self, tmp_path):
        ruta = tmp_path / "cand.jsonl"
        _escribir(ruta, [_candidato("a")])

        revisar(ruta, leer=_respuestas("1"), hoy="2026-10-25")
        _, (fila,) = _leer_jsonl(ruta)
        assert fila["source"] == "revisar_golden_candidates"
        assert fila["fecha"] == "2026-10-25"
        assert "PENDIENTE" not in fila["note"]

    def test_saltar_no_escribe_nada(self, tmp_path):
        ruta = tmp_path / "cand.jsonl"
        _escribir(ruta, [_candidato("a")])

        assert revisar(ruta, leer=_respuestas("s"), hoy="2026-10-25") == 0
        _, (fila,) = _leer_jsonl(ruta)
        assert fila["label"] is None
        assert "dudoso" not in fila

    def test_un_dudoso_sale_de_la_cola_hasta_que_se_pide(self, tmp_path):
        ruta = tmp_path / "cand.jsonl"
        _escribir(ruta, [_candidato("a"), _candidato("b")])

        revisar(ruta, leer=_respuestas("d", "1"), hoy="2026-10-25")
        _, filas = _leer_jsonl(ruta)
        assert filas[0]["dudoso"] is True
        assert filas[0]["label"] is None

        # Sesión normal: no queda nada pendiente, el dudoso no vuelve.
        assert revisar(ruta, leer=_respuestas(), hoy="2026-10-25") == 0
        # Con --dudosos sí, y al etiquetarlo pierde la marca.
        assert revisar(ruta, leer=_respuestas("0"), revisitar_dudosos=True) == 1
        _, filas = _leer_jsonl(ruta)
        assert filas[0]["label"] == 0
        assert "dudoso" not in filas[0]

    def test_un_dudoso_no_se_anexa(self, tmp_path):
        """Dudoso no es negativo: sin etiqueta no entra al golden."""
        candidatos = tmp_path / "cand.jsonl"
        golden = tmp_path / "golden.jsonl"
        _escribir(candidatos, [_candidato("a")])
        _escribir(golden, [])
        revisar(candidatos, leer=_respuestas("d"), hoy="2026-10-25")

        assert anexar(candidatos, golden) == 0

    def test_ensena_el_anuncio_y_no_las_pistas(self, tmp_path, capsys):
        """Órgano sí; `keyword_match` y la probabilidad del modelo no: el
        golden juzga a esas dos fuentes y verlas antes ancla la respuesta."""
        ruta = tmp_path / "cand.jsonl"
        _escribir(ruta, [_candidato("a", organo="Diputació de Girona")])

        revisar(ruta, leer=_respuestas("q"), hoy="2026-10-25")
        salida = capsys.readouterr().out
        assert "Diputació de Girona" in salida
        assert "Licitación a" in salida
        assert "keyword_match" not in salida
        assert "ml_proba" not in salida
        assert "estrato" not in salida


# ── Bootstrap del umbral en el informe ───────────────────────────────────────


class _ClfPorTitulo:
    """Probabilidad fija por ejemplo, leída del título: «Licitación pos-…»."""

    def predict(self, text, *, cpv=None, importe=None):
        proba = 0.9 if "pos" in text else 0.1
        return proba >= 0.5, proba


def _golden_separable(n: int) -> list[dict[str, object]]:
    filas = []
    for i in range(n):
        positivo = i % 2 == 0
        fila = _fila(f"{'pos' if positivo else 'neg'}-{i}", int(positivo))
        fila["titulo"] = f"Licitación {'pos' if positivo else 'neg'}-{i}"
        fila["split"] = "tune"
        filas.append(fila)
    return filas


class TestInformeUmbral:
    def test_un_modelo_que_separa_da_un_umbral_estable(self):
        informe = informe_umbral(_golden_separable(80), _ClfPorTitulo(), beta=1.5)
        assert informe is not None
        # Cualquier umbral en [0,30, 0,90] separa perfectamente; la rejilla
        # elige siempre el más bajo, así que no hay dispersión.
        assert informe["umbral"] == 0.30
        assert informe["sigma"] == 0.0
        assert informe["ancho_p5_p95"] == 0.0

    def test_una_sola_clase_no_da_umbral(self):
        filas = [f for f in _golden_separable(20) if f["label"] == 1]
        assert informe_umbral(filas, _ClfPorTitulo(), beta=1.5) is None

    def test_el_estado_imprime_el_bootstrap_con_modelo(self, tmp_path, capsys):
        golden = tmp_path / "golden.jsonl"
        _escribir(golden, _golden_separable(40))

        estado(golden, clf=_ClfPorTitulo())
        assert "umbral (bootstrap)  0.30" in capsys.readouterr().out

    def test_sin_modelo_lo_dice_en_vez_de_inventar(self, tmp_path, capsys):
        golden = tmp_path / "golden.jsonl"
        _escribir(golden, _golden_separable(10))

        estado(golden)
        assert "sin modelo local" in capsys.readouterr().out
