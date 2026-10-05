"""Competencia esperada de la ficha: las piezas puras, sin BD.

El bloque al que sustituye respondía otra pregunta: los tres adjudicatarios más
frecuentes del órgano entero —de cualquier CPV y de cualquier año— con un
porcentaje que dividía lo adjudicado a cada uno entre el presupuesto de todas
las licitaciones del órgano. Lo que se fija aquí es lo que hace que la
respuesta nueva sea una respuesta:

- la cuota se calcula sobre lo adjudicado **en el mismo segmento**, y quitar a
  la propia organización no la recalcula;
- cada estimación sale del nivel más concreto **con muestra**, y lo dice;
- nada se rellena: sin dato, ``sin_datos`` o nota, nunca un cero.

Lo que exige Postgres (los niveles anidados, la ventana, la exclusión ex ante,
la paridad con la señal del score) está en ``test_competencia_esperada_sql.py``.
"""

from __future__ import annotations

from typing import Any

import pytest

from services.competitive import competencia_esperada as ce
from services.pursuit_awards import IdentidadFiscal
from services.similares import Candidato

_NIF_PROPIO = "B12345678"  # pragma: allowlist secret


def _fila_ofertas(
    *,
    cpv4: tuple[int, int, float | None, int, int, int] = (0, 0, None, 0, 0, 0),
    organo: tuple[int, int, float | None, int, int, int] = (0, 0, None, 0, 0, 0),
) -> dict[str, Any]:
    """Fila de ``ofertas_del_segmento``: (adjudicados, con dato, media, b1, b2-4, b5+)."""
    fila: dict[str, Any] = {}
    for prefijo, valores in (("cpv4", cpv4), ("organo", organo)):
        adjudicados, expedientes, media, b1, b24, b5 = valores
        fila.update(
            {
                f"{prefijo}_adjudicados": adjudicados,
                f"{prefijo}_expedientes": expedientes,
                f"{prefijo}_media": media,
                f"{prefijo}_banda_1": b1,
                f"{prefijo}_banda_2_4": b24,
                f"{prefijo}_banda_5": b5,
            }
        )
    return fila


class TestOfertas:
    def test_el_organo_con_muestra_manda(self) -> None:
        fila = _fila_ofertas(cpv4=(40, 30, 4.2, 3, 15, 12), organo=(8, 6, 2.5, 2, 4, 0))
        ofertas = ce.construir_ofertas(fila, media_global=None, tiene_cpv=True)
        assert ofertas.estimacion_nivel == "organo_cpv4"
        # Redondeo comercial: 2,5 son 3 ofertas, no las 2 del redondeo de banquero.
        assert ofertas.estimacion == 3
        assert ofertas.organo_cpv4 is not None and ofertas.organo_cpv4.expedientes == 6
        # El CPV sigue viniendo: es la cifra que explica la barra del score.
        assert ofertas.cpv4 is not None and ofertas.cpv4.media == 4.2

    def test_el_organo_sin_muestra_suficiente_no_se_publica(self) -> None:
        minimo = ce.MIN_EXPEDIENTES_ORGANO
        fila = _fila_ofertas(
            cpv4=(40, 30, 4.2, 3, 15, 12), organo=(minimo, minimo - 1, 1.0, minimo - 1, 0, 0)
        )
        ofertas = ce.construir_ofertas(fila, media_global=None, tiene_cpv=True)
        assert ofertas.organo_cpv4 is None
        assert ofertas.estimacion_nivel == "cpv4"
        assert ofertas.estimacion == 4

    def test_sin_muestra_en_el_cpv_cae_a_la_media_global_y_lo_dice(self) -> None:
        fila = _fila_ofertas(cpv4=(3, 2, 7.0, 0, 1, 1))
        ofertas = ce.construir_ofertas(fila, media_global=3.4, tiene_cpv=True)
        assert ofertas.cpv4 is None, "dos expedientes no son la media del CPV"
        assert ofertas.estimacion_nivel == "global"
        assert ofertas.media_global == 3.4
        assert ofertas.estimacion == 3

    def test_sin_ningun_dato_no_estima_y_explica(self) -> None:
        ofertas = ce.construir_ofertas(_fila_ofertas(), media_global=None, tiene_cpv=True)
        assert ofertas.estimacion is None
        assert ofertas.estimacion_nivel is None
        assert ofertas.sin_datos and "ofertas" in ofertas.sin_datos

    def test_sin_cpv_el_motivo_es_el_cpv(self) -> None:
        ofertas = ce.construir_ofertas(None, media_global=None, tiene_cpv=False)
        assert ofertas.sin_datos and "CPV" in ofertas.sin_datos

    def test_bandas_y_oferta_unica_sobre_los_expedientes_con_dato(self) -> None:
        fila = _fila_ofertas(cpv4=(20, 10, 3.0, 4, 5, 1))
        segmento = ce.construir_ofertas(fila, media_global=None, tiene_cpv=True).cpv4
        assert segmento is not None
        assert [(b.banda, b.expedientes, b.pct) for b in segmento.bandas] == [
            ("1", 4, 40.0),
            ("2-4", 5, 50.0),
            ("5+", 1, 10.0),
        ]
        assert segmento.pct_oferta_unica == 40.0
        # La cobertura se declara: 10 con dato de 20 adjudicados.
        assert (segmento.expedientes, segmento.adjudicados) == (10, 20)

    def test_nunca_estima_menos_de_una_oferta(self) -> None:
        fila = _fila_ofertas(cpv4=(5, 5, 0.2, 5, 0, 0))
        assert ce.construir_ofertas(fila, media_global=None, tiene_cpv=True).estimacion == 1


