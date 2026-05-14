"""Configuración de navegación y helpers de routing del dashboard."""

from __future__ import annotations

SECTIONS: dict[str, list[str]] = {
    "Vista General": ["Resumen", "Tendencias", "Detalle"],
    "Mercado": ["Órganos", "Geografía", "Proyectos & Módulos", "Tecnologías", "Clusters"],
    "Competencia": ["Competidores", "Pipeline & Alertas"],
    "Personal": ["Mi Watchlist"],
    "Ops": ["Observabilidad", "Calidad de Datos"],
}

SECTION_ICONS: dict[str, str] = {
    "Vista General": "◈",
    "Mercado": "◉",
    "Competencia": "◆",
    "Personal": "★",
    "Ops": "▤",
}

PAGE_ICONS: dict[str, str] = {
    "Resumen": "◈",
    "Tendencias": "📈",
    "Detalle": "🔍",
    "Órganos": "🏛",
    "Geografía": "🗺",
    "Proyectos & Módulos": "🧩",
    "Tecnologías": "🔧",
    "Competidores": "🏆",
    "Pipeline & Alertas": "🔔",
    "Mi Watchlist": "⭐",
    "Observabilidad": "📊",
    "Calidad de Datos": "🔬",
    "Clusters": "🪤",
}

PAGE_DESCRIPTIONS: dict[str, str] = {
    "Resumen": "Top licitaciones, distribución por estado y salud competitiva del mercado.",
    "Tendencias": "Evolución mensual de publicaciones e importes, heatmap y distribución.",
    "Detalle": "Tabla completa con todos los campos y exportación a Excel/CSV.",
    "Órganos": "Ranking de órganos contratantes, treemap y análisis de pipeline individual.",
    "Geografía": "Distribución geográfica por comunidad autónoma e importe acumulado.",
    "Proyectos & Módulos": "Desglose por tipo de proyecto y módulo SAP detectado.",
    "Tecnologías": "Distribución, evolución y cruces por tecnología detectada (SAP, Oracle, Salesforce…).",
    "Competidores": "Empresas adjudicatarias, cuota de mercado y análisis comparativo.",
    "Pipeline & Alertas": "Licitaciones en plazo, predicciones y alertas de vencimiento.",
    "Mi Watchlist": "Reglas de seguimiento personalizadas por CPV, keyword e importe.",
    "Observabilidad": "Métricas de rendimiento, logs de scraping y estado del pipeline.",
    "Calidad de Datos": "Completitud del dataset, frescura del scraping, tasa de errores y DLQ.",
    "Clusters": "Agrupaciones semánticas de licitaciones para detectar patrones y nichos de mercado.",
}
