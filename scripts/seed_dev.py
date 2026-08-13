"""Seed de datos de desarrollo para Tenderflow.

Inserta datos mínimos para que el entorno local arranque sin errores 404 en la UI:
  - Schema inicializado (alembic upgrade head o init_db)
  - ~20 licitaciones de ejemplo vía upsert_licitaciones_with_history (camino real)
  - Adjudicaciones de ejemplo vía replace_adjudicaciones_batch
  - Usuario demo (demo@tenderflow.dev / demo1234!) + API key (impresa en stdout)
  - Usuario admin (admin@tenderflow.dev / admin1234!) con is_admin activo
  - Con --with-predicciones: filas sintéticas en predicciones_baja (marca demo=True)

Uso:
    python scripts/seed_dev.py
    python scripts/seed_dev.py --with-predicciones
    python scripts/seed_dev.py --reset   # trunca datos de seed previos primero

Las licitaciones de seed se identifican por fuente='seed' y llevan el prefijo
'SEED-' en id_externo, por lo que son fácilmente eliminables.
"""

from __future__ import annotations

import argparse
import secrets
import sys
from datetime import UTC, datetime, timedelta
from pathlib import Path

# Asegurar que el package root está en sys.path cuando se corre como script
_ROOT = Path(__file__).resolve().parent.parent
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))


# ── Datos de ejemplo ──────────────────────────────────────────────────────────


def _dia(offset: int) -> str:
    """Fecha ISO a ``offset`` días de hoy (negativo = pasado).

    Las fechas del seed eran literales fijos, escritos cuando "hoy" era
    principios de julio de 2026: los 12 expedientes ``ADM`` tenían entonces
    plazo futuro y los 3 ``ADJ`` plazo pasado, que es la forma que documenta
    ``web/e2e/fixtures.ts`` ("12 en ADM —puntuables— y 3 en ADJ, que el ranking
    descarta por cerrados").

    Mientras el Radar filtraba solo por estado eso daba igual. Desde que
    ``scoring_candidates`` exige además plazo vivo, cada literal que vence saca
    un expediente del ranking: el 2026-08-11 se cayó ``SEED-2026-008`` y con él
    el E2E que lo busca, y el 2026-08-26 se habría quedado vacío del todo.

    Los offsets reproducen exactamente los intervalos originales respecto a
    aquel "hoy", así que el corpus mantiene su forma —mismo orden, misma
    separación entre publicación y plazo— y deja de caducar.

    En UTC y no en hora local, como el resto del fichero: si no, sembrar y
    comprobar a distinta hora del día podría dar días distintos según la zona
    de quien lo ejecute.
    """
    return (datetime.now(UTC).date() + timedelta(days=offset)).isoformat()


