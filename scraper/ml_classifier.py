"""Clasificador ML para detección de licitaciones SAP.

Complementa el filtro por keywords con un modelo TF-IDF + LogisticRegression
entrenado sobre los propios datos de la base de datos.

Estrategia de etiquetado:
  - Positivos: licitaciones que ya pasaron el filtro de keywords (raw_keywords IS NOT NULL)
  - Negativos: licitaciones con CPV fuera del rango TI/software (no 48xxx ni 72xxx)
    y sin keywords SAP — muestra balanceada automáticamente.

Uso:
    # Entrenar (una vez, o periódicamente):
    python -m scraper.ml_classifier train

    # En el pipeline (predicción):
    from scraper.ml_classifier import SAPClassifier
    clf = SAPClassifier.load()
    is_sap, confidence = clf.predict("Mantenimiento del sistema ERP corporativo")
"""

from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING, Any

from observability.logging import get_logger

if TYPE_CHECKING:
    import pandas as pd

log = get_logger(__name__)

# Ruta del modelo serializado (formato joblib, extensión .pkl por compatibilidad)
_MODEL_PATH = Path(__file__).parents[1] / "data" / "models" / "sap_classifier.pkl"

# Umbral de confianza para clasificar como SAP sin keywords
CONFIDENCE_THRESHOLD = 0.70

# Número mínimo de ejemplos para entrenar
MIN_TRAIN_SAMPLES = 50


