"use client";

/**
 * Datos, carriles, filtro, selección y teclado de la agenda.
 *
 * La API fusiona, ordena y clasifica (`GET /pursuits/agenda`); aquí viven
 * el carril activo, el contador que filtra, la fila seleccionada y el teclado
 * —J/K recorren, S sigue, X descarta, C completa la tarea, ⏎ abre—. Lo que
 * esos gestos hacen, que es lo mismo que hacen los botones de cada fila, está
 * en `use-agenda-acciones.ts`.
 *
 * **El carril, el filtro y `solo_mios` viven en la URL** (`?carril=`,
 * `?filtro=`, `?mios=1`), no en `useState`: la agenda es una pantalla que se
 * pasa por chat («mira lo que tengo sin triar»), y un estado que sólo existe en
 * memoria convierte ese enlace en «la agenda, pero por donde tú entres». Se
 * escriben con `replace` porque cambiar de carril no es navegar: llenar el
 * historial de carriles deja el botón «atrás» inservible. Y se escriben sin
 * pasar por el servidor (`lib/url-superficial.ts`): la página es `"use client"`
 * y ningún Server Component lee esos parámetros. El carril y el filtro recortan
 * la respuesta de `/pursuits/agenda` que ya está en caché, y el cambio de
 * `mios` lo pide el propio `usePipelineAgenda` a la API.
 *
 * **El filtro no decide nada.** Qué filas cuentan en cada contador lo dice la
 * API en `item.cuenta_en`, con la misma regla con la que calcula el número;
 * aquí solo se dejan las que lo llevan.
 */

import * as React from "react";
import { useSearchParams } from "next/navigation";
import { useFilters } from "@/lib/filters";
import { queryActual, reemplazarQuery } from "@/lib/url-superficial";
import { type PipelineAgendaItem, usePipelineAgenda } from "@/hooks/use-pursuits";
import {
  type AgendaContador,
  type Carril,
  carrilDe,
  claveDe,
  esContador,
} from "../_components/agenda/agenda-meta";
import { useAgendaAcciones } from "./use-agenda-acciones";

/** Ámbito de la agenda: varias tecnologías o CCAA, separadas por comas (OR). */
function listaDeAmbito(valores: string[]): string | null {
  return valores.length ? valores.join(",") : null;
}

