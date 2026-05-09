"""Tests para dashboard/utils/pdf.py — generación de PDF ejecutivo."""

from __future__ import annotations


def test_generate_pdf_basic():
    from dashboard.utils.pdf import generate_pdf

    kpis = {
        "Total licitaciones": "1,234",
        "Importe medio": "500,000 €",
        "% PYMEs": "45%",
        "HHI": "1,200",
    }
    top = [
        {
            "titulo": "Mantenimiento SAP S/4HANA",
            "organo_contratacion": "Ministerio de Hacienda",
            "importe_fmt": "2,500,000 €",
            "estado_desc": "Evaluación",
            "cpv": "72267100",
        },
        {
            "titulo": "Migración ERP",
            "organo_contratacion": "AEAT",
            "importe_fmt": "1,000,000 €",
            "estado_desc": "Publicada",
            "cpv": "72000000",
        },
    ]
    pdf_bytes = generate_pdf(
        kpis=kpis,
        filtros={"Rango": "2026-01-01 → 2026-05-01", "CCAA": "Madrid"},
        top_oportunidades=top,
    )
    assert isinstance(pdf_bytes, bytes)
    assert len(pdf_bytes) > 1000
    assert pdf_bytes[:5] == b"%PDF-"


def test_generate_pdf_empty_data():
    from dashboard.utils.pdf import generate_pdf

    pdf_bytes = generate_pdf(
        kpis={},
        filtros={},
        top_oportunidades=[],
    )
    assert pdf_bytes[:5] == b"%PDF-"


def test_generate_pdf_many_kpis():
    from dashboard.utils.pdf import generate_pdf

    kpis = {f"KPI {i}": f"{i * 100}" for i in range(9)}
    pdf_bytes = generate_pdf(
        kpis=kpis,
        filtros={},
        top_oportunidades=[],
    )
    assert pdf_bytes[:5] == b"%PDF-"
    assert len(pdf_bytes) > 500


def test_generate_pdf_with_chart():
    # Minimal valid 1x1 white PNG
    import struct
    import zlib

    from dashboard.utils.pdf import generate_pdf

    def _minimal_png() -> bytes:
        sig = b"\x89PNG\r\n\x1a\n"
        ihdr_data = struct.pack(">IIBBBBB", 1, 1, 8, 2, 0, 0, 0)
        ihdr = _chunk(b"IHDR", ihdr_data)
        raw = zlib.compress(b"\x00\xff\xff\xff")
        idat = _chunk(b"IDAT", raw)
        iend = _chunk(b"IEND", b"")
        return sig + ihdr + idat + iend

    def _chunk(chunk_type: bytes, data: bytes) -> bytes:
        c = chunk_type + data
        crc = struct.pack(">I", zlib.crc32(c) & 0xFFFFFFFF)
        return struct.pack(">I", len(data)) + c + crc

    png = _minimal_png()
    pdf_bytes = generate_pdf(
        kpis={"Test": "1"},
        filtros={},
        top_oportunidades=[],
        chart_images=[("Test chart", png)],
    )
    assert pdf_bytes[:5] == b"%PDF-"
    assert len(pdf_bytes) > 1000
