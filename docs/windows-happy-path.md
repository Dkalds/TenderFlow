# Ruta feliz en Windows (PowerShell)

## 1) Crear entorno e instalar

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements-dev.txt
pip install -e .
```

## 2) Verificar entorno

```powershell
make doctor
```

## 3) Flujo de desarrollo diario

```powershell
make lint
make typecheck
make test-unit
```

## 4) Limpieza portable (sin comandos Unix)

```powershell
make clean
```

`make clean` usa `python scripts/clean_artifacts.py`, compatible con Windows/Linux/macOS.

## 5) Navegacion graphify-first

```powershell
make graphify-query Q="scheduler anomaly"
make graphify-update
```

Si `graphify` no esta instalado en tu shell, sigue el fallback documentado en `docs/graphify-first.md`.
