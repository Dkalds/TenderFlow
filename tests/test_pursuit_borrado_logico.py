"""Borrado lógico en las tres hijas de la oportunidad (v131).

Por qué esto necesita un test estructural
-----------------------------------------
El borrado lógico se rompe por omisión, no por error: basta con que **una**
lectura de las diez se olvide del `deleted_at IS NULL` para que el usuario vea
reaparecer lo que borró. Nada en el tipado ni en el linter ve esa clase, y el
test funcional de cada endpoint pasa igual —devuelve datos correctos, sólo que
de más—.

Por eso aquí hay dos capas:

1. **Funcional**, tabla por tabla: borrar deja la fila, la esconde de todas las
   lecturas de su repositorio, y no se puede borrar dos veces.
2. **Estructural**: un barrido sobre el SQL de los tres repositorios que exige
   que toda consulta a esas tablas mencione `deleted_at`. Es el que atrapa la
   lectura nueva que alguien añada dentro de seis meses.

Y una tercera cosa que no es de borrado sino de recuperación: el adjunto
conserva su objeto en el almacén, así que volver a subir el mismo fichero lo
resucita en vez de chocar contra el `UNIQUE (blob_key)`.
"""

from __future__ import annotations

import ast
from pathlib import Path
from typing import Any
from unittest.mock import patch

import pytest

_REPO_ROOT = Path(__file__).resolve().parents[1]

#: `(módulo, tabla)` — los tres repositorios que v131 convierte a borrado lógico.
_REPOS: tuple[tuple[str, str], ...] = (
    ("db/repositories/pursuit_comments.py", "pursuit_comments"),
    ("db/repositories/pursuit_tasks.py", "pursuit_tasks"),
    ("db/repositories/pursuit_attachments.py", "pursuit_attachments"),
)

#: Lecturas que **deben** ver las filas borradas, con su motivo. Igual que las
#: exclusiones de RLS: añadir una entrada aquí es una decisión que hay que poder
#: explicar, no un atajo para callar el test.
_LECTURAS_QUE_VEN_LO_BORRADO: dict[str, str] = {
    "export_for_user": (
        "derecho de acceso RGPD: un comentario borrado lógicamente SIGUE en la "
        "base, así que omitirlo del export sería negar dato que se conserva"
    ),
    "anonymize_author": "desvincular la autoría alcanza también a lo borrado",
    "anonymize_user_references": "igual que anonymize_author, en tareas",
    "keys_de_organizacion": (
        "purga de la organización: los objetos del almacén de un adjunto "
        "borrado siguen existiendo y hay que enumerarlos para borrarlos"
    ),
    "ocupacion": (
        "el adjunto borrado sigue ocupando bytes en el bucket hasta que exista "
        "el barrido de huérfanos; contarlo como libre mentiría sobre el coste"
    ),
    "_by_idempotency_key": (
        "idempotencia: reenviar la misma clave tiene que devolver la MISMA "
        "respuesta, aunque el comentario se borrara después. Filtrar aquí haría "
        "que el reintento chocara con el índice único y devolviera un error "
        "donde antes devolvía el original"
    ),
}

#: Las altas no filtran por `deleted_at` —no hay fila todavía— salvo cuando el
#: `ON CONFLICT` tiene que decidir si resucita (adjuntos, por el `UNIQUE
#: (blob_key)`), y ahí sí lo mencionan. Se detectan por la forma del SQL y no
#: por el nombre del método, que en otro repositorio podría ser otro.
_ES_ALTA = "INSERT INTO"


def _organizacion(db_mod: Any, correo: str) -> tuple[int, int]:
    from db.repositories.organizations import OrganizationRepository
    from db.users import create_user

    user_id = create_user(email=correo, password_hash="x")  # pragma: allowlist secret
    org_id = int(OrganizationRepository().ensure_personal_organization(user_id)["id"])
    return user_id, org_id


def _pursuit(db_mod: Any, organization_id: int, user_id: int) -> int:
    with db_mod.connect() as c:
        c.execute(
            "INSERT INTO licitaciones (id_externo, titulo, fecha_extraccion) "
            "VALUES (%s, %s, %s) ON CONFLICT (id_externo) DO NOTHING",
            ("LIC-BORRADO", "Expediente", "2026-09-01T00:00:00+00:00"),
        )
        fila = c.execute(
            "INSERT INTO pursuits (licitacion_id, organization_id, responsible_user_id, "
            " identified_at, created_at, updated_at) "
            "VALUES (%s, %s, %s, %s, %s, %s) RETURNING id",
            (
                "LIC-BORRADO",
                organization_id,
                user_id,
                "2026-09-01T00:00:00+00:00",
                "2026-09-01T00:00:00+00:00",
                "2026-09-01T00:00:00+00:00",
            ),
        ).fetchone()
    return int(fila[0])