_SAMPLE_LICITACIONES = [
    {
        "id_externo": "SEED-2026-001",
        "titulo": "Suministro de equipos informáticos para administración pública",
        "descripcion": "Adquisición de ordenadores, monitores y periféricos para oficinas.",
        "organo_contratacion": "Ministerio de Hacienda",
        "importe": 485000.00,
        "cpv": "30213000",
        "tipo_contrato": "Suministro",
        "estado": "ADM",
        "fecha_publicacion": _dia(-34),
        "fecha_limite": _dia(10),
        "ccaa": "Madrid",
        "provincia": "Madrid",
        "tecnologia": "hardware",
        "ml_proba": 0.82,
    },
    {
        "id_externo": "SEED-2026-002",
        "titulo": "Desarrollo y mantenimiento de plataforma de gestión documental",
        "descripcion": "Servicio de desarrollo de software para gestión de expedientes.",
        "organo_contratacion": "Junta de Andalucía",
        "importe": 1200000.00,
        "cpv": "72212000",
        "tipo_contrato": "Servicios",
        "estado": "ADM",
        "fecha_publicacion": _dia(-30),
        "fecha_limite": _dia(15),
        "ccaa": "Andalucía",
        "provincia": "Sevilla",
        "tecnologia": "software",
        "ml_proba": 0.91,
    },
    {
        "id_externo": "SEED-2026-003",
        "titulo": "Consultoría de transformación digital y cloud",
        "descripcion": "Asesoramiento estratégico para migración a infraestructura cloud.",
        "organo_contratacion": "Generalitat de Catalunya",
        "importe": 750000.00,
        "cpv": "72220000",
        "tipo_contrato": "Servicios",
        "estado": "ADM",
        "fecha_publicacion": _dia(-25),
        "fecha_limite": _dia(20),
        "ccaa": "Cataluña",
        "provincia": "Barcelona",
        "tecnologia": "cloud",
        "ml_proba": 0.87,
    },
    {
        "id_externo": "SEED-2026-004",
        "titulo": "Servicios de ciberseguridad y auditoría de sistemas",
        "descripcion": "Auditoría de seguridad, pentesting y gestión de vulnerabilidades.",
        "organo_contratacion": "Ayuntamiento de Madrid",
        "importe": 320000.00,
        "cpv": "72315000",
        "tipo_contrato": "Servicios",
        "estado": "ADJ",
        "fecha_publicacion": _dia(-51),
        "fecha_limite": _dia(-5),
        "ccaa": "Madrid",
        "provincia": "Madrid",
        "tecnologia": "seguridad",
        "ml_proba": 0.95,
    },
    {
        "id_externo": "SEED-2026-005",
        "titulo": "Mantenimiento de infraestructura de red y comunicaciones",
        "descripcion": "Gestión, monitorización y soporte de redes corporativas.",
        "organo_contratacion": "Diputación de Valencia",
        "importe": 180000.00,
        "cpv": "32412000",
        "tipo_contrato": "Servicios",
        "estado": "ADM",
        "fecha_publicacion": _dia(-20),
        "fecha_limite": _dia(27),
        "ccaa": "Comunitat Valenciana",
        "provincia": "Valencia",
        "tecnologia": "redes",
        "ml_proba": 0.76,
    },
    {
        "id_externo": "SEED-2026-006",
        "titulo": "Licencias de software de oficimática y productividad",
        "descripcion": "Adquisición de licencias corporativas para suite ofimática.",
        "organo_contratacion": "Gobierno de Aragón",
        "importe": 95000.00,
        "cpv": "48310000",
        "tipo_contrato": "Suministro",
        "estado": "ADM",
        "fecha_publicacion": _dia(-15),
        "fecha_limite": _dia(26),
        "ccaa": "Aragón",
        "provincia": "Zaragoza",
        "tecnologia": "software",
        "ml_proba": 0.68,
    },
    {
        "id_externo": "SEED-2026-007",
        "titulo": "Servicio de soporte técnico y helpdesk TIC",
        "descripcion": "Atención a usuarios, resolución de incidencias y gestión de activos TIC.",
        "organo_contratacion": "Comunidad de Madrid",
        "importe": 420000.00,
        "cpv": "72611000",
        "tipo_contrato": "Servicios",
        "estado": "ADM",
        "fecha_publicacion": _dia(-17),
        "fecha_limite": _dia(23),
        "ccaa": "Madrid",
        "provincia": "Madrid",
        "tecnologia": "soporte",
        "ml_proba": 0.79,
    },
    {
        "id_externo": "SEED-2026-008",
        "titulo": "Implantación de sistema ERP para gestión municipal",
        "descripcion": "Despliegue, configuración y formación en plataforma ERP.",
        "organo_contratacion": "Ayuntamiento de Bilbao",
        "importe": 890000.00,
        "cpv": "72263000",
        "tipo_contrato": "Servicios",
        "estado": "ADM",
        "fecha_publicacion": _dia(-13),
        "fecha_limite": _dia(36),
        "ccaa": "País Vasco",
        "provincia": "Vizcaya",
        "tecnologia": "ERP",
        "ml_proba": 0.88,
    },
    {
        "id_externo": "SEED-2026-009",
        "titulo": "Adquisición de servidores y almacenamiento para CPD",
        "descripcion": "Hardware para centro de procesamiento de datos regional.",
        "organo_contratacion": "Xunta de Galicia",
        "importe": 1100000.00,
        "cpv": "48820000",
        "tipo_contrato": "Suministro",
        "estado": "ADJ",
        "fecha_publicacion": _dia(-46),
        "fecha_limite": _dia(-10),
        "ccaa": "Galicia",
        "provincia": "A Coruña",
        "tecnologia": "infraestructura",
        "ml_proba": 0.93,
    },
    {
        "id_externo": "SEED-2026-010",
        "titulo": "Desarrollo de app móvil para servicios ciudadanos",
        "descripcion": "Aplicación iOS/Android para trámites y notificaciones administrativas.",
        "organo_contratacion": "Ajuntament de Barcelona",
        "importe": 340000.00,
        "cpv": "72212460",
        "tipo_contrato": "Servicios",
        "estado": "ADM",
        "fecha_publicacion": _dia(-10),
        "fecha_limite": _dia(31),
        "ccaa": "Cataluña",
        "provincia": "Barcelona",
        "tecnologia": "móvil",
        "ml_proba": 0.84,
    },
    {
        "id_externo": "SEED-2026-011",
        "titulo": "Servicios de impresión y gestión documental centralizada",
        "descripcion": "Renting de equipos multifunción y software de gestión de impresión.",
        "organo_contratacion": "Junta de Extremadura",
        "importe": 145000.00,
        "cpv": "79810000",
        "tipo_contrato": "Servicios",
        "estado": "ADM",
        "fecha_publicacion": _dia(-7),
        "fecha_limite": _dia(34),
        "ccaa": "Extremadura",
        "provincia": "Badajoz",
        "tecnologia": "impresion",
        "ml_proba": 0.61,
    },
    {
        "id_externo": "SEED-2026-012",
        "titulo": "Plataforma de videoconferencia y colaboración remota",
        "descripcion": "Licencias y soporte para herramientas de trabajo en remoto.",
        "organo_contratacion": "Govern de les Illes Balears",
        "importe": 78000.00,
        "cpv": "64216000",
        "tipo_contrato": "Servicios",
        "estado": "ADM",
        "fecha_publicacion": _dia(-5),
        "fecha_limite": _dia(41),
        "ccaa": "Illes Balears",
        "provincia": "Palma",
        "tecnologia": "comunicaciones",
        "ml_proba": 0.72,
    },
    {
        "id_externo": "SEED-2026-013",
        "titulo": "Auditoría y certificación ISO 27001 de sistemas de información",
        "descripcion": "Proceso de certificación de seguridad de la información.",
        "organo_contratacion": "Ministerio de Defensa",
        "importe": 62000.00,
        "cpv": "79212200",
        "tipo_contrato": "Servicios",
        "estado": "ADJ",
        "fecha_publicacion": _dia(-41),
        "fecha_limite": _dia(-15),
        "ccaa": "Madrid",
        "provincia": "Madrid",
        "tecnologia": "seguridad",
        "ml_proba": 0.97,
    },
    {
        "id_externo": "SEED-2026-014",
        "titulo": "Solución de backup y recuperación ante desastres",
        "descripcion": "Infraestructura y software de backup para continuidad de negocio.",
        "organo_contratacion": "Gobierno de Canarias",
        "importe": 230000.00,
        "cpv": "72253200",
        "tipo_contrato": "Servicios",
        "estado": "ADM",
        "fecha_publicacion": _dia(-4),
        "fecha_limite": _dia(46),
        "ccaa": "Canarias",
        "provincia": "Las Palmas",
        "tecnologia": "backup",
        "ml_proba": 0.81,
    },
    {
        "id_externo": "SEED-2026-015",
        "titulo": "Formación en ciberseguridad para empleados públicos",
        "descripcion": "Cursos online y presenciales de concienciación en seguridad TIC.",
        "organo_contratacion": "Instituto Nacional de Administración Pública",
        "importe": 55000.00,
        "cpv": "80533100",
        "tipo_contrato": "Servicios",
        "estado": "ADM",
        "fecha_publicacion": _dia(-2),
        "fecha_limite": _dia(51),
        "ccaa": "Madrid",
        "provincia": "Madrid",
        "tecnologia": "formacion",
        "ml_proba": 0.69,
    },
]