class SAPClassifier:
    """Pipeline TF-IDF + LogisticRegression para detección de licitaciones SAP."""

    def __init__(self) -> None:
        from sklearn.feature_extraction.text import TfidfVectorizer
        from sklearn.linear_model import LogisticRegression
        from sklearn.pipeline import Pipeline
        from sklearn.preprocessing import MaxAbsScaler

        self.pipeline = Pipeline(
            [
                (
                    "tfidf",
                    TfidfVectorizer(
                        ngram_range=(1, 2),
                        max_features=30_000,
                        sublinear_tf=True,
                        min_df=2,
                        analyzer="word",
                        strip_accents="unicode",
                    ),
                ),
                ("scaler", MaxAbsScaler()),
                (
                    "clf",
                    LogisticRegression(
                        C=1.0,
                        max_iter=500,
                        class_weight="balanced",
                        solver="lbfgs",
                        random_state=42,
                    ),
                ),
            ]
        )
        self._trained = False

    # ── Entrenamiento ─────────────────────────────────────────────────────

    def train(self, df: pd.DataFrame) -> dict[str, Any]:
        """Entrena el clasificador con datos de la BD.

        Args:
            df: DataFrame con columnas titulo, descripcion, raw_keywords, cpv.

        Returns:
            Métricas de evaluación (accuracy, f1, n_train, n_test).
        """
        import numpy as np
        from sklearn.metrics import accuracy_score, f1_score
        from sklearn.model_selection import train_test_split

        texts, labels = _build_dataset(df)
        if len(texts) < MIN_TRAIN_SAMPLES:
            log.warning(
                "ml_classifier.insufficient_data",
                n=len(texts),
                min_required=MIN_TRAIN_SAMPLES,
            )
            return {"error": "insufficient_data", "n_samples": len(texts)}

        n_pos = int(sum(1 for label in labels if label == 1))
        n_neg = len(labels) - n_pos
        if len(set(labels)) < 2:
            log.warning(
                "ml_classifier.single_class",
                n_positive=n_pos,
                n_negative=n_neg,
                hint="Se necesitan ejemplos negativos (CPV fuera de 48xxx/72xxx sin keywords SAP).",
            )
            return {"error": "single_class", "n_positive": n_pos, "n_negative": n_neg}

        X_train, X_test, y_train, y_test = train_test_split(
            texts, labels, test_size=0.2, random_state=42, stratify=labels
        )
        self.pipeline.fit(X_train, y_train)
        self._trained = True

        y_pred = self.pipeline.predict(X_test)
        acc = float(accuracy_score(y_test, y_pred))
        f1 = float(f1_score(y_test, y_pred, zero_division=0))
        n_pos = int(np.sum(labels))
        n_neg = len(labels) - n_pos

        metrics = {
            "accuracy": round(acc, 4),
            "f1": round(f1, 4),
            "n_train": len(X_train),
            "n_test": len(X_test),
            "n_positive": n_pos,
            "n_negative": n_neg,
        }
        log.info("ml_classifier.trained", **metrics)
        return metrics

    def predict(self, text: str) -> tuple[bool, float]:
        """Predice si un texto corresponde a una licitación SAP.

        Args:
            text: Texto combinado (título + descripción).

        Returns:
            (es_sap, confianza) — confianza en [0, 1].
        """
        if not self._trained:
            raise RuntimeError("Clasificador no entrenado. Llama a train() o load() primero.")
        proba = self.pipeline.predict_proba([text])[0]
        # proba[1] = P(SAP)
        confidence = float(proba[1])
        return confidence >= CONFIDENCE_THRESHOLD, confidence

    def predict_batch(self, texts: list[str]) -> list[tuple[bool, float]]:
        """Predicción en batch (más eficiente que llamadas individuales)."""
        if not self._trained:
            raise RuntimeError("Clasificador no entrenado.")
        probas = self.pipeline.predict_proba(texts)
        return [(float(p[1]) >= CONFIDENCE_THRESHOLD, float(p[1])) for p in probas]

    # ── Persistencia ──────────────────────────────────────────────────────

    def save(self, path: Path | None = None) -> Path:
        """Serializa el modelo a disco usando joblib (más seguro que pickle)."""
        import joblib

        target = path or _MODEL_PATH
        target.parent.mkdir(parents=True, exist_ok=True)
        joblib.dump(self, target, compress=3)
        log.info("ml_classifier.saved", path=str(target))
        return target

    @classmethod
    def ensure_downloaded(
        cls,
        path: Path | None = None,
        repo: str = "Dkalds/Licitaciones_sap_SP",
        asset_name: str = "sap_classifier.pkl",
    ) -> bool:
        """Descarga el modelo desde el último GitHub Release si no existe localmente.

        Usa GITHUB_TOKEN del entorno si está disponible (necesario para repos privados
        y siempre disponible en GitHub Actions via secrets.GITHUB_TOKEN).

        Returns:
            True si el modelo está disponible (ya existía o se descargó correctamente).
            False si no se pudo descargar (sin acceso a red, sin releases, etc.).
        """
        import json
        import os
        import urllib.request

        target = path or _MODEL_PATH
        if target.exists():
            log.info("ml_classifier.model_already_local", path=str(target))
            return True

        github_token = os.environ.get("GITHUB_TOKEN", "")
        auth_header = {"Authorization": f"Bearer {github_token}"} if github_token else {}

        # Obtener la URL del asset desde la GitHub API
        api_url = f"https://api.github.com/repos/{repo}/releases/latest"
        try:
            req = urllib.request.Request(  # noqa: S310
                api_url,
                headers={
                    "Accept": "application/vnd.github+json",
                    "User-Agent": "licitaciones-sap",
                    **auth_header,
                },
            )
            with urllib.request.urlopen(req, timeout=15) as resp:  # noqa: S310
                release = json.loads(resp.read())
        except Exception as e:
            log.warning("ml_classifier.release_fetch_failed", error=str(e))
            return False

        asset_id = None
        for asset in release.get("assets", []):
            if asset["name"] == asset_name:
                asset_id = asset["id"]
                break

        if not asset_id:
            log.warning(
                "ml_classifier.asset_not_found", asset=asset_name, release=release.get("tag_name")
            )
            return False

        # Para repos privados, descargar via API con Accept: application/octet-stream
        download_url = f"https://api.github.com/repos/{repo}/releases/assets/{asset_id}"
        target.parent.mkdir(parents=True, exist_ok=True)
        try:
            log.info("ml_classifier.downloading_model", asset_id=asset_id, dest=str(target))
            dl_req = urllib.request.Request(  # noqa: S310
                download_url,
                headers={
                    "Accept": "application/octet-stream",
                    "User-Agent": "licitaciones-sap",
                    **auth_header,
                },
            )
            with urllib.request.urlopen(dl_req, timeout=60) as resp:  # noqa: S310
                target.write_bytes(resp.read())
            log.info("ml_classifier.model_downloaded", path=str(target))
            return True
        except Exception as e:
            log.warning("ml_classifier.download_failed", error=str(e))
            if target.exists():
                target.unlink()
            return False

    @classmethod
    def load(cls, path: Path | None = None) -> SAPClassifier:
        """Carga un modelo serializado con joblib. Lanza FileNotFoundError si no existe."""
        import joblib

        target = path or _MODEL_PATH
        obj = joblib.load(target)
        if not isinstance(obj, cls):
            raise TypeError(f"El archivo no contiene un SAPClassifier: {type(obj)}")
        log.info("ml_classifier.loaded", path=str(target))
        return obj

    @classmethod
    def is_available(cls, path: Path | None = None) -> bool:
        """True si existe un modelo entrenado en disco."""
        return (path or _MODEL_PATH).exists()


