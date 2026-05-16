# ── Etapa 1: builder — instalar dependencias con compiladores ─────────────────
FROM python:3.13-slim-bookworm AS builder

# Buenas prácticas para Python en contenedores:
# - PYTHONDONTWRITEBYTECODE: evita ficheros .pyc en la imagen
# - PYTHONUNBUFFERED: stdout/stderr sin buffer → logs inmediatos en Docker
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    PIP_ROOT_USER_ACTION=ignore

WORKDIR /build

# Herramientas del sistema mínimas (SQLite nativo ya incluido en slim).
# build-essential solo se necesita en el builder; no se copia al runtime.
RUN apt-get update && apt-get install -y --no-install-recommends \
        build-essential \
        libffi-dev \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt pyproject.toml ./
# Instalar en directorio propio para copiar de forma selectiva al runtime
RUN pip install --prefix=/install --no-cache-dir -r requirements.txt


# ── Etapa 2: imagen de producción (sin compiladores) ──────────────────────────
FROM python:3.13-slim-bookworm AS runtime

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_ROOT_USER_ACTION=ignore \
    # Mejoras de seguridad: deshabilitar análisis JIT no usado
    PYTHONHASHSEED=random

# Solo libsqlite3 + curl para healthchecks (no toolchain de compilación)
RUN apt-get update && apt-get install -y --no-install-recommends \
        curl \
        ca-certificates \
    && rm -rf /var/lib/apt/lists/* \
    && apt-get clean

# Usuario no-root para reducir superficie de ataque
RUN useradd --create-home --shell /bin/bash --uid 1001 appuser

WORKDIR /app

# Copiar paquetes instalados desde la etapa builder
COPY --from=builder /install /usr/local

# Código fuente (excluir lo que está en .dockerignore)
COPY --chown=appuser:appuser . .

# Instalar el proyecto como paquete editable (imports sin sys.path hacks)
RUN pip install --no-cache-dir --no-deps . \
    && find /usr/local/lib/python3.13 -name '__pycache__' -type d -exec rm -rf {} + 2>/dev/null || true \
    && find /usr/local/lib/python3.13 -name '*.pyc' -delete

# Directorio de datos persistente — se monta como volumen en producción
RUN mkdir -p /data && chown appuser:appuser /data
ENV DB_PATH=/data/licitaciones.db \
    DATA_DIR=/data

# Puertos: 8501 Streamlit, 8080 API REST
EXPOSE 8501 8080

USER appuser

# Healthcheck: usa curl (más ligero que urllib.request en Python)
HEALTHCHECK --interval=30s --timeout=10s --start-period=30s --retries=3 \
    CMD curl --fail --silent --max-time 5 \
        http://localhost:8501/_stcore/health || exit 1

# CMD por defecto: dashboard Streamlit
# Para arrancar la API REST: docker run ... python -m uvicorn api.app:app --host 0.0.0.0 --port 8080
CMD ["python", "-m", "streamlit", "run", "dashboard/app.py", \
     "--server.port=8501", \
     "--server.address=0.0.0.0", \
     "--server.headless=true", \
     "--server.enableCORS=false", \
     "--server.enableXsrfProtection=true", \
     "--browser.gatherUsageStats=false", \
     "--server.maxUploadSize=10"]