# Las fechas van en `_dia()` por el mismo motivo que las de las licitaciones,
# y además por uno propio: cada adjudicación pertenece a uno de los tres
# expedientes ``ADJ``, cuyo plazo ya se mueve con el calendario. Dejarlas fijas
# las descolgaba de su licitación un día más cada día, hasta el absurdo de
# adjudicar un contrato antes de que cerrara su propio plazo de presentación
# (el 2026-08-12 ya iban 37, 31 y 33 días por delante). Los offsets conservan
# la separación original entre plazo y adjudicación: +1, +7 y +5 días.
_SAMPLE_ADJUDICACIONES = [
    # ADJ-004 — plazo en _dia(-5)
    {
        "licitacion_id": "SEED-2026-004",
        "adjudicatario": "SecureTech Solutions S.L.",
        "importe": 310000.00,
        "fecha": _dia(-4),
    },
    # ADJ-009 — plazo en _dia(-10)
    {
        "licitacion_id": "SEED-2026-009",
        "adjudicatario": "Servidores Ibéricos S.A.",
        "importe": 1050000.00,
        "fecha": _dia(-3),
    },
    # ADJ-013 — plazo en _dia(-15)
    {
        "licitacion_id": "SEED-2026-013",
        "adjudicatario": "CertISO Consultoría",
        "importe": 58000.00,
        "fecha": _dia(-10),
    },
]


