"use client";

import { Fragment } from "react";
import Link from "next/link";
import { ArrowRight } from "lucide-react";
import { PanelTitle } from "@/components/console/panel";
import { Tooltip, TooltipContent, TooltipTrigger } from "@/components/ui/tooltip";
import { findPage } from "@/lib/navigation";
import { useScopedHref } from "@/lib/filters";
import { SPACE_VIEWS } from "@/lib/space-views";

/**
 * Atajos al análisis en profundidad. Los gráficos detallados viven en sus
 * vistas; el Resumen sólo enlaza a ellas para no duplicarlos, y los atajos
 * arrastran el ámbito activo para no perder el contexto al saltar.
 *
 * Eran cuatro tarjetas de 104 px con icono, título y descripción — el mismo
 * peso visual que las tarjetas de «Mercado abierto», que sí traen un dato que
 * caduca. Vuelven a ser lo que son: enlaces, sin icono de página delante (el
 * enlace ya dice su destino, y tres de los cuatro pintaban el mismo glifo del
 * espacio que los absorbe). La descripción pasa a un tooltip, que a diferencia
 * del `title` nativo también se abre con el teclado. El hover solo cambia el
 * color: se ven a diario y nada se desplaza.
 *
 * **Destinos.** Apuntaban a las rutas heredadas (`/tendencias`, `/organos`…),
 * que llegan a su vista de Mercado por un 301, y uno era Proyectos y módulos,
 * una vista marcada `experimental`: la pantalla de entrada no promociona lo que
 * el producto declara a medio hacer. Ahora enlazan directo a
 * `/mercado?vista=…` y salen de `SPACE_VIEWS`, así que una vista que pase a
 * experimental se cae sola de aquí. Con una query propia en el destino,
 * `useWithFilters` descartaría el ámbito: se fusiona con `useScopedHref`.
 */
const ESPACIO = "mercado";
const VISTAS = ["tiempo", "tecnologias", "organos"] as const;

const ATAJOS = VISTAS.flatMap((clave) => {
  const vista = SPACE_VIEWS[ESPACIO]?.find((candidata) => candidata.key === clave);
  if (!vista || vista.visibility === "experimental") return [];
  // Nombre y descripción salen de la ficha de la ruta que la vista absorbió
  // (`lib/navigation.ts`): «Tendencias» se entiende fuera de Mercado, «Tiempo»
  // —el nombre de la pestaña— no.
  const pagina = vista.from ? findPage(vista.from) : undefined;
  return [
    {
      clave,
      label: pagina?.label ?? vista.label,
      href: `/${ESPACIO}?vista=${clave}`,
      descripcion: pagina?.description,
    },
  ];
});

export function AtajosAnalisis() {
  const scopedHref = useScopedHref();

  return (
    <section aria-labelledby="atajos-analisis-title">
      <PanelTitle
        as="h2"
        id="atajos-analisis-title"
        title="Análisis completo"
        hint="con tu ámbito aplicado"
        className="mb-2.5"
      />
      <div className="flex flex-wrap gap-2">
        {ATAJOS.map((atajo) => {
          const enlace = (
            <Link
              href={scopedHref(atajo.href)}
              aria-label={`Ir a ${atajo.label}, en Mercado`}
              className="group inline-flex h-8 items-center gap-2 rounded-md border border-border/60 bg-card px-3 text-tf-meta font-medium transition-colors hover:border-primary/50 active:bg-primary/10 active:duration-0"
            >
              {atajo.label}
              <ArrowRight
                className="h-3 w-3 flex-none text-muted-foreground transition-colors group-hover:text-primary"
                aria-hidden="true"
              />
            </Link>
          );
          if (!atajo.descripcion) return <Fragment key={atajo.clave}>{enlace}</Fragment>;
          return (
            <Tooltip key={atajo.clave}>
              <TooltipTrigger asChild>{enlace}</TooltipTrigger>
              <TooltipContent className="max-w-xs">{atajo.descripcion}</TooltipContent>
            </Tooltip>
          );
        })}
      </div>
    </section>
  );
}