# ── Funciones auxiliares ──────────────────────────────────────────────────────


def _build_dataset(df: pd.DataFrame) -> tuple[list[str], list[int]]:
    """Construye el dataset de entrenamiento desde el DataFrame.

    Positivos: raw_keywords IS NOT NULL (coincidió con keywords SAP).
    Negativos: raw_keywords IS NULL + CPV fuera del rango TI, balanceados.
    """
    import numpy as np

    text_col = (df["titulo"].fillna("") + " " + df["descripcion"].fillna("")).str.strip()

    mask_pos = df["raw_keywords"].notna() & (df["raw_keywords"] != "")
    mask_neg_cpv = df["cpv"].notna() & ~(
        df["cpv"].str.startswith("48") | df["cpv"].str.startswith("72")
    )
    mask_neg = ~mask_pos & mask_neg_cpv

    pos_texts = text_col[mask_pos].tolist()
    neg_texts = text_col[mask_neg].tolist()

    # Balancear: máx. 2x positivos en negativos
    max_neg = min(len(neg_texts), len(pos_texts) * 2)
    if max_neg < len(neg_texts):
        rng = np.random.default_rng(42)
        idx = rng.choice(len(neg_texts), max_neg, replace=False)
        neg_texts = [neg_texts[i] for i in idx]

    texts = pos_texts + neg_texts
    labels = [1] * len(pos_texts) + [0] * len(neg_texts)
    return texts, labels


