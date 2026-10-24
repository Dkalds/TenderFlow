"""OpenDocument con la biblioteca estándar y ZIP endurecido (S8, tanda 2026-10).

Los binarios se construyen **en el propio test**, en memoria: así cada caso
dice exactamente qué trae el fichero —un ``DOCTYPE``, una entrada con ``..``,
una bomba— sin depender de un fixture que haya que regenerar a mano.

Lo que fija:

- ODT, ODS y ODP se leen de ``content.xml`` sin ``odfpy``, respetando párrafos,
  encabezados y filas de tabla, y sin el texto borrado del control de cambios.
- El ``content.xml`` que declara un ``DOCTYPE`` (la puerta de las entidades) se
  rechaza antes de expandir nada.
- Un ZIP limita entradas, tamaño por entrada y total, y ratio de compresión;
  ignora las rutas con ``..`` o absolutas; marca de qué entrada sale cada
  página; y sigue sin recursión.
"""

from __future__ import annotations

import io
import zipfile

import pytest

import scraper.document_fetcher as df
from scraper.document_fetcher import (
    CONTENT_TYPE_ODP,
    CONTENT_TYPE_ODS,
    CONTENT_TYPE_ODT,
    CONTENT_TYPE_ZIP,
    DocumentFetchError,
    UnsupportedDocumentError,
    _extract_paginas,
    _resolver_content_type,
    supported_content_types,
)

_NS = (
    'xmlns:office="urn:oasis:names:tc:opendocument:xmlns:office:1.0" '
    'xmlns:text="urn:oasis:names:tc:opendocument:xmlns:text:1.0" '
    'xmlns:table="urn:oasis:names:tc:opendocument:xmlns:table:1.0" '
    'xmlns:draw="urn:oasis:names:tc:opendocument:xmlns:drawing:1.0"'
)


def _odf(cuerpo: str, *, mimetype: str = CONTENT_TYPE_ODT, prologo: str = "") -> bytes:
    """Un documento OpenDocument mínimo con *cuerpo* dentro de ``office:body``."""
    contenido = (
        f'<?xml version="1.0" encoding="UTF-8"?>{prologo}'
        f"<office:document-content {_NS}><office:body>{cuerpo}</office:body>"
        "</office:document-content>"
    )
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as z:
        # ``mimetype`` va primero y sin comprimir, como manda la especificación.
        z.writestr("mimetype", mimetype, compress_type=zipfile.ZIP_STORED)
        z.writestr("content.xml", contenido, compress_type=zipfile.ZIP_DEFLATED)
    return buf.getvalue()


def _zip(entradas: dict[str, bytes], *, comprimir: int = zipfile.ZIP_DEFLATED) -> bytes:
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as z:
        for nombre, datos in entradas.items():
            z.writestr(nombre, datos, compress_type=comprimir)
    return buf.getvalue()


def _texto(paginas: list[df.PaginaExtraida]) -> str:
    return "\n".join(p.texto for p in paginas)


# ── OpenDocument sin odfpy ──────────────────────────────────────────────────