# ── 1. Comentarios ──────────────────────────────────────────────────────────


def test_el_comentario_borrado_desaparece_del_hilo_pero_no_de_la_base(tmp_db: Any) -> None:
    db_mod, _ = tmp_db
    from db.repositories.pursuit_comments import PursuitCommentRepository

    user_id, org_id = _organizacion(db_mod, "comentario@example.test")
    pursuit_id = _pursuit(db_mod, org_id, user_id)
    repo = PursuitCommentRepository()

    comentario, creado = repo.create(
        organization_id=org_id, pursuit_id=pursuit_id, author_user_id=user_id, body="Ojo al plazo"
    )
    assert creado

    assert repo.delete(org_id, pursuit_id, int(comentario["id"])) is True

    items, total = repo.list_for_pursuit(org_id, pursuit_id)
    assert items == [] and total == 0
    assert repo.get(org_id, pursuit_id, int(comentario["id"])) is None

    # La fila sigue: es lo que distingue el borrado lógico de un DELETE, y lo
    # que hace que el ledger de `pursuit_events` no quede hablando de un
    # comentario inexistente.
    with db_mod.connect_read() as c:
        fila = c.execute(
            "SELECT body, deleted_at FROM pursuit_comments WHERE id = %s",
            (comentario["id"],),
        ).fetchone()
    assert fila is not None and fila[0] == "Ojo al plazo" and fila[1] is not None


def test_borrar_un_comentario_dos_veces_no_es_un_exito_dos_veces(tmp_db: Any) -> None:
    """El segundo borrado devuelve `False`, como cuando era un DELETE.

    Sin el `deleted_at IS NULL` del `WHERE`, el `UPDATE` volvería a tocar la
    fila y el endpoint contestaría 204 a algo que ya no existía: un cambio de
    contrato que nadie pidió.
    """
    db_mod, _ = tmp_db
    from db.repositories.pursuit_comments import PursuitCommentRepository

    user_id, org_id = _organizacion(db_mod, "dos-veces@example.test")
    pursuit_id = _pursuit(db_mod, org_id, user_id)
    repo = PursuitCommentRepository()
    comentario, _ = repo.create(
        organization_id=org_id, pursuit_id=pursuit_id, author_user_id=user_id, body="x"
    )

    assert repo.delete(org_id, pursuit_id, int(comentario["id"])) is True
    assert repo.delete(org_id, pursuit_id, int(comentario["id"])) is False


def test_el_contador_de_la_ficha_no_cuenta_los_borrados(tmp_db: Any) -> None:
    """`comments_count` viaja en la oportunidad y lo pinta la pestaña.

    Es una subconsulta en otro repositorio (`db/repositories/pursuits.py`), así
    que es justo la lectura que se olvida.
    """
    db_mod, _ = tmp_db
    from db.repositories.pursuit_comments import PursuitCommentRepository
    from db.repositories.pursuits import PursuitRepository

    user_id, org_id = _organizacion(db_mod, "contador@example.test")
    pursuit_id = _pursuit(db_mod, org_id, user_id)
    repo = PursuitCommentRepository()
    uno, _ = repo.create(
        organization_id=org_id, pursuit_id=pursuit_id, author_user_id=user_id, body="uno"
    )
    repo.create(organization_id=org_id, pursuit_id=pursuit_id, author_user_id=user_id, body="dos")

    repo.delete(org_id, pursuit_id, int(uno["id"]))

    ficha = PursuitRepository().get(org_id, pursuit_id)
    assert ficha is not None
    assert int(ficha["comments_count"]) == 1


# ── 2. Tareas ───────────────────────────────────────────────────────────────


def test_la_tarea_borrada_sale_de_todas_sus_lecturas(tmp_db: Any) -> None:
    db_mod, _ = tmp_db
    from db.repositories.pursuit_tasks import PursuitTasksRepository

    user_id, org_id = _organizacion(db_mod, "tarea@example.test")
    pursuit_id = _pursuit(db_mod, org_id, user_id)
    repo = PursuitTasksRepository()

    tarea = repo.create(
        pursuit_id=pursuit_id,
        organization_id=org_id,
        titulo="Pedir el aval",
        vence="2026-10-01",
    )
    assert tarea is not None
    task_id = int(tarea["id"])

    assert repo.delete(org_id, task_id) is True

    assert repo.get(org_id, task_id) is None
    assert repo.list_by_pursuit(org_id, pursuit_id) == []
    assert repo.agenda(org_id) == []
    assert repo.siguiente_accion(org_id, pursuit_id) is None
    # Y el despachador no puede avisar de una tarea que ya nadie ve.
    assert [t["id"] for t in repo.vencen_en(fecha="2026-10-01")] == []