def seed_negatives(
    year: int | None = None,
    month: int | None = None,
    max_negatives: int = 2000,
) -> dict[str, int]:
    """Descarga el bulk de un mes y persiste licitaciones con CPV no-TI como negativos.

    Estas licitaciones se guardan con raw_keywords=NULL para que el entrenamiento ML
    las use como ejemplos negativos.

    Args:
        year: Año del bulk a descargar (defecto: mes anterior).
        month: Mes del bulk a descargar (defecto: mes anterior).
        max_negatives: Máximo de negativos a insertar (para no inflar la BD).

    Returns:
        {"downloaded": N, "inserted": M, "skipped_ti": K, "already_exists": J}
    """
    from datetime import UTC, datetime

    from dateutil.relativedelta import relativedelta

    from db.database import init_db
    from scraper.bulk_downloader import download_month, iter_xml_files
    from scraper.codice_parser import (  # type: ignore[attr-defined]
        _text,
        parse_entry_unfiltered,
    )

    if year is None or month is None:
        prev = datetime.now(UTC).date() - relativedelta(months=1)
        year = year or prev.year
        month = month or prev.month

    log.info("seed_negatives.start", year=year, month=month, max_negatives=max_negatives)
    init_db()

    zip_path = download_month(year, month, force=False)
    if zip_path is None:
        log.warning("seed_negatives.no_zip", year=year, month=month)
        return {"downloaded": 0, "inserted": 0, "skipped_ti": 0, "already_exists": 0}

    # CPV prefijos que consideramos TI/software (positivos en potencia → excluir)
    _TI_PREFIXES = ("48", "72")

    downloaded = 0
    skipped_ti = 0
    rows_to_insert: list[tuple] = []

    for _filename, content in iter_xml_files(zip_path):
        if len(rows_to_insert) >= max_negatives:
            break
        try:
            from lxml import etree

            parser = etree.XMLParser(
                huge_tree=False, recover=True, resolve_entities=False, no_network=True
            )
            root = etree.fromstring(content, parser=parser)
            for entry in root.iter("{http://www.w3.org/2005/Atom}entry"):
                if len(rows_to_insert) >= max_negatives:
                    break
                try:
                    # Filtrar por CPV antes de parsear completamente
                    cfs = "./cacext:ContractFolderStatus"
                    project_xp = f"{cfs}/cac:ProcurementProject"
                    cpv_raw = _text(
                        entry,
                        f"{project_xp}/cac:RequiredCommodityClassification"
                        f"/cbc:ItemClassificationCode",
                    )
                    if cpv_raw and any(cpv_raw.startswith(p) for p in _TI_PREFIXES):
                        skipped_ti += 1
                        continue

                    lic = parse_entry_unfiltered(entry)
                    if lic is None:
                        continue
                    downloaded += 1
                    rows_to_insert.append(
                        (
                            lic.id_externo,
                            lic.titulo,
                            lic.descripcion,
                            lic.organo_contratacion,
                            lic.importe,
                            lic.moneda,
                            lic.cpv,
                            lic.tipo_contrato,
                            lic.estado,
                            lic.fecha_publicacion,
                            lic.fecha_actualizacion_fuente,
                            lic.url,
                            lic.provincia,
                            lic.nuts_code,
                            lic.ccaa,
                            lic.duracion_valor,
                            lic.duracion_unidad,
                            lic.fecha_inicio,
                            lic.fecha_fin,
                            lic.prorroga_descripcion,
                        )
                    )
                except Exception:
                    log.debug("seed_negatives.entry_error")
        except Exception:
            log.debug("seed_negatives.file_error")

    # Bulk insert en una sola transacción usando sqlite3 nativo (evita overhead libsql)
    inserted = 0
    already_exists = 0
    if rows_to_insert:
        import sqlite3

        from config import settings as _settings

        db_file = str(_settings.DB_PATH)
        with sqlite3.connect(db_file) as sqlite_conn:
            sqlite_conn.execute("PRAGMA journal_mode=WAL")
            sqlite_conn.execute("PRAGMA busy_timeout=5000")
            # Detect available columns to handle schema version differences
            existing_cols = {
                r[1] for r in sqlite_conn.execute("PRAGMA table_info(licitaciones)").fetchall()
            }
            has_fecha_act = "fecha_actualizacion_fuente" in existing_cols
            has_tecnologia = "tecnologia" in existing_cols

            for row in rows_to_insert:
                extra_cols = ""
                extra_vals = ""
                extra_params: list = []
                if has_fecha_act:
                    extra_cols += ", fecha_actualizacion_fuente"
                    extra_vals += ", ?"
                    extra_params.append(row[10])
                if has_tecnologia:
                    extra_cols += ", tecnologia"
                    extra_vals += ", NULL"
                cur = sqlite_conn.execute(
                    f"""INSERT OR IGNORE INTO licitaciones
                       (id_externo, titulo, descripcion, organo_contratacion,
                        importe, moneda, cpv, tipo_contrato, estado,
                        fecha_publicacion, fecha_extraccion, url, raw_keywords,
                        provincia, nuts_code, ccaa,
                        duracion_valor, duracion_unidad, fecha_inicio,
                        fecha_fin, prorroga_descripcion{extra_cols})
                       VALUES (?,?,?,?,?,?,?,?,?,?,datetime('now'),?,NULL,?,?,?,?,?,?,?,?{extra_vals})""",
                    (
                        row[0],  # id_externo
                        row[1],  # titulo
                        row[2],  # descripcion
                        row[3],  # organo_contratacion
                        row[4],  # importe
                        row[5],  # moneda
                        row[6],  # cpv
                        row[7],  # tipo_contrato
                        row[8],  # estado
                        row[9],  # fecha_publicacion
                        row[11],  # url
                        row[12],  # provincia
                        row[13],  # nuts_code
                        row[14],  # ccaa
                        row[15],  # duracion_valor
                        row[16],  # duracion_unidad
                        row[17],  # fecha_inicio
                        row[18],  # fecha_fin
                        row[19],  # prorroga_descripcion
                        *extra_params,
                    ),
                )
                if cur.rowcount:
                    inserted += 1
                else:
                    already_exists += 1

    log.info(
        "seed_negatives.done",
        year=year,
        month=month,
        downloaded=downloaded,
        inserted=inserted,
        skipped_ti=skipped_ti,
        already_exists=already_exists,
    )
    return {
        "downloaded": downloaded,
        "inserted": inserted,
        "skipped_ti": skipped_ti,
        "already_exists": already_exists,
    }


