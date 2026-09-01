import type { Metadata } from "next";
import Link from "next/link";
import { PaginaEvidencia, type SeccionEvidencia } from "../_components/pagina-evidencia";
import { CONTENIDO } from "../_content/landing";

export const metadata: Metadata = {
  title: "Cobertura de datos",
  description: "Fuentes, alcance tecnológico, frecuencia de actualización y límites conocidos del corpus de TenderFlow.",
  alternates: { canonical: "/cobertura" },
};

const SECCIONES: SeccionEvidencia[] = [
  {
    titulo: "Un mercado acotado, no toda la contratación pública",
    texto: [
      "TenderFlow incluye expedientes con señal de tecnología enterprise. El corte combina coincidencias del diccionario, clasificación sobre CPV 48 y 72 y consultas directas por esos códigos en TED. Cada expediente conserva el motivo por el que entró.",
      "Ese alcance hace comparables el precio y la competencia dentro de un mercado concreto. Si el negocio principal es obra pública, sanidad o suministro general, el corpus no representa ese mercado.",
    ],
    puntos: [
      "El corpus público aplica además un umbral de contenido antes de publicar una ficha.",
      "Los expedientes terminales no ocupan la bandeja de oportunidades abiertas.",
      "Una empresa vigilada abre un carril específico para conservar sus adjudicaciones desde el alta.",
    ],
  },
  {
    titulo: "Fuentes y frecuencia",
    texto: [
      "La fuente principal es el feed ATOM de la Plataforma de Contratación del Sector Público. Se consulta cada cuatro horas con cursor incremental e historial de cambios por expediente.",
      "TED y los RSS oficiales de Galicia y Euskadi amplían el descubrimiento. Esas fuentes no aportan el mismo histórico completo, y TenderFlow no las presenta como si lo hicieran.",
    ],
    puntos: [
      "Cada ficha pública enlaza al anuncio oficial y muestra su fecha de actualización.",
      "El dato no es tiempo real y debe contrastarse con el perfil del contratante antes de presentar una oferta.",
      "La reutilización se declara conforme al marco explicado en el aviso legal.",
    ],
  },
  {
    titulo: "Calidad visible",
    texto: [
      "Las fuentes oficiales no siempre publican órgano, importe, CPV o documentos con la misma completitud. TenderFlow conserva los vacíos, mide su cobertura y evita rellenarlos con estimaciones presentadas como hechos.",
    ],
    puntos: [
      "La señal tecnológica distingue título, clasificador y pliegos cuando están disponibles.",
      "Los pliegos se procesan por lotes; la interfaz muestra el estado pendiente en lugar de improvisar un resumen.",
      "Los agregados analíticos se calculan en backend sobre el universo declarado, no sobre la página visible.",
    ],
  },
];

export default function CoberturaPage() {
  return (
    <>
      <PaginaEvidencia
        kicker="Cobertura"
        titulo="Qué entra en TenderFlow y qué queda fuera"
        introduccion="La utilidad del análisis depende de declarar el universo. Estas son las fuentes, reglas de entrada y limitaciones que delimitan cada cifra del producto."
        secciones={SECCIONES}
      />
      <section className="border-border/60 bg-card/40 border-t">
        <div className="mx-auto w-full max-w-4xl px-6 py-12">
          <h2 className="font-display text-2xl font-semibold tracking-normal">Familias observadas</h2>
          <p className="text-muted-foreground mt-3 max-w-[68ch] text-sm leading-relaxed">
            {CONTENIDO.familiasTitulo}
          </p>
          <ul className="mt-6 flex flex-wrap gap-2">
            {CONTENIDO.familias.map((familia) => (
              <li key={familia} className="border-border/70 bg-background rounded-md border px-3 py-1.5 text-sm font-medium">
                {familia}
              </li>
            ))}
          </ul>
          <div className="mt-8 flex flex-wrap gap-x-5 gap-y-3 text-sm font-medium">
            <Link href="/licitaciones" className="text-primary underline-offset-4 hover:underline">
              Explorar por comunidad autónoma
            </Link>
            <Link href="/cpv" className="text-primary underline-offset-4 hover:underline">
              Explorar por código CPV
            </Link>
          </div>
        </div>
      </section>
    </>
  );
}