class TestOpenDocument:
    def test_odt_respeta_parrafos_encabezados_y_espacios(self):
        odt = _odf(
            "<office:text>"
            "<text:h>PLIEGO DE PRESCRIPCIONES</text:h>"
            "<text:p>Objeto:<text:s/>mantenimiento<text:s text:c='2'/>SAP</text:p>"
            "<text:p>Plazo<text:tab/>24 meses<text:line-break/>prorrogable</text:p>"
            "<text:p/>"
            "</office:text>"
        )
        texto = _texto(_extract_paginas(odt, CONTENT_TYPE_ODT))
        lineas = texto.split("\n")
        assert lineas[0] == "PLIEGO DE PRESCRIPCIONES"  # odfpy perdía los text:h
        assert lineas[1] == "Objeto: mantenimiento  SAP"  # text:s c=2 son dos espacios
        assert "Plazo\t24 meses" in texto
        assert "prorrogable" in texto

    def test_odt_no_necesita_odfpy(self, monkeypatch):
        """La imagen de la API no trae odfpy: el ODT se lee igual."""
        real = df.importlib.import_module

        def _sin_odf(nombre: str, *args, **kwargs):
            if nombre == "odf" or nombre.startswith("odf."):
                raise ImportError("simulado")
            return real(nombre, *args, **kwargs)

        monkeypatch.setattr(df.importlib, "import_module", _sin_odf)
        odt = _odf("<office:text><text:p>Solvencia técnica</text:p></office:text>")
        assert _texto(_extract_paginas(odt, CONTENT_TYPE_ODT)) == "Solvencia técnica"

    def test_las_filas_de_tabla_son_una_linea_con_sus_celdas(self):
        odt = _odf(
            "<office:text><table:table>"
            "<table:table-row>"
            "<table:table-cell><text:p>Criterio</text:p></table:table-cell>"
            "<table:table-cell><text:p>Puntos</text:p></table:table-cell>"
            "</table:table-row>"
            "<table:table-row>"
            "<table:table-cell><text:p>Precio</text:p><text:p>(fórmula)</text:p></table:table-cell>"
            "<table:table-cell/>"
            "<table:table-cell><text:p>60</text:p></table:table-cell>"
            "</table:table-row>"
            "</table:table></office:text>"
        )
        lineas = _texto(_extract_paginas(odt, CONTENT_TYPE_ODT)).split("\n")
        assert lineas == ["Criterio | Puntos", "Precio (fórmula) | 60"]

    def test_el_texto_borrado_del_control_de_cambios_no_se_extrae(self):
        odt = _odf(
            "<office:text>"
            "<text:tracked-changes><text:changed-region><text:deletion>"
            "<text:p>importe anterior 1.000 €</text:p>"
            "</text:deletion></text:changed-region></text:tracked-changes>"
            "<text:p>Importe: 2.000 €"
            "<office:annotation><text:p>comentario interno</text:p></office:annotation>"
            "</text:p>"
            "</office:text>"
        )
        texto = _texto(_extract_paginas(odt, CONTENT_TYPE_ODT))
        assert texto == "Importe: 2.000 €"

    def test_ods_y_odp_tambien_se_leen(self):
        ods = _odf(
            "<office:spreadsheet><table:table><table:table-row>"
            "<table:table-cell><text:p>Lote 1</text:p></table:table-cell>"
            "<table:table-cell><text:p>120.000</text:p></table:table-cell>"
            "</table:table-row></table:table></office:spreadsheet>",
            mimetype=CONTENT_TYPE_ODS,
        )
        odp = _odf(
            "<office:presentation><draw:page><draw:frame><draw:text-box>"
            "<text:p>Arquitectura propuesta</text:p>"
            "</draw:text-box></draw:frame></draw:page></office:presentation>",
            mimetype=CONTENT_TYPE_ODP,
        )
        assert _texto(_extract_paginas(ods, CONTENT_TYPE_ODS)) == "Lote 1 | 120.000"
        assert _texto(_extract_paginas(odp, CONTENT_TYPE_ODP)) == "Arquitectura propuesta"

    def test_la_firma_distingue_los_tres_formatos(self):
        for mimetype in (CONTENT_TYPE_ODT, CONTENT_TYPE_ODS, CONTENT_TYPE_ODP):
            binario = _odf("<office:text/>", mimetype=mimetype)
            assert _resolver_content_type(binario, "application/octet-stream") == mimetype
            assert mimetype in supported_content_types()

    def test_un_doctype_se_rechaza_antes_de_expandir_entidades(self):
        """Billion laughs: sin DTD no hay entidades que expandir."""
        bomba = (
            '<!DOCTYPE lol [<!ENTITY a "aaaaaaaaaa"><!ENTITY b "&a;&a;&a;&a;&a;&a;&a;&a;&a;&a;">]>'
        )
        odt = _odf("<office:text><text:p>&b;</text:p></office:text>", prologo=bomba)
        with pytest.raises(DocumentFetchError, match="DOCTYPE") as exc:
            _extract_paginas(odt, CONTENT_TYPE_ODT)
        assert not isinstance(exc.value, UnsupportedDocumentError)

    def test_odt_sin_content_xml_o_corrupto_es_error(self):
        sin_contenido = _zip({"mimetype": CONTENT_TYPE_ODT.encode()})
        with pytest.raises(DocumentFetchError, match=r"content\.xml"):
            _extract_paginas(sin_contenido, CONTENT_TYPE_ODT)
        roto = _odf("<office:text><text:p>sin cerrar</office:text>")
        with pytest.raises(DocumentFetchError, match="ODT corrupto"):
            _extract_paginas(roto, CONTENT_TYPE_ODT)
        with pytest.raises(DocumentFetchError):
            _extract_paginas(b"no es un zip", CONTENT_TYPE_ODT)

    def test_odt_vacio_es_error_no_unsupported(self):
        with pytest.raises(DocumentFetchError, match="sin texto") as exc:
            _extract_paginas(_odf("<office:text/>"), CONTENT_TYPE_ODT)
        assert not isinstance(exc.value, UnsupportedDocumentError)

    def test_content_xml_bomba_se_corta_por_ratio(self, monkeypatch):
        """El ``content.xml`` pasa por el mismo tope que una entrada de ZIP."""
        monkeypatch.setattr(df, "_ZIP_RATIO_UMBRAL_BYTES", 1024)
        relleno = "<text:p>" + "a" * 400_000 + "</text:p>"
        odt = _odf(f"<office:text>{relleno}</office:text>")
        with pytest.raises(DocumentFetchError, match="ratio de compresión"):
            _extract_paginas(odt, CONTENT_TYPE_ODT)


