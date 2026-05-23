.PHONY: install dev lint format typecheck audit test test-all test-unit test-integration test-e2e test-property test-load lock lock-hashes scrape scrape-daily app dashboard api doctor clean kpi kpi-export-parquet runbook-backup-restore runbook-dlq-replay runbook-rate-limit-reset runbook-model-rollback runbook-disaster-recovery

# ── Instalación ──────────────────────────────────────────────────────────
install:
	pip install -r requirements.txt
	pip install -e .

dev:
	pip install -r requirements-dev.txt
	pip install -e .
	pre-commit install

# ── Calidad ──────────────────────────────────────────────────────────────
lint:
	ruff check .

format:
	ruff format .

typecheck:
	mypy .

audit:
	pip-audit --strict --desc

# ── Tests ────────────────────────────────────────────────────────────────
test:
	pytest tests/ --ignore=tests/test_integration_e2e.py --ignore=tests/test_dashboard_smoke.py

test-all:
	pytest tests/ -m "not integration"

test-integration:
	pytest tests/ -m integration

test-smoke:
	pytest tests/test_dashboard_smoke.py

test-perf:
	pytest tests/test_performance.py -m slow --timeout=120

# ── Tests por categoría (markers nuevos en F0) ───────────────────────────
test-unit:
	pytest tests/ -m "unit and not slow"

test-e2e:
	pytest tests/ -m e2e

test-property:
	pytest tests/ -m property

test-load:
	pytest tests/ -m load

# ── Lockfile reproducible con hashes (uv) ────────────────────────────────
# Requiere uv instalado (https://github.com/astral-sh/uv).
# Genera requirements.txt y requirements-dev.txt con --generate-hashes.
lock:
	uv pip compile requirements.in -o requirements.txt --generate-hashes --quiet
	uv pip compile requirements-dev.in -o requirements-dev.txt --generate-hashes --quiet

lock-hashes: lock

# ── Scraper ──────────────────────────────────────────────────────────────
scrape:
	python -m scheduler.run_update --backfill $(YEAR) $(MONTH)

scrape-daily:
	python -m scheduler.run_update

# ── KPIs ─────────────────────────────────────────────────────────────────
kpi:
	python -m scheduler.kpi_precompute

kpi-export-parquet:
	python -m scheduler.kpi_precompute --export-parquet $(or $(PARQUET_DIR),data/parquet)

# ── Dashboard / API ──────────────────────────────────────────────────────
## Alias principal — arranca el dashboard (equivalente a 'make dashboard')
app:
	PYTHONPATH=$(CURDIR) streamlit run dashboard/app.py

dashboard:
	PYTHONPATH=$(CURDIR) streamlit run dashboard/app.py

## Arranca la API REST en modo desarrollo (requiere uvicorn)
api:
	PYTHONPATH=$(CURDIR) uvicorn api.app:app --host 0.0.0.0 --port 8080 --reload

# ── Migraciones ──────────────────────────────────────────────────────────
migrate:
	python -c "from db.database import init_db; init_db()"

migrate-alembic:
	alembic upgrade head

# ── Doctor: verifica entorno antes de despliegue ─────────────────────────
doctor:
	python scripts/doctor.py

# ── Limpieza ─────────────────────────────────────────────────────────────
clean:
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
