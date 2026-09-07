"""F1.3 — la explicación del score en lenguaje claro.

El test que de verdad importa es :class:`TestSinCifrasInventadas`: recorre
todas las combinaciones de dimensión y origen y exige que **cada número** que
aparece en una frase se pueda rastrear hasta el desglose o hasta una señal.
Es la traducción mecánica de ADR-014 al texto: si mañana alguien añade una
frase con un porcentaje calculado sobre la marcha, falla aquí.
"""

from __future__ import annotations

import re

import pytest

from services.analytics.scoring_explicacion import (
    FLAG_EXPLICACIONES,
    HechosDeFila,
    explicar,
)

# Todas las banderas que `_score_row` puede emitir hoy, más la que añade F1.4.
# Se enumeran a mano —y no se importan— justamente para que añadir una bandera
# al scoring sin darle texto rompa este fichero.
FLAGS_DEL_SCORING = (
    "sin_importe",
    "sin_plazo",
    "sin_titulo",
    "sin_historico_competencia",
    "sin_prediccion",
    "sin_senal_tecnica",
    "fuera_de_rango",
    "organo_anula_frecuente",
)

MARGEN_ORIGENES = ("modelo", "baseline", "mixto", "sin_predicciones", "desconocido")
AFINIDAD_METODOS = ("semantic_embeddings", "keyword_cpv_fallback", "unavailable")


def _numeros(frases: list[str]) -> list[str]:
    """Todo grupo de dígitos del texto, con su decimal si lo lleva."""
    return re.findall(r"\d+(?:,\d+)?", " ".join(frases))


class TestEncabezado:
    def test_siempre_empieza_por_la_puntuacion(self) -> None:
        frases = explicar(HechosDeFila(score=82))
        assert frases[0] == "Puntúa 82 sobre 100."

    def test_una_fila_sin_ninguna_senal_no_se_queda_muda(self) -> None:
        """Sin dimensiones ni flags queda el encabezado. Nunca lista vacía."""
        assert explicar(HechosDeFila(score=0)) == ["Puntúa 0 sobre 100."]