# ── ZIP endurecido ──────────────────────────────────────────────────────────


class TestZip:
    def test_cada_entrada_lleva_su_separador_y_se_procesan_en_orden(self):
        odt = _odf("<office:text><text:p>Pliego técnico en ODT</text:p></office:text>")
        archivo = _zip({"b/anexo.odt": odt, "a/leeme.txt": b"no se procesa"})
        paginas = _extract_paginas(archivo, CONTENT_TYPE_ZIP)
        assert len(paginas) == 1
        assert paginas[0].texto.split("\n") == ["── b/anexo.odt ──", "Pliego técnico en ODT"]

    def test_las_rutas_con_traversal_o_absolutas_se_ignoran(self):
        malo = _odf("<office:text><text:p>no debe salir</text:p></office:text>")
        bueno = _odf("<office:text><text:p>sí debe salir</text:p></office:text>")
        archivo = _zip(
            {
                "../../etc/evil.odt": malo,
                "/abs/evil.odt": malo,
                "dir/../../evil.odt": malo,
                "C:\\evil.odt": malo,
                "__MACOSX/._pliego.odt": malo,
                "pliego.odt": bueno,
            }
        )
        texto = _texto(_extract_paginas(archivo, CONTENT_TYPE_ZIP))
        assert "sí debe salir" in texto
        assert "no debe salir" not in texto

    def test_las_carpetas_con_barra_invertida_de_windows_se_leen(self):
        bueno = _odf("<office:text><text:p>pliego en carpeta</text:p></office:text>")
        malo = _odf("<office:text><text:p>no debe salir</text:p></office:text>")
        archivo = _zip({"Pliegos\\PPT.odt": bueno, "..\\..\\evil.odt": malo})
        texto = _texto(_extract_paginas(archivo, CONTENT_TYPE_ZIP))
        assert "pliego en carpeta" in texto
        assert "no debe salir" not in texto

    def test_un_zip_solo_con_rutas_peligrosas_es_unsupported(self):
        malo = _odf("<office:text><text:p>x</text:p></office:text>")
        with pytest.raises(UnsupportedDocumentError):
            _extract_paginas(_zip({"../evil.odt": malo}), CONTENT_TYPE_ZIP)

    def test_zip_bomb_pequena_se_corta_por_ratio(self, monkeypatch):
        """2 MB de ceros comprimen a ~2 KB: ratio ~1000:1, muy por encima del tope."""
        monkeypatch.setattr(df, "_ZIP_RATIO_UMBRAL_BYTES", 64 * 1024)
        archivo = _zip({"pliego.pdf": b"%PDF-" + b"\x00" * 2_000_000})
        with pytest.raises(DocumentFetchError, match="ratio de compresión"):
            _extract_paginas(archivo, CONTENT_TYPE_ZIP)

    def test_el_tope_por_entrada_corta_aunque_quede_presupuesto(self, monkeypatch):
        monkeypatch.setattr(df, "_ZIP_MAX_BYTES_POR_ENTRADA", 10_000)
        archivo = _zip({"pliego.pdf": b"%PDF-" + bytes(range(256)) * 100}, comprimir=0)
        with pytest.raises(DocumentFetchError, match="descomprimido"):
            _extract_paginas(archivo, CONTENT_TYPE_ZIP)

    def test_el_tamano_declarado_excesivo_se_rechaza_sin_leer(self, monkeypatch):
        """Si la cabecera ya confiesa el exceso no hace falta descomprimir nada."""
        monkeypatch.setattr(df, "_ZIP_MAX_BYTES_POR_ENTRADA", 100)
        archivo = _zip({"pliego.pdf": b"%PDF-" + b"x" * 500})
        llamadas: list[str] = []
        original = zipfile.ZipFile.open

        def _espia(self, nombre, *args, **kwargs):
            llamadas.append(getattr(nombre, "filename", nombre))
            return original(self, nombre, *args, **kwargs)

        monkeypatch.setattr(zipfile.ZipFile, "open", _espia)
        with pytest.raises(DocumentFetchError, match="descomprimido"):
            _extract_paginas(archivo, CONTENT_TYPE_ZIP)
        assert "pliego.pdf" not in llamadas

    def test_el_zip_dentro_del_zip_no_se_abre(self):
        interior = _zip({"pliego.odt": _odf("<office:text><text:p>x</text:p></office:text>")})
        with pytest.raises(UnsupportedDocumentError):
            _extract_paginas(_zip({"anidado.zip": interior}), CONTENT_TYPE_ZIP)

    def test_el_nombre_utf8_sin_bandera_se_recupera(self):
        """Muchos compresores de Windows escriben UTF-8 sin la bandera 0x800."""
        odt = _odf("<office:text><text:p>texto</text:p></office:text>")
        buf = io.BytesIO()
        with zipfile.ZipFile(buf, "w") as z:
            info = zipfile.ZipInfo("Pliego técnico.odt")
            z.writestr(info, odt)
        crudo = bytearray(buf.getvalue())
        # Se quita la bandera UTF-8 (bit 11) de la cabecera local y la central,
        # que es lo que deja una herramienta de ZIP que no la escribe. La local es la
        # primera firma del fichero y la central la última: en medio está el
        # ODT, que es otro ZIP con sus propias firmas.
        for inicio, desplazamiento in (
            (crudo.find(b"PK\x03\x04"), 6),
            (crudo.rfind(b"PK\x01\x02"), 8),
        ):
            flags = int.from_bytes(
                crudo[inicio + desplazamiento : inicio + desplazamiento + 2], "little"
            )
            crudo[inicio + desplazamiento : inicio + desplazamiento + 2] = (
                flags & ~0x800
            ).to_bytes(2, "little")
        paginas = _extract_paginas(bytes(crudo), CONTENT_TYPE_ZIP)
        assert paginas[0].texto.startswith("── Pliego técnico.odt ──")
