# ── Etapa 1: dependencias ───────────────────────────────────────────────────
FROM python:3.11-slim AS deps

WORKDIR /app

# Herramientas del sistema mínimas (SQLite nativo ya incluido en slim)
RUN apt-get update && apt-get install -y --no-install-recommends \
        build-essential \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt .
COPY pyproject.toml .
RUN pip install --no-cache-dir -r requirements.txt

# ── Etapa 2: imagen de producción ───────────────────────────────────────────
FROM python:3.11-slim AS runtime

# Usuario no-root para reducir superficie de ataque
RUN useradd --create-home --shell /bin/bash appuser

WORKDIR /app

# Copiar paquetes instalados desde la etapa anterior
COPY --from=deps /usr/local/lib/python3.11/site-packages /usr/local/lib/python3.11/site-packages
COPY --from=deps /usr/local/bin /usr/local/bin

# Código fuente (excluir lo que está en .dockerignore)
COPY --chown=appuser:appuser . .

# Instalar el proyecto como paquete (imports resueltos sin sys.path hacks)
RUN pip install --no-cache-dir --no-deps -e .

# Directorio de datos persistente — se monta como volumen en producción
RUN mkdir -p /data && chown appuser:appuser /data
ENV DB_PATH=/data/licitaciones.db

# Puerto por defecto de Streamlit
EXPOSE 8501

USER appuser

HEALTHCHECK --interval=30s --timeout=10s --start-period=20s --retries=3 \
    CMD python -c "import urllib.request; urllib.request.urlopen('http://localhost:8501/_stcore/health')" || exit 1

ENTRYPOINT ["python", "-m", "streamlit", "run", "dashboard/app.py", \
            "--server.port=8501", \
            "--server.address=0.0.0.0", \
            "--server.headless=true", \
            "--browser.gatherUsageStats=false"]