class TestDimensiones:
    def test_importe_alto_y_bajo(self) -> None:
        alto = explicar(HechosDeFila(score=80, fraccion={"importe": 0.9}))
        bajo = explicar(HechosDeFila(score=20, fraccion={"importe": 0.1}))
        assert any("tramo alto" in f for f in alto)
        assert any("tramo bajo" in f for f in bajo)

    def test_importe_intermedio_no_genera_frase(self) -> None:
        """«Ni alto ni bajo» ocupa una de las tres líneas que se leen."""
        frases = explicar(HechosDeFila(score=50, fraccion={"importe": 0.45}))
        assert not any("tramo" in f for f in frases)

    def test_plazo_por_escalon(self) -> None:
        assert any("cómodo" in f for f in explicar(HechosDeFila(score=1, fraccion={"plazo": 1.0})))
        assert any("justo" in f for f in explicar(HechosDeFila(score=1, fraccion={"plazo": 0.5})))
        assert any("vencido" in f for f in explicar(HechosDeFila(score=1, fraccion={"plazo": 0.0})))

    @pytest.mark.parametrize(
        ("media", "esperado"),
        [(1.5, "Poca competencia"), (4.0, "Competencia media"), (8.0, "Mucha competencia")],
    )
    def test_competencia_califica_sin_cambiar_el_numero(self, media: float, esperado: str) -> None:
        frases = explicar(HechosDeFila(score=50, media_ofertas=media))
        assert any(f.startswith(esperado) for f in frases)

    def test_competencia_sin_dato_no_afirma_nada(self) -> None:
        frases = explicar(HechosDeFila(score=50, media_ofertas=None))
        assert not any("competencia" in f.lower() for f in frases)

    def test_margen_declara_su_origen(self) -> None:
        modelo = explicar(HechosDeFila(score=50, baja_esperada=0.12, margen_origen="modelo"))
        historico = explicar(HechosDeFila(score=50, baja_esperada=0.12, margen_origen="baseline"))
        assert any("según el modelo de baja" in f for f in modelo)
        assert any("según el histórico del CPV" in f for f in historico)
        # Mismo hecho, dos procedencias: los textos no pueden ser idénticos.
        assert modelo != historico

    def test_margen_con_origen_desconocido_no_inventa_procedencia(self) -> None:
        frases = explicar(HechosDeFila(score=50, baja_esperada=0.12, margen_origen="desconocido"))
        assert any(f == "Baja esperada del 12 %." for f in frases)
        assert not any("según" in f for f in frases)

    def test_margen_apretado_se_declara(self) -> None:
        frases = explicar(HechosDeFila(score=50, baja_esperada=0.30, margen_origen="modelo"))
        assert any("margen apretado" in f for f in frases)

    def test_afinidad_declara_su_metodo(self) -> None:
        semantica = explicar(
            HechosDeFila(
                score=50, fraccion={"afinidad": 0.9}, afinidad_metodo="semantic_embeddings"
            )
        )
        palabras = explicar(
            HechosDeFila(
                score=50, fraccion={"afinidad": 0.9}, afinidad_metodo="keyword_cpv_fallback"
            )
        )
        assert any("similitud semántica" in f for f in semantica)
        assert any("coincidencia de palabras y CPV" in f for f in palabras)

    def test_afinidad_sin_metodo_no_afirma_encaje(self) -> None:
        """`unavailable` es «no se pudo medir», no «no encaja»."""
        frases = explicar(
            HechosDeFila(score=50, fraccion={"afinidad": 0.9}, afinidad_metodo="unavailable")
        )
        assert not any("perfil" in f for f in frases)

    def test_senal_tecnica(self) -> None:
        fuerte = explicar(HechosDeFila(score=50, fraccion={"senal_tecnica": 0.9}))
        debil = explicar(HechosDeFila(score=50, fraccion={"senal_tecnica": 0.1}))
        assert any("confirmada en los pliegos" in f for f in fuerte)
        assert any("Evidencia débil" in f for f in debil)

    def test_dimension_ausente_del_perfil_no_se_explica(self) -> None:
        """Afinidad sin portfolio no está en `fraccion`: no se menciona."""
        frases = explicar(HechosDeFila(score=50, fraccion={"importe": 0.9}))
        assert not any("perfil" in f for f in frases)


class TestHuecosDeclarados:
    @pytest.mark.parametrize("flag", FLAGS_DEL_SCORING)
    def test_toda_bandera_tiene_frase(self, flag: str) -> None:
        """Una penalización sin texto es una penalización invisible."""
        assert flag in FLAG_EXPLICACIONES
        frases = explicar(HechosDeFila(score=50, risk_flags=(flag,)))
        assert FLAG_EXPLICACIONES[flag] in frases

    def test_la_neutralidad_se_dice_no_se_disimula(self) -> None:
        frases = explicar(HechosDeFila(score=50, risk_flags=("sin_importe",)))
        assert any("neutral" in f for f in frases)

    def test_los_huecos_van_despues_de_las_razones(self) -> None:
        frases = explicar(
            HechosDeFila(
                score=70,
                fraccion={"importe": 0.9},
                media_ofertas=1.5,
                risk_flags=("sin_plazo",),
            )
        )
        indice_hueco = next(i for i, f in enumerate(frases) if "Sin fecha límite" in f)
        indice_razon = next(i for i, f in enumerate(frases) if "tramo alto" in f)
        assert indice_razon < indice_hueco

    def test_flag_sin_texto_no_rompe_la_respuesta(self) -> None:
        frases = explicar(HechosDeFila(score=50, risk_flags=("bandera_del_futuro",)))
        assert frases == ["Puntúa 50 sobre 100."]

    def test_orden_de_banderas_es_el_del_scoring(self) -> None:
        frases = explicar(HechosDeFila(score=10, risk_flags=("sin_plazo", "sin_importe")))
        assert frases[1] == FLAG_EXPLICACIONES["sin_plazo"]
        assert frases[2] == FLAG_EXPLICACIONES["sin_importe"]


