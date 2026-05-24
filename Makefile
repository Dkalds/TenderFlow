.PHONY: install dev lint format typecheck audit test test-all test-unit test-integration test-e2e test-property test-load lock lock-hashes lock-uv install-uv scrape scrape-daily app dashboard api doctor clean kpi kpi-export-parquet runbook-backup-restore runbook-dlq-replay runbook-rate-limit-reset runbook-model-rollback runbook-disaster-recovery check help migrate migrate-alembic migrate-status migrate-history

# ── Ayuda ────────────────────────────────────────────────────────────────
help:  ## Muestra esta ayuda
	@echo "Targets disponibles:"
	@echo ""
	@grep -E '^[a-zA-Z_-]+:.*?## .*$$' $(MAKEFILE_LIST) | sort | awk 'BEGIN {FS = ":.*?## "}; {printf "  \033[36m%-25s\033[0m %s\n", $$1, $$2}'

.DEFAULT_GOAL := help

# ── Instalación ──────────────────────────────────────────────────────────
install:  ## Instala dependencias de producción
	pip install -r requirements.txt
	pip install -e .

dev:  ## Instala dependencias de desarrollo + pre-commit
	pip install -r requirements-dev.txt
	pip install -e .
	pre-commit install

# ── Calidad ──────────────────────────────────────────────────────────────
lint:  ## Linting con ruff
	ruff check .

format:  ## Formatea código con ruff
	ruff format .

typecheck:  ## Type checking con mypy
	mypy .

audit:  ## Auditoría de dependencias
	pip-audit --strict --desc

check:  ## Lint + typecheck + tests unitarios (ideal para desarrollo)
	ruff check .
	mypy .
	pytest tests/ -m "unit and not slow" -q

# ── Tests ────────────────────────────────────────────────────────────────
test:  ## Suite de tests estándar (excluye integration_e2e y dashboard_smoke)
	pytest tests/ --ignore=tests/test_integration_e2e.py --ignore=tests/test_dashboard_smoke.py

test-all:  ## Ejecuta TODOS los tests sin excepción
	pytest tests/

test-integration:  ## Tests de integración (requieren BD real)
	pytest tests/ -m integration

test-smoke:  ## Tests de smoke del dashboard
	pytest tests/test_dashboard_smoke.py

test-perf:  ## Tests de rendimiento (marker slow)
	pytest tests/test_performance.py -m slow --timeout=120

# ── Tests por categoría (markers nuevos en F0) ───────────────────────────
test-unit:  ## Tests unitarios rápidos
	pytest tests/ -m "unit and not slow"

test-e2e:  ## Tests end-to-end
	pytest tests/ -m e2e

test-property:  ## Tests basados en propiedades (hypothesis)
	pytest tests/ -m property

test-load:  ## Tests de carga/benchmark
	pytest tests/ -m load

# ── Lockfile reproducible con hashes (uv) ────────────────────────────────
# Requiere uv instalado (https://github.com/astral-sh/uv).
# Genera requirements.txt y requirements-dev.txt con --generate-hashes.
lock:  ## Genera lockfiles reproducibles con hashes (uv pip compile)
	uv pip compile requirements.in -o requirements.txt --generate-hashes --quiet
	uv pip compile requirements-dev.in -o requirements-dev.txt --generate-hashes --quiet

lock-hashes: lock

lock-uv:  ## Genera uv.lock desde pyproject.toml (uv lock)
	uv lock

install-uv:  ## Instala dependencias desde uv.lock (uv sync)
	uv sync

# ── Scraper ──────────────────────────────────────────────────────────────
scrape:  ## Backfill de un mes específico (YEAR=2024 MONTH=1)
	python -m scheduler.run_update --backfill $(YEAR) $(MONTH)

scrape-daily:  ## Ejecuta scraper en modo diario (ATOM feed)
	python -m scheduler.run_update

# ── KPIs ─────────────────────────────────────────────────────────────────
kpi:  ## Pre-computa KPIs
	python -m scheduler.kpi_precompute

kpi-export-parquet:
	python -m scheduler.kpi_precompute --export-parquet $(or $(PARQUET_DIR),data/parquet)

# ── Dashboard / API ──────────────────────────────────────────────────────
## Alias principal — arranca el dashboard (equivalente a 'make dashboard')
app:  ## Alias: arranca el dashboard
	PYTHONPATH=$(CURDIR) streamlit run dashboard/app.py

dashboard:  ## Arranca Streamlit dashboard
	PYTHONPATH=$(CURDIR) streamlit run dashboard/app.py

## Arranca la API REST en modo desarrollo (requiere uvicorn)
api:  ## Arranca FastAPI API en modo desarrollo
	PYTHONPATH=$(CURDIR) uvicorn api.app:app --host 0.0.0.0 --port 8080 --reload

