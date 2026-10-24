#!/usr/bin/env bash
# Reinicia la BD de la demo: drop, create, extensiones, migraciones y seed.
set -euo pipefail
cd /home/user/TenderFlow
sudo -u postgres psql -q -c "SELECT pg_terminate_backend(pid) FROM pg_stat_activity WHERE datname='tenderflow_demo' AND pid<>pg_backend_pid();" >/dev/null
sudo -u postgres psql -q -c "DROP DATABASE IF EXISTS tenderflow_demo" -c "CREATE DATABASE tenderflow_demo OWNER tenderflow"
sudo -u postgres psql -q -d tenderflow_demo -c "CREATE EXTENSION IF NOT EXISTS vector; CREATE EXTENSION IF NOT EXISTS pg_trgm;"
export ENV=dev DATABASE_URL=postgresql://tenderflow:tenderflow@localhost:5432/tenderflow_demo
alembic upgrade head >/dev/null 2>&1
python scripts/seed_dev.py --with-predicciones >/dev/null 2>&1 || true
psql "$DATABASE_URL" -Atc "select count(*) from licitaciones"