class TestElegirNivel:
    def test_el_mas_estrecho_con_muestra(self) -> None:
        minimo = ce.MIN_EXPEDIENTES_RIVALES
        nivel, suficiente = ce.elegir_nivel(
            {"organo_cpv4": minimo, "cpv4_ccaa": 50, "cpv4": 200}, con_organo=True, con_ccaa=True
        )
        assert (nivel, suficiente) == ("organo_cpv4", True)

    def test_el_organo_corto_cede_a_la_ccaa(self) -> None:
        nivel, suficiente = ce.elegir_nivel(
            {"organo_cpv4": 2, "cpv4_ccaa": 50, "cpv4": 200}, con_organo=True, con_ccaa=True
        )
        assert (nivel, suficiente) == ("cpv4_ccaa", True)

    def test_sin_ccaa_salta_al_cpv(self) -> None:
        nivel, _ = ce.elegir_nivel(
            {"organo_cpv4": 1, "cpv4_ccaa": 0, "cpv4": 9}, con_organo=True, con_ccaa=False
        )
        assert nivel == "cpv4"

    def test_sin_muestra_en_ninguno_usa_el_mas_estrecho_con_algo_y_lo_declara(self) -> None:
        nivel, suficiente = ce.elegir_nivel(
            {"organo_cpv4": 2, "cpv4_ccaa": 3, "cpv4": 4}, con_organo=True, con_ccaa=True
        )
        assert (nivel, suficiente) == ("organo_cpv4", False)

    def test_sin_nada_no_hay_nivel(self) -> None:
        assert ce.elegir_nivel(
            {"organo_cpv4": 0, "cpv4_ccaa": 0, "cpv4": 0}, con_organo=True, con_ccaa=True
        ) == (None, False)


def _rival(clave: str, importe: float, **extra: Any) -> dict[str, Any]:
    return {
        "clave": clave,
        "empresa_id": extra.get("empresa_id"),
        "nifs": extra.get("nifs", []),
        "nombre": extra.get("nombre", clave),
        "expedientes": extra.get("expedientes", 1),
        "importe": importe,
        "baja_mediana_pct": extra.get("baja"),
        "bajas_n": extra.get("bajas_n", 0),
        "ultima_adjudicacion": extra.get("ultima"),
    }


