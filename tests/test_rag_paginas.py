"""F2.5 — visor de página con la cita resaltada.

La traducción de offsets absolutos del documento a índices de página es donde
está el fallo fácil: los de ``documento_pages`` van sobre el documento entero,
así que pasárselos al cliente tal cual resalta el trozo equivocado en cuanto
la cita no está en la primera página. Eso es lo que fija ``TestOffsets``.
"""

from __future__ import annotations

from typing import Any

import pytest

from services.rag import paginas as mod


@pytest.fixture
def repo_falso(monkeypatch: pytest.MonkeyPatch) -> list[dict[str, Any]]:
    """Dos páginas de un documento y una de otro de la misma licitación.

    Las páginas 1 y 2 son consecutivas: la 1 ocupa los offsets 0-10 y la 2
    empieza en el 10. Sin eso el test no distinguiría el offset absoluto del
    relativo, que es justo lo que se quiere distinguir.
    """
    filas: list[dict[str, Any]] = [
        {
            "documento_id": 7,
            "page_number": 1,
            "texto": "0123456789",
            "start_offset": 0,
            "end_offset": 10,
            "tipo": "PCAP",
            "filename": "pcap.pdf",
            "uri": "https://ejemplo.test/pcap.pdf",
        },
        {
            "documento_id": 7,
            "page_number": 2,
            "texto": "ABCDEFGHIJ",
            "start_offset": 10,
            "end_offset": 20,
            "tipo": "PCAP",
            "filename": "pcap.pdf",
            "uri": "https://ejemplo.test/pcap.pdf",
        },
        {
            "documento_id": 9,
            "page_number": 1,
            "texto": "otro documento",
            "start_offset": 0,
            "end_offset": 14,
            "tipo": "PPT",
            "filename": "ppt.pdf",
            "uri": None,
        },
    ]
    monkeypatch.setattr(mod._repo, "list_pages_by_licitacion", lambda _licitacion_id: list(filas))
    return filas


class TestLocalizacion:
    def test_devuelve_la_pagina_pedida(self, repo_falso: object) -> None:
        pagina = mod.get_pagina("EXP-1", 7, 2)
        assert pagina is not None
        assert pagina.texto == "ABCDEFGHIJ"
        assert pagina.page_number == 2

    def test_total_de_paginas_es_el_del_documento(self, repo_falso: object) -> None:
        """Y no el de la licitación entera: la navegación es dentro del PDF."""
        pagina = mod.get_pagina("EXP-1", 7, 1)
        assert pagina is not None
        assert pagina.total_paginas == 2

    def test_pagina_inexistente(self, repo_falso: object) -> None:
        assert mod.get_pagina("EXP-1", 7, 99) is None

    def test_documento_inexistente(self, repo_falso: object) -> None:
        assert mod.get_pagina("EXP-1", 1234, 1) is None

    def test_lleva_el_enlace_al_original(self, repo_falso: object) -> None:
        pagina = mod.get_pagina("EXP-1", 7, 1)
        assert pagina is not None
        assert pagina.uri == "https://ejemplo.test/pcap.pdf"
        assert pagina.tipo == "PCAP"


class TestOffsets:
    def test_offsets_de_la_primera_pagina(self, repo_falso: object) -> None:
        pagina = mod.get_pagina("EXP-1", 7, 1, inicio=2, fin=5)
        assert pagina is not None
        assert (pagina.resaltado_inicio, pagina.resaltado_fin) == (2, 5)
        assert pagina.resaltado_omitido is None
        assert pagina.texto[2:5] == "234"

    def test_offsets_absolutos_se_hacen_relativos(self, repo_falso: object) -> None:
        """El fallo que este módulo existe para no cometer.

        La cita ocupa los offsets 12-15 del **documento**; en la página 2, que
        empieza en el 10, eso es el 2-5. Sin la resta, el cliente resaltaría
        «CDE» donde toca «MNO» — o peor, se saldría del texto.
        """
        pagina = mod.get_pagina("EXP-1", 7, 2, inicio=12, fin=15)
        assert pagina is not None
        assert (pagina.resaltado_inicio, pagina.resaltado_fin) == (2, 5)
        assert pagina.texto[2:5] == "CDE"

    def test_sin_offsets_no_hay_omision_que_declarar(self, repo_falso: object) -> None:
        """Abrir la página no es pedir una cita."""
        pagina = mod.get_pagina("EXP-1", 7, 1)
        assert pagina is not None
        assert pagina.resaltado_omitido is None
        assert pagina.resaltado_inicio is None

    def test_offsets_fuera_de_rango_devuelven_pagina_completa(self, repo_falso: object) -> None:
        pagina = mod.get_pagina("EXP-1", 7, 1, inicio=0, fin=999)
        assert pagina is not None
        assert pagina.texto == "0123456789"
        assert pagina.resaltado_inicio is None
        assert pagina.resaltado_omitido == mod.MOTIVO_FUERA_DE_RANGO

    def test_offsets_de_otra_pagina_no_se_aplican_a_esta(self, repo_falso: object) -> None:
        # 12-15 es la página 2; pedirlos sobre la 1 los deja fuera de rango.
        pagina = mod.get_pagina("EXP-1", 7, 1, inicio=12, fin=15)
        assert pagina is not None
        assert pagina.resaltado_omitido == mod.MOTIVO_FUERA_DE_RANGO

    def test_offsets_invertidos(self, repo_falso: object) -> None:
        pagina = mod.get_pagina("EXP-1", 7, 1, inicio=5, fin=2)
        assert pagina is not None
        assert pagina.resaltado_omitido == mod.MOTIVO_INVERTIDOS

    def test_offsets_iguales(self, repo_falso: object) -> None:
        """Un resaltado de longitud cero no es un resaltado."""
        pagina = mod.get_pagina("EXP-1", 7, 1, inicio=3, fin=3)
        assert pagina is not None
        assert pagina.resaltado_omitido == mod.MOTIVO_INVERTIDOS

    def test_solo_uno_de_los_dos_offsets(self, repo_falso: object) -> None:
        pagina = mod.get_pagina("EXP-1", 7, 1, inicio=3)
        assert pagina is not None
        assert pagina.resaltado_omitido == mod.MOTIVO_SIN_OFFSETS

    def test_pagina_sin_start_offset_se_trata_como_cero(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Extracciones antiguas guardaron páginas sin offset de inicio."""
        monkeypatch.setattr(
            mod._repo,
            "list_pages_by_licitacion",
            lambda _l: [
                {
                    "documento_id": 1,
                    "page_number": 1,
                    "texto": "hola mundo",
                    "start_offset": None,
                    "end_offset": None,
                    "tipo": None,
                    "filename": None,
                    "uri": None,
                }
            ],
        )
        pagina = mod.get_pagina("EXP-1", 1, 1, inicio=0, fin=4)
        assert pagina is not None
        assert (pagina.resaltado_inicio, pagina.resaltado_fin) == (0, 4)


class TestAislamiento:
    def test_el_documento_se_acota_a_su_licitacion(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Un `documento_id` de otro expediente no puede leerse desde aquí.

        La comprobación se hace sobre las páginas que la licitación de la ruta
        tiene, no sobre el id suelto: si el repositorio no devuelve el
        documento para esa licitación, la respuesta es 404.
        """
        monkeypatch.setattr(mod._repo, "list_pages_by_licitacion", lambda _l: [])
        assert mod.get_pagina("EXP-DE-OTRO", 7, 1) is None