def test_editar_no_resucita_una_tarea_borrada(tmp_db: Any) -> None:
    db_mod, _ = tmp_db
    from db.repositories.pursuit_tasks import PursuitTasksRepository

    user_id, org_id = _organizacion(db_mod, "editar@example.test")
    pursuit_id = _pursuit(db_mod, org_id, user_id)
    repo = PursuitTasksRepository()
    tarea = repo.create(pursuit_id=pursuit_id, organization_id=org_id, titulo="Original")
    assert tarea is not None
    repo.delete(org_id, int(tarea["id"]))

    assert repo.update(org_id, int(tarea["id"]), titulo="Resucitada") is None
    with db_mod.connect_read() as c:
        fila = c.execute(
            "SELECT titulo FROM pursuit_tasks WHERE id = %s", (tarea["id"],)
        ).fetchone()
    assert fila is not None and fila[0] == "Original"


# ── 3. Adjuntos ─────────────────────────────────────────────────────────────


def _adjunto(repo: Any, pursuit_id: int, org_id: int, user_id: int, clave: str) -> dict[str, Any]:
    fila = repo.create(
        pursuit_id=pursuit_id,
        organization_id=org_id,
        blob_key=clave,
        filename="pliego.pdf",
        content_type="application/pdf",
        size_bytes=1024,
        sha256="a" * 64,
        uploaded_by_user_id=user_id,
    )
    assert fila is not None
    return dict(fila)


def test_el_adjunto_borrado_desaparece_de_la_lista(tmp_db: Any) -> None:
    db_mod, _ = tmp_db
    from db.repositories.pursuit_attachments import PursuitAttachmentsRepository

    user_id, org_id = _organizacion(db_mod, "adjunto@example.test")
    pursuit_id = _pursuit(db_mod, org_id, user_id)
    repo = PursuitAttachmentsRepository()
    adjunto = _adjunto(repo, pursuit_id, org_id, user_id, "org/1/pliego-aaa")

    assert repo.delete(int(adjunto["id"]), organization_id=org_id) == "org/1/pliego-aaa"

    assert repo.get(int(adjunto["id"]), organization_id=org_id) is None
    assert repo.list_for_pursuit(pursuit_id, organization_id=org_id) == []
    # La fila sigue, y con ella la clave del objeto: es lo que permitiría
    # restaurarlo, y lo que el barrido de huérfanos necesitará para limpiarlo.
    assert repo.keys_de_organizacion(org_id) == ["org/1/pliego-aaa"]


def test_el_objeto_del_almacen_no_se_borra(tmp_db: Any) -> None:
    """La mitad menos evidente de v131 y la que la hace reversible de verdad.

    Con el binario borrado, restaurar la fila daría una descarga rota — o sea,
    no sería restaurar.
    """
    db_mod, _ = tmp_db
    from db.repositories.pursuit_attachments import PursuitAttachmentsRepository
    from services import pursuit_attachments as svc

    user_id, org_id = _organizacion(db_mod, "almacen@example.test")
    pursuit_id = _pursuit(db_mod, org_id, user_id)
    adjunto = _adjunto(
        PursuitAttachmentsRepository(), pursuit_id, org_id, user_id, "org/1/pliego-bbb"
    )

    with patch.object(svc, "get_object_store") as almacen:
        assert svc.borrar(user_id, int(adjunto["id"]), organization_id=org_id) is True

    almacen.assert_not_called()


def test_volver_a_subir_el_mismo_fichero_lo_resucita(tmp_db: Any) -> None:
    """`blob_key` es UNIQUE y lleva la huella del contenido.

    Sin resurrección, borrar un adjunto haría que ese fichero exacto no se
    pudiera volver a subir **nunca** a esa oportunidad, con un 409 que el
    usuario no puede explicarse porque no ve nada.
    """
    db_mod, _ = tmp_db
    from db.repositories.pursuit_attachments import PursuitAttachmentsRepository

    user_id, org_id = _organizacion(db_mod, "resucita@example.test")
    pursuit_id = _pursuit(db_mod, org_id, user_id)
    repo = PursuitAttachmentsRepository()
    primero = _adjunto(repo, pursuit_id, org_id, user_id, "org/1/pliego-ccc")
    repo.delete(int(primero["id"]), organization_id=org_id)

    segundo = _adjunto(repo, pursuit_id, org_id, user_id, "org/1/pliego-ccc")
    assert int(segundo["id"]) == int(primero["id"])  # la misma fila, viva otra vez
    assert repo.list_for_pursuit(pursuit_id, organization_id=org_id) != []