# ── Migraciones ──────────────────────────────────────────────────────────
migrate:  ## [DEPRECATED] Migraciones custom v1-v32. Usar migrate-alembic para nuevas BDs.
	python -c "from db.database import init_db; init_db()"

migrate-alembic:  ## Aplica todas las migraciones Alembic pendientes (sistema canónico)
	alembic upgrade head

migrate-status:  ## Muestra el estado actual de las migraciones Alembic
	alembic current

migrate-history:  ## Muestra el historial de migraciones Alembic
	alembic history --verbose

# ── Doctor: verifica entorno antes de despliegue ─────────────────────────
doctor:  ## Verifica entorno antes de despliegue
	python scripts/doctor.py

# ── Limpieza ─────────────────────────────────────────────────────────────
clean:  ## Limpia artefactos de build y caché
	find . -type d -name __pycache__ -exec rm -rf {} + 2>/dev/null || true
	rm -f cov80.txt full_cov.txt _test_summary.txt pytest-run.txt
	rm -rf .pytest_cache .mypy_cache .ruff_cache htmlcov

# ── Runbooks ejecutables ─────────────────────────────────────────────────
# Extrae y ejecuta bloques de código bash de los runbooks Markdown.
_run-runbook = python - <<'PYEOF' \
&& import re, subprocess, sys, pathlib; \
  md = pathlib.Path("$(1)").read_text(); \
  blocks = re.findall(r'```bash\n(.*?)\n```', md, re.DOTALL); \
  [subprocess.run(b, shell=True, check=False) for b in blocks] \
PYEOF

runbook-backup-restore:
	@echo "==> Runbook: backup-restore"
	@bash docs/runbooks/backup-restore.md 2>/dev/null || python - <<'EOF'
import re, subprocess, pathlib
md = pathlib.Path("docs/runbooks/backup-restore.md").read_text()
for block in re.findall(r'```bash\n(.*?)\n```', md, re.DOTALL):
    print(f"\n--- ejecutando ---\n{block[:120]}...")
    subprocess.run(block, shell=True)
EOF

runbook-dlq-replay:
	@echo "==> Runbook: dlq-replay"
	@python - <<'EOF'
import re, subprocess, pathlib
md = pathlib.Path("docs/runbooks/dlq-replay.md").read_text()
for block in re.findall(r'```bash\n(.*?)\n```', md, re.DOTALL):
    print(f"\n--- ejecutando ---\n{block[:120]}...")
    subprocess.run(block, shell=True)
EOF

runbook-rate-limit-reset:
	@echo "==> Runbook: rate-limit-reset"
	@python - <<'EOF'
import re, subprocess, pathlib
md = pathlib.Path("docs/runbooks/rate-limit-reset.md").read_text()
for block in re.findall(r'```bash\n(.*?)\n```', md, re.DOTALL):
    print(f"\n--- ejecutando ---\n{block[:120]}...")
    subprocess.run(block, shell=True)
EOF

runbook-model-rollback:
	@echo "==> Runbook: model-rollback"
	@python - <<'EOF'
import re, subprocess, pathlib
md = pathlib.Path("docs/runbooks/model-rollback.md").read_text()
for block in re.findall(r'```bash\n(.*?)\n```', md, re.DOTALL):
    print(f"\n--- ejecutando ---\n{block[:120]}...")
    subprocess.run(block, shell=True)
EOF

runbook-disaster-recovery:
	@echo "==> Runbook: disaster-recovery"
	@python - <<'EOF'
import re, subprocess, pathlib
md = pathlib.Path("docs/runbooks/disaster-recovery.md").read_text()
for block in re.findall(r'```bash\n(.*?)\n```', md, re.DOTALL):
    print(f"\n--- ejecutando ---\n{block[:120]}...")
    subprocess.run(block, shell=True)
EOF

# ── Extras ───────────────────────────────────────────────────────────────────

.PHONY: docker-build security coverage-html pre-commit

docker-build:  ## Build all Docker images
	docker compose build

security:  ## Run security scanners locally (bandit + semgrep)
	bandit -r api db scraper scheduler services shared config observability llm -q
	@echo "bandit OK"
	semgrep --config auto --quiet api db scraper scheduler services shared config observability llm || true
	@echo "semgrep done"

coverage-html:  ## Generate HTML coverage report
	pytest tests/ -x -q --cov=. --cov-report=html --ignore=tests/test_integration_e2e.py --ignore=tests/test_dashboard_smoke.py -m "not slow"
	@echo "Coverage report: htmlcov/index.html"

pre-commit:  ## Run all pre-commit hooks
	pre-commit run --all-files
