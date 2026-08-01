# Ruta feliz en Windows (PowerShell)

## 1) Crear entorno e instalar

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements-dev.txt
pip install -e .
```

## 2) Verificar entorno

Los targets del Makefile requieren WSL, Git Bash o un entorno POSIX con `make`.
Desde PowerShell puro, ejecuta el script equivalente:

```powershell
python scripts/doctor.py
```

## 3) Flujo de desarrollo diario

```powershell
ruff check .
mypy .
pytest tests/ -m "unit and not slow"
```

La suite requiere `TEST_DATABASE_URL`; consulta `AGENTS.md` para levantar Postgres.

## 4) Limpieza portable

```powershell
python scripts/clean_artifacts.py
```

`make clean` usa comandos POSIX; el script anterior es la alternativa portable.

## 5) Navegacion graphify-first

```powershell
graphify query "scheduler anomaly"
graphify update .
```

`graphify` es un CLI local, no un target del Makefile. Si no esta instalado en tu shell, sigue el fallback documentado en `docs/graphify-first.md` y no intentes instalarlo.
