import type { Metadata } from "next";
import { PaginaEvidencia, type SeccionEvidencia } from "../_components/pagina-evidencia";

export const metadata: Metadata = {
  title: "Metodología",
  description: "Cómo calcula TenderFlow el scoring, los escenarios de baja y el contexto competitivo, con sus límites.",
  alternates: { canonical: "/metodologia" },
};

const SECCIONES: SeccionEvidencia[] = [
  {
    titulo: "Scoring de oportunidad",
    texto: [
      "El ranking puntúa de 0 a 100 las oportunidades abiertas. Combina importe, plazo, competencia, margen, afinidad y señal técnica. Los pesos globales son 20, 15, 20, 20, 15 y 10 puntos respectivamente; cada perfil puede sustituirlos manteniendo una suma de 100.",
      "Sin portfolio explícito, la afinidad se omite y su peso se redistribuye. Una señal ausente usa un valor neutral y añade un indicador de riesgo: la falta de dato no se confunde con una valoración negativa.",
    ],
    puntos: [
      "Bandas: Caliente desde 75, Atractiva desde 50, Tibia desde 25 y Descarte por debajo.",
      "El importe se normaliza entre los percentiles 10 y 90 del mercado abierto puntuable.",
      "La competencia usa ofertas históricas por segmento CPV de los últimos 24 meses, con fallback declarado.",
      "Los descartes se guardan antes de ordenar y cortar el top, por lo que no ocupan una plaza invisible.",
    ],
  },
  {
    titulo: "Referencia de precio",
    texto: [
      "Los escenarios describen adjudicaciones comparables por empresa, órgano, CPV y comunidad autónoma. No calculan una probabilidad de ganar y no sustituyen el criterio comercial del equipo.",
      "Cuando existe una predicción por licitación, el producto sirve un intervalo p10/p50/p90 con la versión del modelo. La cobertura empírica se contrasta contra bajas ya resueltas.",
    ],
    puntos: [
      "La calibración responde «insuficiente» con menos de 30 pares comparables.",
      "Los cuantiles descriptivos se etiquetan según la robustez de la muestra.",
      "El modelo no se presenta como causal: resume patrones observados en adjudicaciones oficiales.",
    ],
  },
  {
    titulo: "Contexto competitivo",
    texto: [
      "Las cuotas y la concentración HHI se calculan sobre adjudicaciones del universo tecnológico observado. El maestro de empresas normaliza NIF, alias y uniones temporales para reducir la fragmentación de un mismo competidor.",
    ],
    puntos: [
      "El dossier de empresa conserva historial y participación en UTEs.",
      "La ficha del órgano muestra lo que publica y los resultados disponibles en la fuente.",
      "El nombre del órgano procede de la fuente oficial; hay búsqueda y agregación, pero no se afirma un maestro administrativo perfecto.",
    ],
  },
  {
    titulo: "Trazabilidad y degradación",
    texto: [
      "El backend informa qué señales estaban disponibles al calcular una respuesta. Si competencia, margen, señal técnica o percentiles no aportan el nivel esperado, el estado viaja con el resultado para que la interfaz pueda declararlo.",
    ],
    puntos: [
      "Los scores exponen su desglose por dimensión.",
      "Las predicciones conservan versión y fecha de cálculo.",
      "Los campos ausentes permanecen vacíos; no se fabrican agregados en el navegador.",
    ],
  },
];

export default function MetodologiaPage() {
  return (
    <PaginaEvidencia
      kicker="Metodología"
      titulo="Cómo se construye cada señal"
      introduccion="TenderFlow separa hechos oficiales, estadística descriptiva y predicción. Esta página explica qué calcula cada capa y cuándo el producto debe responder que no sabe suficiente."
      secciones={SECCIONES}
    />
  );
}
