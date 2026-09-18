"""Unit tests for Dockerfile.api signal propagation fix (issue #61).

Validates that:
- docker-entrypoint-api.sh exists and is executable
- docker-entrypoint-api.sh uses exec to replace shell as PID 1
- Dockerfile.api uses ENTRYPOINT exec form (not shell form CMD)
"""

from __future__ import annotations

import stat
import sys
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


@contextmanager
def _api_app_descargada() -> Iterator[None]:
    """Descarga ``api.app`` para poder medir qué arrastra su import, y **repone
    el módulo original al salir**.

    La reposición no es limpieza de buenos modales: es lo que impide que estos
    dos tests rompan la suite entera. ``api/app.py`` crea el objeto ``app`` en
    el import, y una veintena de ficheros de test hacen ``from api.app import
    app`` **en la colección**, antes de que corra nada. Si aquí se deja en
    ``sys.modules`` el módulo recién importado, a partir de ese punto hay dos
    objetos ``app``: el que aquellos ficheros capturaron y el que resuelve el
    fixture ``client``. Sus ``dependency_overrides`` son diccionarios distintos,
    así que un test que instala su sustitución de ``require_any_auth`` la pone
    en un ``app`` que ya no responde y su petición sale con **401**.

    Eso es exactamente lo que pasaba: `test_webhooks_rotate_secret.py` fallaba
    dos tests por tirada con ``-n 4``, nunca los mismos, y pasaba en solitario y
    con ``-p no:randomly`` —hace falta que estos tests corran antes, y el orden
    aleatorio decide si pasa—. Se diagnosticó imprimiendo `id(app)` desde el
    test que fallaba: el del módulo y el del ``TestClient`` eran distintos.
    """
    guardados = {
        nombre: modulo
        for nombre, modulo in sys.modules.items()
        if nombre == "api.app" or nombre.startswith("api.app.")
    }
    for nombre in guardados:
        del sys.modules[nombre]
    try:
        yield
    finally:
        # El módulo recién importado se descarta entero y vuelve el original:
        # quedarse con el nuevo es justo el fallo que este helper existe para
        # no cometer.
        for nombre in [n for n in sys.modules if n == "api.app" or n.startswith("api.app.")]:
            del sys.modules[nombre]
        sys.modules.update(guardados)
        # Y el atributo del paquete, que es la mitad que se olvida. `import
        # api.app` deja `app` como atributo de `api`, y al reimportar queda
        # apuntando al módulo nuevo. Reponer sólo `sys.modules` deja las dos
        # vías discrepando: `from api.app import app` da el original y
        # `import api.app as m; m.app` da el recargado. Con eso el fallo no
        # desaparece, sólo se vuelve más raro.
        for nombre, modulo in guardados.items():
            padre, _, hoja = nombre.rpartition(".")
            if padre in sys.modules:
                setattr(sys.modules[padre], hoja, modulo)


def test_entrypoint_script_exists() -> None:
    entrypoint = ROOT / "docker" / "docker-entrypoint-api.sh"
    assert entrypoint.exists(), "docker/docker-entrypoint-api.sh must exist"


def test_entrypoint_script_is_executable() -> None:
    entrypoint = ROOT / "docker" / "docker-entrypoint-api.sh"
    import platform
    import subprocess

    if platform.system() == "Windows":
        # On Windows, check git's executable bit tracking instead of filesystem permissions
        result = subprocess.run(
            ["git", "ls-files", "--stage", "docker/docker-entrypoint-api.sh"],
            capture_output=True,
            text=True,
            cwd=str(ROOT),
        )
        assert result.returncode == 0 and result.stdout.strip(), (
            "docker-entrypoint-api.sh must be tracked by git"
        )
        # Git executable bit: mode 100755 vs 100644
        git_mode = result.stdout.split()[0]
        assert git_mode == "100755", (
            f"docker-entrypoint-api.sh must be executable in git (got {git_mode})"
        )
    else:
        mode = entrypoint.stat().st_mode
        assert mode & stat.S_IXUSR, "docker-entrypoint-api.sh must be executable"


def test_entrypoint_uses_exec() -> None:
    """exec ensures uvicorn replaces sh as PID 1 for signal propagation."""
    entrypoint = ROOT / "docker" / "docker-entrypoint-api.sh"
    content = entrypoint.read_text()
    assert "exec " in content, "entrypoint must use 'exec' to replace shell as PID 1"
    assert "uvicorn" in content, "entrypoint must invoke uvicorn"


def test_entrypoint_has_shebang() -> None:
    entrypoint = ROOT / "docker" / "docker-entrypoint-api.sh"
    content = entrypoint.read_text()
    assert content.startswith("#!/bin/sh"), "entrypoint must have #!/bin/sh shebang"