def test_subir_dos_veces_un_adjunto_vivo_sigue_siendo_409(tmp_db: Any) -> None:
    """La resurrección no puede tragarse el conflicto legítimo."""
    db_mod, _ = tmp_db
    from db.repositories.pursuit_attachments import (
        PursuitAttachmentExists,
        PursuitAttachmentsRepository,
    )

    user_id, org_id = _organizacion(db_mod, "duplicado@example.test")
    pursuit_id = _pursuit(db_mod, org_id, user_id)
    repo = PursuitAttachmentsRepository()
    _adjunto(repo, pursuit_id, org_id, user_id, "org/1/pliego-ddd")

    with pytest.raises(PursuitAttachmentExists):
        _adjunto(repo, pursuit_id, org_id, user_id, "org/1/pliego-ddd")


# ── 4. Estructural: ninguna lectura se olvida del filtro ────────────────────


def _fuente_de_las_consultas(ruta: str, tabla: str) -> list[tuple[str, str]]:
    """`(método, código)` de cada `execute(...)` que toque la tabla.

    Se hace sobre el AST y no con una expresión regular sobre el módulo porque
    el SQL de este repositorio se arma concatenando cadenas: la mitad de las
    consultas nombran la tabla en una constante de módulo (`_SELECT`) y la otra
    mitad en el literal del `execute`. Mirar la llamada entera —constante
    incluida, por su nombre— es lo único que ve las dos.
    """
    fuente = (_REPO_ROOT / ruta).read_text(encoding="utf-8")
    arbol = ast.parse(fuente, filename=ruta)

    # Constantes de módulo cuyo texto nombra la tabla: usarlas es tocarla.
    constantes = {
        destino.id
        for nodo in arbol.body
        if isinstance(nodo, ast.Assign)
        for destino in nodo.targets
        if isinstance(destino, ast.Name)
        and tabla in (ast.get_source_segment(fuente, nodo.value) or "")
    }

    encontradas: list[tuple[str, str]] = []

    class _Visitante(ast.NodeVisitor):
        def __init__(self) -> None:
            self.metodo = "<módulo>"

        def visit_FunctionDef(self, nodo: ast.FunctionDef) -> None:
            anterior, self.metodo = self.metodo, nodo.name
            self.generic_visit(nodo)
            self.metodo = anterior

        def visit_Call(self, nodo: ast.Call) -> None:
            func = nodo.func
            if isinstance(func, ast.Attribute) and func.attr == "execute":
                codigo = ast.get_source_segment(fuente, nodo) or ""
                if tabla in codigo or any(c in codigo for c in constantes):
                    encontradas.append((self.metodo, codigo))
            self.generic_visit(nodo)

    _Visitante().visit(arbol)
    return encontradas


@pytest.mark.parametrize(("ruta", "tabla"), _REPOS)
def test_toda_consulta_a_la_tabla_menciona_deleted_at(ruta: str, tabla: str) -> None:
    """El guardarraíl que atrapa la lectura que alguien añada mañana.

    No comprueba que el filtro sea *correcto* —eso lo hacen los tests
    funcionales de arriba—, sino que la consulta se haya planteado la pregunta.
    Una lectura nueva sin `deleted_at` a la vista es, casi siempre, una lectura
    que enseña lo borrado.
    """
    culpables = [
        f"{metodo}: {codigo[:110]}"
        for metodo, codigo in _fuente_de_las_consultas(ruta, tabla)
        if "deleted_at" not in codigo
        and _ES_ALTA not in codigo
        and metodo not in _LECTURAS_QUE_VEN_LO_BORRADO
    ]

    assert not culpables, (
        f"Consulta(s) a `{tabla}` sin `deleted_at` en {ruta}. Desde v131 el "
        "borrado es lógico: una lectura sin el filtro le enseña al usuario lo "
        "que borró. Si esta lectura debe ver lo borrado, declarala en "
        f"_LECTURAS_QUE_VEN_LO_BORRADO con su motivo. Encontradas: {culpables}"
    )
