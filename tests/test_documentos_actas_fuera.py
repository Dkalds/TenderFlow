"""Las actas de la mesa (``tipo='acta'``) no entran en el pipeline de pliegos.

Contra Postgres (``tmp_db``): el filtro es SQL y solo la tabla de verdad dice
qué filas deja pasar. Spec de las puntuaciones del acta, §3.3: el acta queda
como referencia ``pending``, no la descarga la pasada nocturna ni entra en
chunks, RAG, ficha o señal tecnológica, y tampoco infla los recuentos de salud;
quien la necesita la pide por su tipo.
"""

from __future__ import annotations

import pytest

from db.database import DocumentoReferencia
from db.repositories.documentos import TIPO_ACTA, DocumentosRepository


@pytest.fixture()
def repo(tmp_db):
    _db_mod, _ = tmp_db
    return DocumentosRepository()


def _sembrar(repo: DocumentosRepository, licitacion_id: str = "EXP-ACTA") -> dict[str, int]:
    """Una licitación con un pliego ``legal`` y un ``acta``, ambos ``pending``.

    Devuelve ``{tipo: documento_id}``.
    """
    from db.database import connect

    with connect() as c:
        c.execute(
            "INSERT INTO licitaciones (id_externo, titulo, fuente, fecha_extraccion) "
            "VALUES (%s, %s, 'placsp', CURRENT_TIMESTAMP)",
            (licitacion_id, f"Contrato {licitacion_id}"),
        )
    repo.upsert_meta(
        licitacion_id,
        [
            DocumentoReferencia(
                tipo="legal",
                uri=f"https://x.example/{licitacion_id}/pcap.pdf",
                source_hash=f"{licitacion_id}-pcap",
            ),
            DocumentoReferencia(
                tipo=TIPO_ACTA,
                uri=f"https://x.example/{licitacion_id}/acta.pdf",
                source_hash=f"{licitacion_id}-acta",
            ),
        ],
    )
    ids = {str(fila["tipo"]): int(fila["id"]) for fila in repo.list_by_licitacion(licitacion_id)}
    assert set(ids) == {"legal", TIPO_ACTA}
    return ids


def _extraer(repo: DocumentosRepository, ids: dict[str, int], tipo: str) -> None:
    """Deja el documento ``extracted`` con dos páginas."""
    repo.mark_extracted(
        ids[tipo],
        texto=f"texto del {tipo}",
        sha256=f"hash-{tipo}",
        pages=[f"página 1 del {tipo}", f"página 2 del {tipo}"],
    )


def test_list_pendientes_no_elige_actas(repo):
    ids = _sembrar(repo)

    pendientes = repo.list_pendientes()

    assert [fila["id"] for fila in pendientes] == [ids["legal"]]


def test_list_extracted_without_chunks_ignora_actas(repo):
    ids = _sembrar(repo)
    _extraer(repo, ids, TIPO_ACTA)

    assert repo.list_extracted_without_chunks() == []

    _extraer(repo, ids, "legal")

    assert [fila["id"] for fila in repo.list_extracted_without_chunks()] == [ids["legal"]]


def test_list_pages_by_licitacion_por_defecto_sin_actas(repo):
    ids = _sembrar(repo)
    _extraer(repo, ids, "legal")
    _extraer(repo, ids, TIPO_ACTA)

    paginas = repo.list_pages_by_licitacion("EXP-ACTA")

    assert {fila["documento_id"] for fila in paginas} == {ids["legal"]}
    assert {fila["tipo"] for fila in paginas} == {"legal"}


def test_list_pages_by_licitacion_con_tipos_acta(repo):
    ids = _sembrar(repo)
    _extraer(repo, ids, "legal")
    _extraer(repo, ids, TIPO_ACTA)

    paginas = repo.list_pages_by_licitacion("EXP-ACTA", tipos=frozenset({TIPO_ACTA}))

    assert [(fila["documento_id"], fila["page_number"]) for fila in paginas] == [
        (ids[TIPO_ACTA], 1),
        (ids[TIPO_ACTA], 2),
    ]


def test_list_textos_by_licitacion_ignora_actas(repo):
    ids = _sembrar(repo)
    _extraer(repo, ids, "legal")
    _extraer(repo, ids, TIPO_ACTA)

    textos = repo.list_textos_by_licitacion("EXP-ACTA")

    assert [fila["id"] for fila in textos] == [ids["legal"]]


def test_list_chunks_by_licitacion_ignora_actas(repo):
    """Un acta con chunks (de antes del filtro) tampoco llega al contexto del asistente."""
    ids = _sembrar(repo)
    _extraer(repo, ids, "legal")
    _extraer(repo, ids, TIPO_ACTA)
    repo.replace_chunks(ids["legal"], ["chunk del pliego"], [[0.1] * 384])
    repo.replace_chunks(ids[TIPO_ACTA], ["chunk del acta"], [[0.2] * 384])

    chunks = repo.list_chunks_by_licitacion("EXP-ACTA")

    assert [fila["documento_id"] for fila in chunks] == [ids["legal"]]


def test_list_by_licitacion_sigue_mostrando_el_acta(repo):
    """La ficha puede mostrar el acta como documento: ese listado no filtra."""
    ids = _sembrar(repo)

    assert {int(fila["id"]) for fila in repo.list_by_licitacion("EXP-ACTA")} == set(ids.values())


def test_formato_counts_no_cuenta_actas_pendientes(repo):
    _sembrar(repo)

    fila = next(f for f in repo.formato_counts() if f["content_type"] is None)

    assert fila["pendientes"] == 1


def test_status_counts_separa_las_actas(repo):
    _sembrar(repo)

    counts = repo.status_counts()

    assert counts["pending"] == 1
    assert counts["total"] == 1
    assert counts["actas"] == 1


def test_status_counts_sin_actas_declara_la_clave_a_cero(repo):
    assert repo.status_counts()["actas"] == 0


def test_pending_signal_ignora_licitaciones_con_solo_actas(repo):
    from db.repositories.tecnologia_pliego import TecnologiaPliegoRepository

    solo_acta = _sembrar(repo, "EXP-SOLO-ACTA")
    con_pliego = _sembrar(repo, "EXP-CON-PLIEGO")
    _extraer(repo, solo_acta, TIPO_ACTA)
    _extraer(repo, con_pliego, TIPO_ACTA)
    _extraer(repo, con_pliego, "legal")

    pendientes = TecnologiaPliegoRepository().list_licitaciones_pending_signal(
        signal_version="v-test"
    )

    assert pendientes == ["EXP-CON-PLIEGO"]
