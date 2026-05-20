"""Configuración de navegación y helpers de routing del dashboard."""

from __future__ import annotations

SECTIONS: dict[str, list[str]] = {
    "Vista General": ["Resumen", "Tendencias", "Tendencias CPV", "Calendario", "Detalle"],
    "Mercado": ["Órganos", "Geografía", "Proyectos & Módulos", "Tecnologías", "Clusters"],
    "Competencia": [
        "Competidores",
        "Licitadores",
        "UTEs",
        "Ecosistema Partners",
        "Pipeline & Alertas",
    ],
    "Personal": ["Mi Watchlist", "Investigador"],
    "Ops": ["Observabilidad", "Calidad de Datos"],
    "Admin": ["Administración", "Feature Flags", "Active Learning"],
}

SECTION_ICONS: dict[str, str] = {
    "Vista General": "◈",
    "Mercado": "◉",
    "Competencia": "◆",
    "Personal": "★",
    "Ops": "▤",
    "Admin": "⚙",
}

PAGE_ICONS: dict[str, str] = {
    "Resumen": "◈",
    "Tendencias": "📈",
    "Tendencias CPV": "💰",
    "Calendario": "📅",
    "Comparador": "🔀",
    "Detalle": "🔍",
    "Órganos": "🏛",
    "Geografía": "🗺",
    "Proyectos & Módulos": "🧩",
    "Tecnologías": "🔧",
    "Competidores": "🏆",
    "Licitadores": "🏅",
    "UTEs": "🤝",
    "Ecosistema Partners": "🕸",
    "Pipeline & Alertas": "🔔",
    "Mi Watchlist": "⭐",
    "Investigador": "🔬",
    "Observabilidad": "📊",
    "Calidad de Datos": "🔬",
    "Clusters": "🪤",
    "Administración": "⚙️",
    "Feature Flags": "⚑",
    "Active Learning": "🎯",
}

PAGE_DESCRIPTIONS: dict[str, str] = {
    "Resumen": "Top licitaciones, distribución por estado y salud competitiva del mercado.",
    "Tendencias": "Evolución mensual de publicaciones e importes, heatmap y distribución.",
    "Tendencias CPV": "Serie temporal de importes por CPV con predicción ARIMA.",
    "Calendario": "Heatmap de publicaciones por semana/día del año.",
    "Comparador": "Diff side-by-side de 2-3 expedientes en paralelo.",
    "Detalle": "Tabla completa con todos los campos y exportación a Excel/CSV.",
    "Órganos": "Ranking de órganos contratantes, treemap y análisis de pipeline individual.",
    "Geografía": "Distribución geográfica por comunidad autónoma e importe acumulado.",
    "Proyectos & Módulos": "Desglose por tipo de proyecto y módulo SAP detectado.",
    "Tecnologías": "Distribución, evolución y cruces por tecnología detectada (SAP, Oracle, Salesforce…).",
    "Competidores": "Empresas adjudicatarias, cuota de mercado y análisis comparativo.",
    "Licitadores": "Ranking de licitadores recurrentes, cuota por órgano y análisis de competencia.",
    "UTEs": "Análisis de Uniones Temporales de Empresas: alianzas, estructura y contratos ganados.",
    "Ecosistema Partners": "Grafo de co-adjudicaciones, ganadores por segmento y buscador de partners para subcontratación.",
    "Pipeline & Alertas": "Licitaciones en plazo, predicciones y alertas de vencimiento.",
    "Mi Watchlist": "Reglas de seguimiento personalizadas por CPV, keyword e importe.",
    "Investigador": "Búsqueda semántica RAG sobre el corpus de licitaciones.",
    "Observabilidad": "Métricas de rendimiento, logs de scraping y estado del pipeline.",
    "Calidad de Datos": "Completitud del dataset, frescura del scraping, tasa de errores y DLQ.",
    "Clusters": "Agrupaciones semánticas de licitaciones para detectar patrones y nichos de mercado.",
    "Administración": "Gestión de DLQ, usuarios y API Keys. Solo accesible para administradores.",
    "Feature Flags": "Activar/desactivar funcionalidades en tiempo real con rollout gradual.",
    "Active Learning": "Etiquetado humano de licitaciones en zona de incertidumbre del modelo ML.",
}