def train_from_db() -> dict[str, float]:
    """Entrena el clasificador usando datos de la BD activa y lo guarda."""
    import pandas as pd

    from db.database import connect, init_db

    init_db()
    with connect() as c:
        cursor = c.execute("SELECT titulo, descripcion, raw_keywords, cpv FROM licitaciones")
        rows = cursor.fetchall()
        cols = [d[0] for d in cursor.description]

    df = pd.DataFrame(rows, columns=cols)
    clf = SAPClassifier()
    metrics = clf.train(df)
    if "error" not in metrics:
        clf.save()
    return metrics


# ── CLI entry point ───────────────────────────────────────────────────────────

if __name__ == "__main__":
    import sys

    cmd = sys.argv[1] if len(sys.argv) > 1 else "train"
    if cmd == "train":
        print("Entrenando clasificador SAP desde la BD...")
        result = train_from_db()
        if "error" in result:
            err = result["error"]
            if err == "single_class":
                print(
                    "\n[AVISO] Entrenamiento no posible: todos los ejemplos son SAP (clase única).\n"
                    f"  n_positive={result.get('n_positive', 0)}, n_negative={result.get('n_negative', 0)}\n"
                    "  El clasificador ML necesita licitaciones sin keywords SAP con CPV fuera de 48xxx/72xxx.\n"
                    "  Solución: ejecuta primero: python -m scraper.ml_classifier seed-negatives"
                )
            elif err == "insufficient_data":
                print(
                    f"\n[AVISO] Datos insuficientes: {result.get('n_samples', 0)} muestras "
                    f"(mínimo {MIN_TRAIN_SAMPLES})."
                )
            else:
                print(f"\n[ERROR] {result}")
        else:
            for k, v in result.items():
                print(f"  {k}: {v}")
            print(f"\nModelo guardado en: {_MODEL_PATH}")
    elif cmd == "seed-negatives":
        import argparse

        parser_cli = argparse.ArgumentParser(prog="ml_classifier seed-negatives")
        parser_cli.add_argument("--year", type=int, default=None)
        parser_cli.add_argument("--month", type=int, default=None)
        parser_cli.add_argument("--max", type=int, default=2000, dest="max_negatives")
        args = parser_cli.parse_args(sys.argv[2:])
        print(
            f"Descargando negativos del bulk "
            f"{args.year or 'mes anterior'}/{args.month or ''}  (máx {args.max_negatives})..."
        )
        result = seed_negatives(year=args.year, month=args.month, max_negatives=args.max_negatives)
        print(
            f"  Descargadas : {result['downloaded']}\n"
            f"  Insertadas  : {result['inserted']}\n"
            f"  Omitidas TI : {result['skipped_ti']}\n"
            f"  Ya existían : {result['already_exists']}\n"
            "\nAhora puedes entrenar: python -m scraper.ml_classifier train"
        )
    elif cmd == "info":
        if SAPClassifier.is_available():
            print(f"Modelo disponible: {_MODEL_PATH}")
        else:
            print("No hay modelo entrenado. Ejecuta: python -m scraper.ml_classifier train")
    else:
        print(f"Comando desconocido: {cmd}. Usa 'train', 'seed-negatives' o 'info'.")
        sys.exit(1)
