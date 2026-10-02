"use client";

import Link from "next/link";
import { useSyncExternalStore } from "react";
import { Check } from "lucide-react";
import { EnlaceIr, PanelTitle, SUPERFICIE_PANEL } from "@/components/console/panel";
import { Button } from "@/components/ui/button";
import { cn } from "@/lib/utils";
import {
  estaDescartado,
  estaDescartadoEnServidor,
  marcarDescartado,
  suscribirDescarte,
} from "@/components/onboarding/descarte";
import {
  debeMostrarse,
  derivarPasos,
  etiquetaProgreso,
  progresoDe,
  progresoParaTelemetria,
  type EstadoPaso,
  type PasoDerivado,
  type Progreso,
} from "@/components/onboarding/pasos";
import { registrarEvento } from "@/lib/analytics";
import { useSenalesOnboarding } from "@/components/onboarding/use-estado-onboarding";

/**
 * Primeros pasos — la banda que le faltaba a la entrada.
 *
 * No es un tour, ni un modal, ni un carrusel: el repo tiene un presupuesto de
 * movimiento explícito (`docs/frontend-motion.md`) y una cultura de densidad,
 * así que esto son tres filas del mismo alto que las de «Tu día», cada una con
 * lo que el usuario se está perdiendo y el enlace al sitio donde se arregla.
 *
 * Lo que la hace distinta de un cartel de bienvenida es que **se apaga sola**:
 * el estado sale de la API (`components/onboarding/pasos.ts` documenta de dónde
 * exactamente), de modo que en cuanto los tres pasos están hechos la banda deja
 * de renderizarse, y un usuario veterano no la ve nunca. Mientras se comprueba
 * tampoco aparece: entrar tarde es mejor que abrir la pantalla afirmando una
 * carencia que puede resultar falsa (ADR-014).
 *
 * El botón «Ocultar» es la salida explícita. Al desmontar la sección el foco se
 * quedaría huérfano, así que se avisa al contenedor con `onDescartar` para que
 * lo recoja — el foco no puede caerse al `body` sin más.
 *
 * **Dónde va.** Debajo de «Tu día», para no desplazar la tesis de la pantalla…
 * salvo en una cuenta recién creada. Ahí lo primero que se veía era «sin
 * cambios», cuatro ceros y una agenda vacía, y lo único accionable quedaba
 * debajo. Así que con los tres pasos **confirmados** pendientes la banda sube
 * arriba del todo, y en cuanto hay uno hecho vuelve a su sitio
 * (`posicionDe`). Con alguno sin comprobar se queda abajo: subirla sería
 * afirmar una cuenta vacía que puede no serlo, la misma regla que la tiene
 * oculta mientras carga.
 */

export type PosicionPrimerosPasos = "arriba" | "abajo";

/** Arriba solo con cero pasos hechos y ninguno por comprobar. */
export function posicionDe(progreso: Progreso): PosicionPrimerosPasos {
  return progreso.hechos === 0 && progreso.sinResolver === 0 ? "arriba" : "abajo";
}

// Texto a plena tinta (`text-foreground`) en los chips tintados: a 11 px,
// `text-primary` sobre su tinte y el verde sobre el suyo quedaban por debajo del
// 4,5:1 que exige el E2E de accesibilidad. El estado nunca dependió del color
// (viaja en el texto y en el icono ✓), así que la semántica queda en el fondo.
const CHIP: Record<EstadoPaso, string> = {
  hecho: "bg-success/10 text-foreground",
  pendiente: "bg-primary/10 text-foreground",
  cargando: "bg-secondary text-muted-foreground",
  desconocido: "bg-secondary text-muted-foreground",
};

/**
 * El estado va en texto, no sólo en color: «pendiente» y «hecho» no pueden
 * distinguirse únicamente por el tono del chip.
 */
const ETIQUETA: Record<EstadoPaso, string> = {
  hecho: "hecho",
  pendiente: "pendiente",
  cargando: "comprobando",
  desconocido: "sin comprobar",
};

const FILA = "flex items-center gap-2.5 px-3.5 py-2";