def _datos(rivales: list[dict[str, Any]], **total: Any) -> dict[str, Any]:
    return {
        "total": {
            "expedientes": total.get("expedientes", 10),
            "importe_total": total.get("importe_total", 1000.0),
            "baja_mediana_pct": total.get("baja"),
            "bajas_n": total.get("bajas_n", 0),
            "baja_oferta_minima_mediana_pct": total.get("baja_minima"),
            "ofertas_minimas_n": total.get("minimas_n", 0),
            "propia_expedientes": total.get("propia_expedientes", 0),
            "propia_importe": total.get("propia_importe", 0.0),
        },
        "rivales": rivales,
    }


class TestRivales:
    def test_la_cuota_es_sobre_lo_adjudicado_en_el_segmento(self) -> None:
        """El defecto del bloque viejo: dividía entre el presupuesto de todo el órgano."""
        rivales = ce.construir_rivales(
            _datos([_rival("A", 600.0), _rival("B", 150.0)], importe_total=1000.0),
            nivel="organo_cpv4",
            suficiente=True,
            identidad=IdentidadFiscal(),
            incumbente_clave=None,
        )
        assert [(r.nombre, r.cuota_pct) for r in rivales.items] == [("A", 60.0), ("B", 15.0)]
        assert rivales.importe_total == 1000.0

    def test_la_propia_organizacion_sale_de_la_lista_sin_recalcular_las_cuotas(self) -> None:
        identidad = IdentidadFiscal(nifs=frozenset({_NIF_PROPIO}), empresa_ids=frozenset({7}))
        rivales = ce.construir_rivales(
            _datos(
                [
                    _rival("7", 500.0, empresa_id=7),
                    # El NIF de la fila llega sin normalizar: guion, punto y minúscula.
                    _rival(_NIF_PROPIO, 100.0, nifs=["b-1234567.8"]),
                    _rival("C", 250.0),
                ],
                importe_total=1000.0,
                propia_expedientes=3,
                propia_importe=600.0,
            ),
            nivel="cpv4",
            suficiente=True,
            identidad=identidad,
            incumbente_clave=None,
        )
        assert [r.nombre for r in rivales.items] == ["C"]
        # La cuota de C sigue siendo del mercado entero, nosotros incluidos.
        assert rivales.items[0].cuota_pct == 25.0
        assert rivales.propia is not None
        assert (rivales.propia.expedientes, rivales.propia.cuota_pct) == (3, 60.0)
        assert rivales.identidad_conocida

    def test_sin_identidad_no_se_excluye_a_nadie_y_se_declara(self) -> None:
        rivales = ce.construir_rivales(
            _datos([_rival("A", 10.0)]),
            nivel="cpv4",
            suficiente=False,
            identidad=IdentidadFiscal(),
            incumbente_clave=None,
        )
        assert [r.nombre for r in rivales.items] == ["A"]
        assert not rivales.identidad_conocida
        assert not rivales.muestra_suficiente

    def test_marca_al_incumbente(self) -> None:
        rivales = ce.construir_rivales(
            _datos([_rival("A", 600.0), _rival("B", 150.0)]),
            nivel="organo_cpv4",
            suficiente=True,
            identidad=IdentidadFiscal(),
            incumbente_clave="B",
        )
        assert [r.es_incumbente for r in rivales.items] == [False, True]

    def test_como_mucho_max_rivales(self) -> None:
        rivales = ce.construir_rivales(
            _datos([_rival(str(i), 100.0 - i) for i in range(ce.MAX_RIVALES + 3)]),
            nivel="cpv4",
            suficiente=True,
            identidad=IdentidadFiscal(),
            incumbente_clave=None,
        )
        assert len(rivales.items) == ce.MAX_RIVALES

    def test_un_importe_corrupto_no_tumba_la_respuesta(self) -> None:
        rivales = ce.construir_rivales(
            _datos([_rival("A", -50.0), _rival("B", 5000.0)], importe_total=100.0),
            nivel="cpv4",
            suficiente=True,
            identidad=IdentidadFiscal(),
            incumbente_clave=None,
        )
        assert [r.cuota_pct for r in rivales.items] == [0.0, 100.0]

    def test_baja_y_fecha_de_cada_rival(self) -> None:
        rivales = ce.construir_rivales(
            _datos([_rival("A", 10.0, baja=12.3456, bajas_n=4, ultima="2026-05-02T00:00:00")]),
            nivel="cpv4",
            suficiente=True,
            identidad=IdentidadFiscal(),
            incumbente_clave=None,
        )
        rival = rivales.items[0]
        assert (rival.baja_mediana_pct, rival.bajas_n, rival.ultima_adjudicacion) == (
            12.35,
            4,
            "2026-05-02",
        )

    def test_si_solo_gana_la_propia_organizacion_lo_dice(self) -> None:
        identidad = IdentidadFiscal(nifs=frozenset({"B1"}), empresa_ids=frozenset({1}))
        rivales = ce.construir_rivales(
            _datos([_rival("1", 10.0, empresa_id=1)], propia_expedientes=1, propia_importe=10.0),
            nivel="cpv4",
            suficiente=True,
            identidad=identidad,
            incumbente_clave=None,
        )
        assert rivales.items == []
        assert rivales.sin_datos and "propia organización" in rivales.sin_datos

    def test_la_clave_de_competidor_no_se_publica(self) -> None:
        """Sin `empresa_id`, la clave es el NIF; el de un autónomo es un dato personal."""
        assert "clave" not in ce.Rival.model_fields
        assert not any("nif" in campo for campo in ce.Rival.model_fields)
        assert not any("nif" in campo for campo in ce.Incumbente.model_fields)


