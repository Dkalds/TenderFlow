"use client";

import Link from "next/link";
import { useSyncExternalStore } from "react";
import { ArrowRight, Check, Users } from "lucide-react";
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
 */

// Texto a plena tinta (`text-foreground`) en los chips tintados: a 10px,
// `text-primary` sobre `bg-primary/12` y el verde sobre su tinte quedaban por
// debajo del 4.5:1 que exige el E2E de accesibilidad. El estado nunca dependió
// del color (viaja en el texto y en el icono ✓), así que la semántica queda en
// el fondo tintado.
const CHIP: Record<EstadoPaso, string> = {
  hecho: "bg-[hsl(var(--success)/0.14)] text-foreground",
  pendiente: "bg-primary/12 text-foreground",
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
          "w-[84px] flex-none rounded px-1.5 py-0.5 text-center text-[10px] font-semibold",
          CHIP[paso.estado],
        )}
      >
        {ETIQUETA[paso.estado]}
      </span>
      {paso.estado === "hecho" ? (
        <Check className="h-3.5 w-3.5 flex-none text-[hsl(var(--success))]" aria-hidden="true" />
      ) : (
        <Icon className="text-muted-foreground h-3.5 w-3.5 flex-none" aria-hidden="true" />
      )}
      <span
        className={cn(
          "flex-none text-[11.5px] font-medium",
          paso.estado === "hecho" && "text-muted-foreground",
        )}
      >
        {paso.titulo}
      </span>
      <span className="text-muted-foreground min-w-0 flex-1 truncate text-[10.5px]">
        {paso.gana}
      </span>
      {paso.estado === "pendiente" && (
        <>
          <span className="text-primary hidden flex-none whitespace-nowrap text-[11px] font-medium md:inline">
            {paso.cta}
          </span>
          <ArrowRight className="text-muted-foreground h-3 w-3 flex-none" aria-hidden="true" />
        </>
      )}
    </>
  );
}

export function PrimerosPasos({ onDescartar }: { onDescartar?: () => void }) {
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
      <div className="mb-2.5 flex items-baseline gap-2.5">
        <h2 id="resumen-primeros-pasos" className="text-xs font-semibold">
          Primeros pasos
        </h2>
        <span className="text-muted-foreground min-w-0 flex-1 truncate text-[10.5px]">
          <span>{etiquetaProgreso(progreso)}</span>
          {" · sin esto el Radar y Tu día no hablan de tu negocio"}
        </span>
        <button
          type="button"
          onClick={ocultar}
          aria-label="Ocultar los primeros pasos"
          className="text-muted-foreground hover:text-foreground focus-visible:ring-ring flex-none whitespace-nowrap rounded text-[11px] font-medium transition-colors duration-140 ease-out focus-visible:outline-none focus-visible:ring-2"
        >
          Ocultar
        </button>
      </div>

      <ol className="border-border/60 bg-card/70 overflow-hidden rounded-xl border">
        {pasos.map((paso) => (
          <li key={paso.id} className="border-border/25 border-b last:border-b-0">
            {paso.estado === "pendiente" ? (
              <Link
                href={paso.href}
                className={cn(FILA, "hover:bg-primary/4 transition-colors duration-140 ease-out")}
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
      <p className="text-muted-foreground mt-2 flex items-center gap-2 px-1 text-[10.5px]">
        <Users className="h-3 w-3 flex-none" aria-hidden="true" />
        <span className="min-w-0 flex-1">
          Las reglas, los pursuits y las decisiones pertenecen a la organización, no a tu usuario.
        </span>
        <Link href="/equipo" className="text-primary flex-none whitespace-nowrap hover:underline">
          Gestionar el equipo →
        </Link>
      </p>
    </section>
  );
}