def test_dockerfile_api_uses_entrypoint_exec_form() -> None:
    """Dockerfile.api must use ENTRYPOINT exec form, not shell form CMD."""
    dockerfile = ROOT / "docker" / "Dockerfile.api"
    content = dockerfile.read_text()
    # Must NOT have the old sh -c pattern
    assert 'CMD ["sh", "-c"' not in content, (
        "Dockerfile.api must not use sh -c wrapper (prevents signal propagation)"
    )
    # Must have ENTRYPOINT in exec form
    assert 'ENTRYPOINT ["' in content and "docker-entrypoint-api.sh" in content, (
        "Dockerfile.api must use ENTRYPOINT exec form with docker-entrypoint-api.sh"
    )


def test_entrypoint_expands_forwarded_allow_ips() -> None:
    """Entrypoint must reference FORWARDED_ALLOW_IPS for env var expansion."""
    entrypoint = ROOT / "docker" / "docker-entrypoint-api.sh"
    content = entrypoint.read_text()
    assert "FORWARDED_ALLOW_IPS" in content, "entrypoint must reference FORWARDED_ALLOW_IPS env var"


# ── C3.1: la imagen de la API no carga el plano de ingesta/ML ────────────────


def test_la_api_arranca_sin_sentence_transformers() -> None:
    """Importar `api.app` no puede exigir el extra `[ml]`.

    `sentence-transformers` arrastra PyTorch (~2 GB). No está en
    `requirements.in` —y por tanto no viaja a la imagen— pero nada lo impedía:
    un import nuevo en el arranque lo convertiría en obligatorio y el fallo
    aparecería en el despliegue, no en CI.
    """
    # Se simula "no instalado" incluso si el entorno de desarrollo lo tiene.
    centinelas = {
        nombre: sys.modules.get(nombre) for nombre in ("sentence_transformers", "torch", "faiss")
    }
    for nombre in centinelas:
        sys.modules[nombre] = None  # type: ignore[assignment]
    try:
        with _api_app_descargada():
            import api.app  # noqa: F401
    finally:
        for nombre, previo in centinelas.items():
            if previo is None:
                sys.modules.pop(nombre, None)
            else:
                sys.modules[nombre] = previo


def test_la_api_no_importa_el_parser_codice() -> None:
    """`lxml` es del plano de ingesta: seis ficheros en `scraper/`, cero en `api/`.

    Es el paquete más grande que el corte C3.1 saca de la imagen expuesta a
    internet, así que un import eager desde `api/` lo devolvería sin que nadie
    lo note hasta ver la factura de parches.
    """
    with _api_app_descargada():
        antes = "lxml" in sys.modules
        import api.app  # noqa: F401

        arrastra = not antes and "lxml" in sys.modules

    assert not arrastra, (
        "importar api.app arrastra lxml; el corte de requirements-api.in deja de valer"
    )


def test_el_dockerfile_usa_el_lockfile_de_la_api_cuando_existe() -> None:
    """El corte C3.1 no puede quedarse a medias en silencio.

    Mientras `requirements-api.txt` no exista (lo genera `make lock`, que
    necesita `uv`), la imagen sigue instalando `requirements.txt` y eso está
    declarado en el propio Dockerfile. En cuanto el lockfile aparezca, seguir
    instalando el conjunto entero sería un corte hecho y no aplicado.
    """
    lockfile_api = ROOT / "requirements-api.txt"
    dockerfile = (ROOT / "docker" / "Dockerfile.api").read_text(encoding="utf-8")
    if not lockfile_api.exists():
        assert "requirements-api.txt" in dockerfile, (
            "el Dockerfile debe explicar por qué todavía no usa requirements-api.txt"
        )
        return
    assert "-r requirements-api.txt" in dockerfile, (
        "requirements-api.txt existe: docker/Dockerfile.api tiene que instalarlo "
        "en vez de requirements.txt (C3.1)"
    )


def test_el_corte_de_requirements_esta_declarado() -> None:
    """Los dos `.in` del corte existen y el pipeline hereda de la API."""
    api_in = ROOT / "requirements-api.in"
    pipeline_in = ROOT / "requirements-pipeline.in"
    assert api_in.exists(), "falta requirements-api.in (C3.1)"
    assert pipeline_in.exists(), "falta requirements-pipeline.in (C3.1)"
    assert "-r requirements-api.in" in pipeline_in.read_text(encoding="utf-8"), (
        "el pipeline comparte persistencia y observabilidad con la API: "
        "requirements-pipeline.in debe heredar de requirements-api.in"
    )