class TestPuja:
    def test_publica_las_medianas_con_muestra(self) -> None:
        puja = ce.construir_puja(
            _datos([], baja=12.3456, bajas_n=8, baja_minima=20.01, minimas_n=5), nivel="cpv4"
        )
        assert puja.baja_ganadora_mediana_pct == 12.35
        assert puja.baja_oferta_minima_mediana_pct == 20.01
        assert (puja.bajas_n, puja.ofertas_minimas_n) == (8, 5)
        assert puja.base == "mixta"

    def test_no_publica_la_mediana_de_dos_casos(self) -> None:
        puja = ce.construir_puja(
            _datos([], baja=12.0, bajas_n=ce.MIN_BAJAS - 1, baja_minima=20.0, minimas_n=1),
            nivel="cpv4",
        )
        assert puja.baja_ganadora_mediana_pct is None
        assert puja.baja_oferta_minima_mediana_pct is None
        # Pero sí cuántas había: el `n` explica el hueco.
        assert puja.bajas_n == ce.MIN_BAJAS - 1


def _candidato(**extra: Any) -> Candidato:
    datos: dict[str, Any] = {
        "id_externo": "EXP-2023/1",
        "titulo": "Mantenimiento SAP",
        "organo_contratacion": "Ayuntamiento",
        "cpv": "72267100",
        "importe": 100_000.0,
        "estado": "ADJ",
        "fecha_publicacion": "2023-01-10",
        "score": 0.9,
        "adjudicatario": "ALFA SA",
        "importe_adjudicado": 86_000.0,
        "fecha_adjudicacion": "2023-03-14T00:00:00",
        "baja_pct": 14.0,
        "adjudicatario_clave": "42",
        "adjudicatario_empresa_id": 42,
        "adjudicatario_nif": "A11111111",
    }
    datos.update(extra)
    return Candidato(**datos)


class TestIncumbente:
    def test_sin_predecesor_no_hay_incumbente(self) -> None:
        assert ce.construir_incumbente(None, metodo="fts", identidad=IdentidadFiscal()) is None

    def test_del_predecesor(self) -> None:
        incumbente = ce.construir_incumbente(
            _candidato(), metodo="embedding", identidad=IdentidadFiscal()
        )
        assert incumbente is not None
        assert incumbente.adjudicatario == "ALFA SA"
        assert incumbente.empresa_id == 42
        assert incumbente.fecha_adjudicacion == "2023-03-14"
        assert incumbente.metodo == "embedding"
        assert not incumbente.es_propia

    @pytest.mark.parametrize(
        "identidad",
        [
            IdentidadFiscal(nifs=frozenset({"A11111111"})),
            IdentidadFiscal(nifs=frozenset({"X"}), empresa_ids=frozenset({42})),
        ],
    )
    def test_reconoce_a_la_propia_organizacion(self, identidad: IdentidadFiscal) -> None:
        incumbente = ce.construir_incumbente(_candidato(), metodo="fts", identidad=identidad)
        assert incumbente is not None and incumbente.es_propia