# ── Helpers ───────────────────────────────────────────────────────────────────


def _build_licitacion(d: dict) -> object:
    from db.database import Licitacion

    now = datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")
    return Licitacion(
        id_externo=d["id_externo"],
        titulo=d["titulo"],
        descripcion=d.get("descripcion"),
        organo_contratacion=d.get("organo_contratacion"),
        importe=d.get("importe"),
        cpv=d.get("cpv"),
        tipo_contrato=d.get("tipo_contrato"),
        estado=d.get("estado"),
        fecha_publicacion=d.get("fecha_publicacion"),
        fecha_limite=d.get("fecha_limite"),
        ccaa=d.get("ccaa"),
        provincia=d.get("provincia"),
        tecnologia=d.get("tecnologia"),
        ml_proba=d.get("ml_proba"),
        fuente="seed",
        fecha_extraccion=now,
    )


def _build_adjudicacion(d: dict) -> object:
    from db.database import Adjudicacion

    # Los nombres del dict de ejemplo (`adjudicatario`, `importe`, `fecha`) no
    # son los de la dataclass: se traducen aquí en vez de renombrar los datos,
    # que es como los lee quien edita el seed.
    return Adjudicacion(
        licitacion_id=d["licitacion_id"],
        nombre=d["adjudicatario"],
        importe_adjudicado=d.get("importe"),
        fecha_adjudicacion=d.get("fecha"),
    )


# ── Pasos del seed ────────────────────────────────────────────────────────────


def step_init_db() -> None:
    """Inicializa el schema (idempotente)."""
    from db.database import init_db

    init_db()
    print("[seed] Schema inicializado (init_db OK)")


def step_reset(verbose: bool = True) -> None:
    """Elimina datos de seed previos (fuente='seed' + predicciones demo)."""
    from db.database import connect

    with connect() as c:
        # predicciones primero (FK)
        c.execute(
            "DELETE FROM predicciones_baja WHERE licitacion_id IN "
            "(SELECT id_externo FROM licitaciones WHERE fuente='seed')"
        )
        c.execute("DELETE FROM adjudicaciones WHERE licitacion_id LIKE 'SEED-%'")
        c.execute("DELETE FROM licitaciones WHERE fuente='seed'")
    if verbose:
        print("[seed] Datos de seed previos eliminados")


def step_licitaciones() -> int:
    """Upsert de licitaciones de ejemplo usando el camino real."""
    from db.database import upsert_licitaciones_with_history

    items = [_build_licitacion(d) for d in _SAMPLE_LICITACIONES]
    result = upsert_licitaciones_with_history(items, "seed")
    # `inserted`/`modified`/`unchanged` son listas de id_externo, no conteos:
    # sumarlas concatenaba y el mensaje escupía los 15 ids tres veces.
    nuevas, actualizadas, iguales = (
        len(result.inserted),
        len(result.modified),
        len(result.unchanged),
    )
    total = nuevas + actualizadas + iguales
    print(
        f"[seed] Licitaciones: {nuevas} nuevas, "
        f"{actualizadas} actualizadas, {iguales} sin cambios ({total} total)"
    )
    return total


def step_adjudicaciones() -> None:
    """Inserta adjudicaciones de ejemplo usando replace_adjudicaciones_batch."""
    from db.database import Adjudicacion, replace_adjudicaciones_batch

    by_licitacion: dict[str, list[Adjudicacion]] = {}
    for d in _SAMPLE_ADJUDICACIONES:
        adj = _build_adjudicacion(d)
        by_licitacion.setdefault(d["licitacion_id"], []).append(adj)  # type: ignore[arg-type]
    replace_adjudicaciones_batch(by_licitacion)
    total = sum(len(v) for v in by_licitacion.values())
    print(f"[seed] Adjudicaciones: {total} insertadas")


