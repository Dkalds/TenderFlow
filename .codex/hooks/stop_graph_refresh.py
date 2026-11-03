"""Stop: refresca el grafo de graphify en segundo plano si quedó marcado como viejo.

`pretooluse_edit_stale.py` deja `graphify-out/.graph_stale` al editar un `.py`,
y el paso de después de editar (AGENTS.md §5, «graphify update .») dependía de
acordarse: en la sesión del PR #650 no se hizo y el grafo se quedó tres días por
detrás. Ahora, al acabar cada turno con la marca puesta, este hook lanza
`graphify update .` en un proceso aparte (tarda ~90 s y no puede retener el
turno) y la marca se borra solo si el refresco acaba bien y nadie volvió a
editar mientras tanto.

Best-effort como los demás hooks: sin CLI, sin grafo o ante cualquier error, no
hace nada. Un cerrojo evita dos refrescos a la vez; uno de más de media hora se
da por muerto. La salida del último refresco queda en
`graphify-out/.ultimo_refresco.log`.
"""

import json
import os
import pathlib
import shutil
import subprocess
import sys
import time

ROOT = pathlib.Path(__file__).resolve().parents[2]
CERROJO_CADUCA_S = 1800


def raiz_del_checkout(*pistas: str) -> pathlib.Path:
    """El checkout donde trabaja la sesión (en un worktree no es el de este fichero)."""
    for pista in pistas:
        if not pista:
            continue
        inicio = pathlib.Path(pista)
        if not inicio.is_absolute():
            continue
        for candidato in (inicio, *inicio.parents):
            if (candidato / ".git").exists():
                return candidato
    return ROOT


def lanzar(raiz: pathlib.Path) -> bool:
    """Lanza el refresco en segundo plano si toca. Devuelve si lo lanzó."""
    salida = raiz / "graphify-out"
    marca = salida / ".graph_stale"
    if not (marca.is_file() and (salida / "graph.json").is_file() and shutil.which("graphify")):
        return False
    cerrojo = salida / ".refrescando"
    if cerrojo.is_file() and time.time() - cerrojo.stat().st_mtime < CERROJO_CADUCA_S:
        return False
    cerrojo.write_text(str(os.getpid()), encoding="utf-8")
    opciones: dict[str, object] = {
        "cwd": str(raiz),
        "stdin": subprocess.DEVNULL,
        "stdout": subprocess.DEVNULL,
        "stderr": subprocess.DEVNULL,
    }
    if os.name == "nt":
        opciones["creationflags"] = getattr(subprocess, "DETACHED_PROCESS", 0) | getattr(
            subprocess, "CREATE_NEW_PROCESS_GROUP", 0
        )
    else:
        opciones["start_new_session"] = True
    subprocess.Popen([sys.executable, __file__, "--refrescar", str(raiz)], **opciones)
    return True


def refrescar(raiz: pathlib.Path) -> int:
    """Ejecuta `graphify update .`; borra la marca si acabó bien y nadie editó entretanto."""
    salida = raiz / "graphify-out"
    marca = salida / ".graph_stale"
    try:
        antes = marca.stat().st_mtime if marca.is_file() else None
        binario = shutil.which("graphify")
        if binario is None:
            return 1
        with (salida / ".ultimo_refresco.log").open("w", encoding="utf-8") as log:
            codigo = subprocess.run(
                [binario, "update", "."],
                cwd=str(raiz),
                stdin=subprocess.DEVNULL,
                stdout=log,
                stderr=subprocess.STDOUT,
                timeout=CERROJO_CADUCA_S,
                check=False,
            ).returncode
        if codigo == 0 and antes is not None and marca.is_file() and marca.stat().st_mtime == antes:
            marca.unlink()
        return codigo
    finally:
        (salida / ".refrescando").unlink(missing_ok=True)


def main() -> None:
    if len(sys.argv) == 3 and sys.argv[1] == "--refrescar":
        refrescar(pathlib.Path(sys.argv[2]))
        return
    try:
        d = json.load(sys.stdin)
        lanzar(raiz_del_checkout(str(d.get("cwd") or "")))
    except Exception:
        return


if __name__ == "__main__":
    main()