function ContenidoFila({ paso }: { paso: PasoDerivado }) {
  const Icon = paso.icon;
  return (
    <>
      <span
        className={cn(
          "w-[84px] flex-none rounded-sm px-1.5 py-0.5 text-center text-tf-micro font-semibold",
          CHIP[paso.estado],
        )}
      >
        {ETIQUETA[paso.estado]}
      </span>
      {paso.estado === "hecho" ? (
        <Check className="h-3.5 w-3.5 flex-none text-success" aria-hidden="true" />
      ) : (
        <Icon className="h-3.5 w-3.5 flex-none text-muted-foreground" aria-hidden="true" />
      )}
      <span
        className={cn(
          "flex-none text-tf-meta font-medium",
          paso.estado === "hecho" && "text-muted-foreground",
        )}
      >
        {paso.titulo}
      </span>
      <span className="min-w-0 flex-1 truncate text-tf-micro text-muted-foreground">{paso.gana}</span>
      {/* La fila entera es el enlace: la llamada a la acción va en texto, sin
          flecha detrás. */}
      {paso.estado === "pendiente" && (
        <span className="hidden flex-none whitespace-nowrap text-tf-micro font-medium text-primary md:inline">
          {paso.cta}
        </span>
      )}
    </>
  );
}

export function PrimerosPasos({
  onDescartar,
  posicion,
}: {
  onDescartar?: () => void;
  /**
   * El hueco de la pantalla que ocupa esta instancia. La vista monta una en
   * cada hueco y solo se pinta la que coincide con `posicionDe`; las consultas
   * se comparten (misma clave). Sin `posicion` se pinta donde se monte.
   */
  posicion?: PosicionPrimerosPasos;
}) {
  // El descarte se lee como store externo, no en un efecto: así el primer
  // render del cliente ya sabe si la banda está oculta y las tres queries no
  // llegan a lanzarse en quien no las necesita. En servidor no hay preferencia
  // que leer, pero da igual: allí las señales están todas «cargando» y la banda
  // no se pinta de todos modos, así que no hay desajuste de hidratación.
  const descartado = useSyncExternalStore(
    suscribirDescarte,
    estaDescartado,
    estaDescartadoEnServidor,
  );

  const senales = useSenalesOnboarding(!descartado);
  const pasos = derivarPasos(senales);

  if (descartado) return null;
  if (!debeMostrarse(pasos)) return null;

  const progreso = progresoDe(pasos);
  if (posicion && posicionDe(progreso) !== posicion) return null;

  function ocultar() {
    marcarDescartado();
    // La otra mitad del embudo: los pasos hechos dicen quién se activa, y esto
    // dice quién se planta. La banda sólo se pinta con algo pendiente, así que
    // pulsar aquí es siempre un rechazo, no un «ya está»; `progreso` distingue
    // el rechazo de entrada (`"0"`) del abandono con casi todo hecho (`"2"`),
    // que señalan a problemas distintos. Va antes de `onDescartar` porque ese
    // callback desmonta la sección.
    registrarEvento("onboarding_ocultado", { progreso: progresoParaTelemetria(progreso) });
    onDescartar?.();
  }

  return (
    <section aria-labelledby="resumen-primeros-pasos" className="mb-5.5">
      <PanelTitle
        as="h2"
        id="resumen-primeros-pasos"
        title="Primeros pasos"
        hint={<span>{etiquetaProgreso(progreso)}</span>}
        actions={
          <Button
            type="button"
            variant="ghost"
            size="sm"
            onClick={ocultar}
            aria-label="Ocultar los primeros pasos"
            className="text-muted-foreground"
          >
            Ocultar
          </Button>
        }
        className="mb-2.5"
      />

      <ol className={cn(SUPERFICIE_PANEL, "overflow-hidden")}>
        {pasos.map((paso) => (
          <li key={paso.id} className="border-b border-border/25 last:border-b-0">
            {paso.estado === "pendiente" ? (
              <Link
                href={paso.href}
                className={cn(
                  FILA,
                  "transition-colors hover:bg-primary/5 active:bg-primary/10 active:duration-0",
                )}
              >
                <ContenidoFila paso={paso} />
              </Link>
            ) : (
              <div className={FILA}>
                <ContenidoFila paso={paso} />
              </div>
            )}
          </li>
        ))}
      </ol>

      {/* El equipo no es un paso: quien trabaja solo no lo hará nunca y la banda
          no podría apagarse. Va como nota, y no cuenta en el progreso. */}
      <p className="mt-2 flex flex-wrap items-center gap-x-2 gap-y-1 px-1 text-tf-micro text-muted-foreground">
        <span className="min-w-0 flex-1">
          Las reglas, las oportunidades y las decisiones son de la organización, no de tu usuario.
        </span>
        <EnlaceIr href="/equipo" className="flex-none text-tf-micro">
          Gestionar el equipo
        </EnlaceIr>
      </p>
    </section>
  );
}