def step_usuario_demo() -> tuple[int, str]:
    """Crea usuario demo y devuelve (user_id, raw_api_key).

    Idempotente: si el usuario ya existe lo reutiliza.
    """
    import argon2

    from db.database import connect
    from db.users import create_user, get_user_by_email

    email = "demo@tenderflow.dev"
    existing = get_user_by_email(email)
    if existing:
        user_id: int = int(existing["id"])
        print(f"[seed] Usuario demo ya existe (id={user_id})")
    else:
        ph = argon2.PasswordHasher()
        password_hash = ph.hash("demo1234!")
        user_id = create_user(
            email=email,
            password_hash=password_hash,
            display_name="Demo User",
        )
        print(f"[seed] Usuario demo creado (id={user_id}, email={email})")

    # Crear API key
    raw_key = f"tf_dev_{secrets.token_urlsafe(24)}"
    import hashlib

    key_hash = hashlib.sha256(raw_key.encode()).hexdigest()
    with connect() as c:
        from db.database import now_utc_iso

        c.execute(
            "INSERT INTO api_keys (key_hash, name, created_at, is_active) "
            "VALUES (%s, %s, %s, 1) ON CONFLICT (key_hash) DO NOTHING",
            (key_hash, "seed-demo-key", now_utc_iso()),
        )
    print(f"[seed] API key demo: {raw_key}")
    return user_id, raw_key


def step_usuario_admin() -> int:
    """Crea el usuario admin de desarrollo y devuelve su ``user_id``.

    Los tests E2E necesitan un usuario con ``is_admin`` para ejercitar las rutas
    de administración por el camino de éxito: el usuario demo no es admin, así
    que sin este segundo usuario esas páginas solo se pueden verificar en su
    estado "Acceso restringido". El fuzzer del contrato API usa la misma cuenta
    como dueña de su clave para alcanzar los endpoints con scope ``admin``.

    Idempotente: si el usuario ya existe lo reutiliza y se limita a re-aplicar
    el flag.
    """
    import argon2

    from db.users import create_user, get_user_by_email, set_admin_by_email

    email = "admin@tenderflow.dev"
    existing = get_user_by_email(email)
    if existing:
        user_id: int = int(existing["id"])
        print(f"[seed] Usuario admin ya existe (id={user_id})")
    else:
        ph = argon2.PasswordHasher()
        user_id = create_user(
            email=email,
            password_hash=ph.hash("admin1234!"),
            display_name="Admin User",
        )
        print(f"[seed] Usuario admin creado (id={user_id}, email={email})")

    set_admin_by_email(email, is_admin=True)
    return user_id


def step_predicciones(licitacion_ids: list[str]) -> None:
    """Inserta filas sintéticas en predicciones_baja para los ids dados."""
    from db.database import connect, now_utc_iso

    now = now_utc_iso()
    rows = [
        (lid, 0.05 + i * 0.03, 0.12 + i * 0.03, 0.22 + i * 0.03, 0, now)
        for i, lid in enumerate(licitacion_ids)
    ]
    with connect() as c:
        c.executemany(
            "INSERT INTO predicciones_baja "
            "(licitacion_id, p10, p50, p90, model_version, computed_at) "
            "VALUES (%s, %s, %s, %s, %s, %s) "
            "ON CONFLICT (licitacion_id) DO UPDATE SET "
            "p10 = EXCLUDED.p10, p50 = EXCLUDED.p50, p90 = EXCLUDED.p90, "
            "model_version = EXCLUDED.model_version, computed_at = EXCLUDED.computed_at",
            rows,
        )
    print(f"[seed] Predicciones demo insertadas: {len(rows)} filas")


# ── Entry point ───────────────────────────────────────────────────────────────


def main() -> int:
    parser = argparse.ArgumentParser(description="Seed de datos de desarrollo")
    parser.add_argument(
        "--with-predicciones",
        action="store_true",
        help="Insertar filas sintéticas en predicciones_baja (mata el 404 de la UI)",
    )
    parser.add_argument(
        "--reset",
        action="store_true",
        help="Eliminar datos de seed previos antes de insertar",
    )
    args = parser.parse_args()

    print("== Tenderflow seed_dev ==\n")

    try:
        step_init_db()

        if args.reset:
            step_reset()

        n = step_licitaciones()
        step_adjudicaciones()
        step_usuario_demo()
        step_usuario_admin()

        if args.with_predicciones:
            ids = [d["id_externo"] for d in _SAMPLE_LICITACIONES]
            step_predicciones(ids)

        print(
            f"\n[seed] Completado: {n} licitaciones de ejemplo listas.\n"
            "       Arranca la API con `make api` y accede a http://localhost:8080/docs"
        )
        if args.with_predicciones:
            print("       Predicciones demo disponibles en /api/v1/predicciones/baja")
        return 0

    except Exception as exc:
        print(f"\n[seed] ERROR: {exc}", file=sys.stderr)
        import traceback

        traceback.print_exc()
        return 1


if __name__ == "__main__":
    sys.exit(main())
