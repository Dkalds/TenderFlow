"""Verificación de integridad de modelos ML serializados antes de deserializar.

``joblib.load`` ejecuta código arbitrario (usa pickle bajo el capó), así que
deserializar un artefacto ``.pkl`` manipulado equivale a ejecutar código de un
atacante. Este módulo centraliza la defensa en profundidad que originalmente
vivía solo en ``scraper.ml_classifier.SAPClassifier.load`` y la extiende a los
demás cargadores de modelo del proyecto (``TechnologyClassifier``,
``BajaModel``, ``RetencionModel``):

  1. **Pin out-of-band** (un setting ``ML_*_SHA256`` fijado fuera del propio
     release, p.ej. en el entorno del proceso): si está configurado, el hash
     del artefacto DEBE coincidir. Es la única defensa real contra un release
     comprometido — un checksum ``.sha256`` co-ubicado viaja junto al ``.pkl``
     en el mismo release, así que un atacante que controle el release podría
     sustituir ambos ficheros a la vez.
  2. **Checksum co-ubicado** (``<modelo>.sha256`` junto al ``.pkl``): defensa
     complementaria — detecta corrupción o manipulación posterior al release
     (p.ej. un fallo de disco, o un paso intermedio del pipeline de deploy),
     pero es insuficiente por sí sola frente al escenario de (1).
  3. **Fallo duro en producción** (``ENV == "prod"``): si no hay pin NI
     checksum co-ubicado, no hay ninguna verificación posible — se rechaza la
     carga en vez de deserializar a ciegas. Fuera de producción se permite
     (con warning) para no bloquear desarrollo local.

Uso típico en un ``classmethod load``::

    from shared.model_integrity import verify_model_integrity

    target = path or _MODEL_PATH
    verify_model_integrity(
        target,
        pinned_sha256=str(getattr(settings, "ML_MODEL_SHA256", "") or ""),
        pin_setting_name="ML_MODEL_SHA256",
        model_label="sap_classifier",
        env=str(getattr(settings, "ENV", "dev")),
    )
    obj = joblib.load(target)

Y en el ``save`` correspondiente, para mantener el checksum co-ubicado
sincronizado con el artefacto::

    from shared.model_integrity import write_checksum

    joblib.dump(self, target, compress=3)
    write_checksum(target)
"""

from __future__ import annotations

import hashlib
from pathlib import Path

from observability.logging import get_logger

log = get_logger(__name__)


def verify_model_integrity(
    target: Path,
    *,
    pinned_sha256: str,
    pin_setting_name: str,
    model_label: str,
    env: str,
) -> str:
    """Verifica ``target`` antes de deserializarlo con joblib.

    Args:
        target: ruta del artefacto ``.pkl`` a verificar (debe existir).
        pinned_sha256: valor del pin out-of-band ya resuelto (vacío = sin pin).
        pin_setting_name: nombre del setting de origen (solo para mensajes,
            p.ej. ``"ML_MODEL_SHA256"``).
        model_label: nombre corto del modelo para logs/mensajes (p.ej.
            ``"sap_classifier"``, ``"baja_model"``).
        env: valor de ``settings.ENV`` ya resuelto (``"dev"``/``"staging"``/
            ``"prod"``).

    Returns:
        El SHA256 (hex, minúsculas) calculado sobre ``target``.

    Raises:
        RuntimeError: si el pin no coincide, si el checksum co-ubicado no
            coincide, o si ``env == "prod"`` y no existe ninguna de las dos
            verificaciones.
        FileNotFoundError: si ``target`` no existe (propagada de ``read_bytes``).
    """
    actual_hash = hashlib.sha256(target.read_bytes()).hexdigest()
    pinned = pinned_sha256.strip().lower()

    # 1) Pin out-of-band: defensa contra un release comprometido (ver docstring
    # del módulo). Se comprueba primero porque es la única verificación que no
    # puede haber sido sustituida junto con el .pkl.
    if pinned and actual_hash.lower() != pinned:
        raise RuntimeError(
            f"Integridad del modelo '{model_label}' comprometida: SHA256 no "
            f"coincide con {pin_setting_name} fijado. Esperado: {pinned[:16]}..., "
            f"obtenido: {actual_hash[:16]}... Fichero: {target}"
        )

    # 2) Checksum co-ubicado (<target>.sha256)
    checksum_path = target.with_suffix(".sha256")
    if checksum_path.exists():
        expected_hash = checksum_path.read_text(encoding="utf-8").strip()
        if actual_hash != expected_hash:
            raise RuntimeError(
                f"Integridad del modelo '{model_label}' comprometida: SHA256 no "
                f"coincide con el checksum co-ubicado ({checksum_path}). "
                f"Esperado: {expected_hash[:16]}..., obtenido: {actual_hash[:16]}... "
                f"Fichero: {target}"
            )
        log.info("model_integrity.checksum_verified", model=model_label, path=str(target))
    elif env == "prod" and not pinned:
        # En producción se exige al menos una verificación de integridad (pin
        # o checksum co-ubicado): joblib.load ejecuta código arbitrario.
        raise RuntimeError(
            f"Sin verificación de integridad para el modelo '{model_label}': no "
            f"existe {checksum_path} ni {pin_setting_name} fijado. En producción "
            "es obligatorio para deserializar con seguridad. Re-entrena con "
            f"save() o define {pin_setting_name}."
        )
    elif not pinned:
        log.warning(
            "model_integrity.no_checksum_file",
            model=model_label,
            path=str(checksum_path),
            hint="El modelo se cargará sin verificación de integridad. "
            "Re-entrena con save() para generar el fichero .sha256.",
        )

    return actual_hash


def write_checksum(target: Path, sha256: str | None = None) -> str:
    """Calcula el SHA256 de ``target`` y lo persiste en ``<target>.sha256``.

    Usado por los métodos ``save()`` de los cuatro modelos para mantener el
    checksum co-ubicado sincronizado con el artefacto recién escrito.

    Args:
        target: artefacto ``.pkl`` cuyo checksum se persiste.
        sha256: hash ya calculado sobre ``target``. Lo pasa
            ``shared.model_artifacts`` para no releer un artefacto de cientos
            de MB que acaba de hashear; omitido, se calcula aquí.

    Returns:
        El SHA256 (hex) escrito, por si el llamador quiere loguearlo.
    """
    sha256_hash = sha256 or hashlib.sha256(target.read_bytes()).hexdigest()
    target.with_suffix(".sha256").write_text(sha256_hash, encoding="utf-8")
    return sha256_hash


__all__ = ["verify_model_integrity", "write_checksum"]
