"""Tests de la herramienta de etiquetado del golden set.

Lo que importa fijar aquí no es la interacción por teclado sino las dos cosas
que, si fallan, corrompen el único conjunto con juicio humano del repo: que
anexar no cuela filas sin etiquetar ni duplica ids, y que el informe de estado
cuenta lo mismo que ``services.ml_eval`` contaría.
"""

from __future__ import annotations

import json

from scripts.revisar_golden_candidates import _escribir_jsonl, _leer_jsonl, anexar, estado


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