export function useAgenda() {
  const params = useSearchParams();
  const filters = useFilters();
  // El backend acepta listas desde 2026-09-21: se manda **todo** el ámbito
  // elegido. Antes viajaba sólo el primer valor y la pantalla tenía que avisar
  // de que enseñaba menos de lo que el chip prometía.
  const tecnologia = listaDeAmbito(filters.tecnologias);
  const ccaa = listaDeAmbito(filters.ccaas);

  const soloMios = params.get("mios") === "1";

  const { data, isPending, error, refetch } = usePipelineAgenda({ soloMios, tecnologia, ccaa });

  /**
   * Sin reglas activas no puede llegar ninguna señal, así que no hay bandeja
   * que triar. `=== 0` y no «falsy»: una API anterior al campo no lo manda, y
   * ahí no se sabe — el carril se queda como estaba.
   */
  const sinReglas = data?.reglas_activas === 0;
  const carril: Carril =
    params.get("carril") === "triaje" && !sinReglas ? "triaje" : "compromisos";
  const pedido = params.get("filtro");
  // El filtro es de los compromisos: en el triaje no hay contador que valga.
  const filtro: AgendaContador | null =
    carril === "compromisos" && esContador(pedido) ? pedido : null;

  const acciones = useAgendaAcciones();
  const { abrir, completarTarea, descartar, seguir } = acciones;

  const todos = React.useMemo(() => data?.items ?? [], [data]);
  const conteos = React.useMemo(
    () => ({
      compromisos: todos.filter((item) => carrilDe(item) === "compromisos").length,
      triaje: todos.filter((item) => carrilDe(item) === "triaje").length,
    }),
    [todos],
  );
  const items = React.useMemo(
    () =>
      todos.filter(
        (item) =>
          carrilDe(item) === carril && (filtro == null || (item.cuenta_en ?? []).includes(filtro)),
      ),
    [todos, carril, filtro],
  );

  const [selected, setSelected] = React.useState(0);
  const activeIndex = Math.min(selected, Math.max(0, items.length - 1));
  const active: PipelineAgendaItem | undefined = items[activeIndex];

  /**
   * Petición de foco sobre el editor de próxima acción, como contador por fila.
   * Un booleano no serviría: pedirlo dos veces sobre la misma fila no cambiaría
   * el valor y el segundo clic no enfocaría nada.
   */
  const [focoAccion, setFocoAccion] = React.useState<{ clave: string; n: number } | null>(null);

  const escribirParams = React.useCallback((cambios: Record<string, string | null>) => {
    const search = queryActual();
    for (const [clave, valor] of Object.entries(cambios)) {
      if (valor) search.set(clave, valor);
      else search.delete(clave);
    }
    reemplazarQuery(search);
  }, []);

  const setCarril = React.useCallback(
    (next: Carril) => {
      setSelected(0);
      // Al triaje se llega sin filtro: un contador pulsado sobre una lista que
      // no filtra sería un botón encendido que no hace nada.
      escribirParams(
        next === "compromisos" ? { carril: null } : { carril: next, filtro: null },
      );
    },
    [escribirParams],
  );

  /** Pulsar un contador lo pone; pulsarlo otra vez lo quita. */
  const alternarFiltro = React.useCallback(
    (contador: AgendaContador) => {
      setSelected(0);
      escribirParams({ carril: null, filtro: filtro === contador ? null : contador });
    },
    [escribirParams, filtro],
  );

  const alternarSoloMios = React.useCallback(() => {
    setSelected(0);
    escribirParams({ mios: soloMios ? null : "1" });
  }, [escribirParams, soloMios]);

  /** La `next_action` manual no tiene fila que completar: se edita a mano. */
  const editarAccion = React.useCallback((item: PipelineAgendaItem) => {
    setFocoAccion((previo) => ({ clave: claveDe(item), n: (previo?.n ?? 0) + 1 }));
  }, []);

  // Teclado: mismo contrato que el Radar, más `C` para cerrar la tarea activa.
  // Ignorado con el foco en un campo o dentro de un diálogo, que tienen sus
  // propias teclas.
  React.useEffect(() => {
    const onKey = (event: KeyboardEvent) => {
      // El destino puede no ser un elemento (`window`, el documento): ahí no
      // hay foco en ningún control y el atajo es de la lista.
      const target = event.target instanceof HTMLElement ? event.target : null;
      const tag = target?.tagName ?? "";
      if (tag === "INPUT" || tag === "TEXTAREA" || target?.isContentEditable) return;
      if (target?.closest('[role="dialog"]')) return;
      if (event.metaKey || event.ctrlKey || event.altKey) return;
      if (!items.length) return;
      const key = event.key.toLowerCase();
      if (key === "j" || event.key === "ArrowDown") {
        event.preventDefault();
        setSelected((current) => Math.min(current + 1, items.length - 1));
      } else if (key === "k" || event.key === "ArrowUp") {
        event.preventDefault();
        setSelected((current) => Math.max(current - 1, 0));
      } else if (key === "s") {
        event.preventDefault();
        if (active && (active.kind === "senal" || active.kind === "renovacion")) void seguir(active);
      } else if (key === "x") {
        event.preventDefault();
        if (active && active.kind === "senal") descartar(active);
      } else if (key === "c") {
        event.preventDefault();
        if (active?.kind !== "tarea") return;
        if (active.tarea_id == null) editarAccion(active);
        else completarTarea(active);
      } else if (event.key === "Enter") {
        // ⏎ con el foco en un botón o un enlace es de ese control. Se escucha
        // en `window`, así que sin esta salvedad pulsarlo sobre un contador o
        // sobre «Solo míos» abría la ficha de la fila seleccionada. Las filas
        // (`role="button"`) tienen su propio ⏎: abren la fila enfocada, que no
        // siempre es la activa.
        if (tag === "BUTTON" || tag === "A" || target?.getAttribute("role") === "button") return;
        event.preventDefault();
        if (active) abrir(active);
      }
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [abrir, active, completarTarea, descartar, editarAccion, items.length, seguir]);

  return {
    ...acciones,
    data,
    // `isPending` y no `isLoading`: mientras la organización activa no está
    // resuelta la consulta sigue retenida, sin fetch en vuelo, y la agenda
    // tiene que seguir enseñando su esqueleto en vez de su estado vacío.
    isLoading: isPending,
    error,
    refetch,
    items,
    conteos,
    carril,
    setCarril,
    sinReglas,
    filtro,
    alternarFiltro,
    activeIndex,
    active,
    setSelected,
    soloMios,
    alternarSoloMios,
    editarAccion,
    focoAccion: active && focoAccion?.clave === claveDe(active) ? focoAccion.n : 0,
  };
}

export type Agenda = ReturnType<typeof useAgenda>;