class TestSinCifrasInventadas:
    """ADR-014 aplicado al texto: ningún número sin origen declarado."""

    @pytest.mark.parametrize("margen_origen", MARGEN_ORIGENES)
    @pytest.mark.parametrize("afinidad_metodo", AFINIDAD_METODOS)
    def test_por_dimension_y_origen(self, margen_origen: str, afinidad_metodo: str) -> None:
        hechos = HechosDeFila(
            score=73,
            fraccion={
                "importe": 0.91,
                "plazo": 1.0,
                "competencia": 0.83,
                "margen": 0.7,
                "afinidad": 0.88,
                "senal_tecnica": 0.95,
            },
            media_ofertas=2.4,
            baja_esperada=0.12,
            margen_origen=margen_origen,
            afinidad_metodo=afinidad_metodo,
        )
        frases = explicar(hechos)
        # Los únicos números publicables: el score, el 100 de la escala, la
        # media de ofertas de la señal y la baja esperada de la señal.
        permitidos = {"73", "100", "2,4", "12"}
        assert set(_numeros(frases)) <= permitidos, frases

    @pytest.mark.parametrize("flag", FLAGS_DEL_SCORING)
    def test_las_frases_de_hueco_no_llevan_cifras(self, flag: str) -> None:
        assert _numeros([FLAG_EXPLICACIONES[flag]]) == []

    def test_la_media_de_ofertas_se_publica_tal_cual(self) -> None:
        """Sin redondeos de conveniencia: 2,4 no puede salir como «dos»."""
        frases = explicar(HechosDeFila(score=50, media_ofertas=2.4))
        assert "2,4" in " ".join(frases)

    def test_los_enteros_no_arrastran_coma_cero(self) -> None:
        frases = explicar(HechosDeFila(score=50, media_ofertas=2.0))
        assert "2 ofertas" in " ".join(frases)
        assert "2,0" not in " ".join(frases)

    def test_la_baja_se_publica_como_porcentaje_entero(self) -> None:
        frases = explicar(HechosDeFila(score=50, baja_esperada=0.1234))
        assert "12 %" in " ".join(frases)


class TestFormaDeLasFrases:
    def test_toda_frase_termina_en_punto(self) -> None:
        frases = explicar(
            HechosDeFila(
                score=73,
                fraccion={"importe": 0.9, "plazo": 1.0},
                media_ofertas=2.4,
                baja_esperada=0.12,
                margen_origen="modelo",
                risk_flags=("fuera_de_rango",),
            )
        )
        assert all(f.endswith(".") for f in frases), frases

    def test_no_hay_frases_repetidas(self) -> None:
        frases = explicar(
            HechosDeFila(
                score=73,
                fraccion={"importe": 0.9, "plazo": 1.0, "senal_tecnica": 0.9},
                media_ofertas=2.4,
                baja_esperada=0.12,
                risk_flags=FLAGS_DEL_SCORING,
            )
        )
        assert len(frases) == len(set(frases))

    def test_cabe_en_una_tarjeta(self) -> None:
        """El plan promete «tres frases por tarjeta»: la parte positiva no se
        dispara aunque todas las dimensiones tengan algo que decir."""
        frases = explicar(
            HechosDeFila(
                score=90,
                fraccion={
                    "importe": 0.95,
                    "plazo": 1.0,
                    "competencia": 0.9,
                    "margen": 0.9,
                    "afinidad": 0.9,
                    "senal_tecnica": 0.9,
                },
                media_ofertas=1.5,
                baja_esperada=0.05,
                margen_origen="modelo",
                afinidad_metodo="semantic_embeddings",
            )
        )
        # Encabezado + como mucho una por dimensión.
        assert len(frases) <= 7
