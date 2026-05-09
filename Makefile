.PHONY: install dev lint format typecheck test test-all scrape scrape-daily dashboard clean

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

# ── Tests ────────────────────────────────────────────────────────────────
test:
	pytest tests/ --ignore=tests/test_integration_e2e.py --ignore=tests/test_dashboard_smoke.py

test-all:
	pytest tests/ -m "not integration"

test-integration:
	pytest tests/ -m integration

test-smoke:
	pytest tests/test_dashboard_smoke.py

# ── Scraper ──────────────────────────────────────────────────────────────
scrape:
	python -m scheduler.run_update --backfill $(YEAR) $(MONTH)

scrape-daily:
	python -m scheduler.run_update

# ── Dashboard ────────────────────────────────────────────────────────────
dashboard:
	streamlit run dashboard/app.py

# ── Migraciones ──────────────────────────────────────────────────────────
migrate:
	python -c "from db.database import init_db; init_db()"

migrate-alembic:
	alembic upgrade head

# ── Limpieza ─────────────────────────────────────────────────────────────
clean:
	find . -type d -name __pycache__ -exec rm -rf {} + 2>/dev/null || true
	rm -f cov80.txt full_cov.txt _test_summary.txt pytest-run.txt
	rm -rf .pytest_cache .mypy_cache .ruff_cache htmlcov