def _competencia(**extra: Any) -> ce.CompetenciaEsperada:
    datos: dict[str, Any] = {
        "licitacion_id": "EXP-2026/9",
        "organo": "Ayuntamiento",
        "cpv4": "7226",
        "ccaa": "Madrid",
        "ofertas": ce.OfertasEsperadas(ventana_meses=24),
        "rivales": ce.RivalesEsperados(ventana_meses=36),
        "calculado_en": "2026-10-04T10:00:00+00:00",
    }
    datos.update(extra)
    return ce.CompetenciaEsperada(**datos)


class TestBloquePdf:
    def test_sin_nada_que_decir_se_omite_con_nota(self) -> None:
        bloque = ce.bloque_ficha(_competencia())
        assert bloque.vacio
        assert "Sin histórico comparable" in bloque.nota_vacio

    def test_con_datos_declara_universo_ventana_n_y_fecha(self) -> None:
        fila = _fila_ofertas(cpv4=(20, 12, 2.8, 4, 7, 1))
        competencia = _competencia(
            ofertas=ce.construir_ofertas(fila, media_global=None, tiene_cpv=True),
            incumbente=ce.construir_incumbente(
                _candidato(), metodo="fts", identidad=IdentidadFiscal()
            ),
            rivales=ce.construir_rivales(
                _datos([_rival("A", 600.0, nombre="ALFA SA")], expedientes=23),
                nivel="organo_cpv4",
                suficiente=True,
                identidad=IdentidadFiscal(),
                incumbente_clave="A",
            ),
            puja=ce.construir_puja(_datos([], baja=12.0, bajas_n=21), nivel="organo_cpv4"),
        )
        bloque = ce.bloque_ficha(competencia)
        etiquetas = [etiqueta for etiqueta, _ in bloque.filas]
        assert etiquetas == [
            "Ofertas esperadas",
            "Incumbente",
            "Rivales principales",
            "Baja típica del ganador",
        ]
        filas = dict(bloque.filas)
        assert filas["Ofertas esperadas"].startswith("~3 (media 2.8 en el CPV 7226")
        assert "ALFA SA" in filas["Incumbente"] and "EXP-2023/1" in filas["Incumbente"]
        assert filas["Rivales principales"] == "ALFA SA (60 %)"
        assert "12 expedientes con el dato de 20 adjudicados" in bloque.procedencia
        assert "23 expedientes adjudicados" in bloque.procedencia
        assert "últimos 24 meses" in bloque.procedencia
        assert "últimos 36 meses" in bloque.procedencia
        assert "Calculado el 2026-10-04" in bloque.procedencia
        # Ningún NIF en el papel.
        assert "A11111111" not in " ".join(valor for _, valor in bloque.filas)

    def test_sin_incumbente_lo_dice_en_vez_de_un_guion(self) -> None:
        fila = _fila_ofertas(cpv4=(20, 12, 2.8, 4, 7, 1))
        bloque = ce.bloque_ficha(
            _competencia(ofertas=ce.construir_ofertas(fila, media_global=None, tiene_cpv=True))
        )
        assert dict(bloque.filas)["Incumbente"].startswith("Sin contrato anterior")

    def test_un_fallo_del_calculo_no_tumba_el_pdf(self, monkeypatch: pytest.MonkeyPatch) -> None:
        from services import pursuits

        def _revienta(*_args: Any, **_kwargs: Any) -> None:
            raise RuntimeError("timeout")

        monkeypatch.setattr(ce, "competencia_esperada", _revienta)
        bloque = pursuits._bloque_competencia("EXP-1", 1)
        assert bloque.vacio
        assert "No se pudo calcular" in bloque.nota_vacio
