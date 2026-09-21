"use client";

/**
 * Datos, carriles, selección y gestos de la agenda.
 *
 * El backend fusiona, ordena y clasifica (`GET /pursuits/agenda`); aquí viven
 * el carril activo, la fila seleccionada, el teclado —J/K recorren, S sigue, X
 * descarta, C completa la tarea, ⏎ abre— y las acciones que esos gestos
 * comparten con los botones de cada fila.
 *
 * **El carril y `solo_mios` viven en la URL** (`?carril=`, `?mios=1`), no en
 * `useState`: la agenda es una pantalla que se pasa por chat («mira lo que
 * tengo sin triar»), y un estado que sólo existe en memoria convierte ese
 * enlace en «la agenda, pero por donde tú entres». Se escriben con `replace`
 * porque cambiar de carril no es navegar: llenar el historial de carriles deja
 * el botón «atrás» inservible.
 */

import * as React from "react";
import { useRouter, useSearchParams } from "next/navigation";
import { toast } from "sonner";
import { useFilters } from "@/lib/filters";
import { useOrganizationStore } from "@/hooks/use-organization";
import { useDismissRadarTender, useRestoreRadarTender } from "@/hooks/use-radar";
import { useActualizarTarea } from "@/hooks/use-pursuit-tasks";
import {
  type PipelineAgendaItem,
  useCreatePursuit,
  usePipelineAgenda,
} from "@/hooks/use-pursuits";
import {
  type Carril,
  carrilDe,
  claveDe,
  DIAS_POSPONER,
  tituloDe,
} from "../_components/agenda/agenda-meta";

/** Ámbito de la agenda: varias tecnologías o CCAA, separadas por comas (OR). */
function listaDeAmbito(valores: string[]): string | null {
  return valores.length ? valores.join(",") : null;
}

export function useAgenda() {
  const router = useRouter();
  const params = useSearchParams();
  const filters = useFilters();
  // El backend acepta listas desde 2026-09-21: se manda **todo** el ámbito
  // elegido. Antes viajaba sólo el primer valor y la pantalla tenía que avisar
  // de que enseñaba menos de lo que el chip prometía.
  const tecnologia = listaDeAmbito(filters.tecnologias);
  const ccaa = listaDeAmbito(filters.ccaas);

  const carril: Carril = params.get("carril") === "triaje" ? "triaje" : "compromisos";
  const soloMios = params.get("mios") === "1";

  const { data, isPending, error, refetch } = usePipelineAgenda({ soloMios, tecnologia, ccaa });

  const createPursuit = useCreatePursuit();
  const dismissTender = useDismissRadarTender();
  const restoreTender = useRestoreRadarTender();
  const actualizarTarea = useActualizarTarea();
  const setActiveOrganizationId = useOrganizationStore((state) => state.setActiveOrganizationId);

  const todos = React.useMemo(() => data?.items ?? [], [data]);
  const conteos = React.useMemo(
    () => ({
      compromisos: todos.filter((item) => carrilDe(item) === "compromisos").length,
      triaje: todos.filter((item) => carrilDe(item) === "triaje").length,
    }),
    [todos],
  );
  const items = React.useMemo(
    () => todos.filter((item) => carrilDe(item) === carril),
    [todos, carril],
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

  const escribirParam = React.useCallback(
    (clave: string, valor: string | null) => {
      const search = new URLSearchParams(params.toString());
      if (valor) search.set(clave, valor);
      else search.delete(clave);
      router.replace(`?${search.toString()}`, { scroll: false });
    },
    [params, router],
  );

  const setCarril = React.useCallback(
    (next: Carril) => {
      setSelected(0);
      escribirParam("carril", next === "compromisos" ? null : next);
    },
    [escribirParam],
  );

  const alternarSoloMios = React.useCallback(() => {
    setSelected(0);
    escribirParam("mios", soloMios ? null : "1");
  }, [escribirParam, soloMios]);

  const seguir = React.useCallback(
    async (item: PipelineAgendaItem) => {
      try {
        const pursuit = await createPursuit.mutateAsync({ licitacion_id: item.licitacion_id });
        setActiveOrganizationId(pursuit.organization_id);
        toast.success(
          item.kind === "renovacion" ? "Renovación anticipada como pursuit" : "Oportunidad abierta",
        );
        router.push(`/oportunidades/${pursuit.id}`);
      } catch (err) {
        toast.error(err instanceof Error ? err.message : "No se pudo abrir la oportunidad");
      }
    },
    [createPursuit, router, setActiveOrganizationId],
  );

  const descartar = React.useCallback(
    (item: PipelineAgendaItem) => {
      dismissTender.mutate({ idExterno: item.licitacion_id });
      toast("Señal descartada", {
        description: item.titulo ?? undefined,
        action: { label: "Deshacer", onClick: () => restoreTender.mutate(item.licitacion_id) },
      });
    },
    [dismissTender, restoreTender],
  );

  /**
   * Posponer: el mismo triaje del Radar con caducidad (`accion: "posponer"`).
   * La señal vuelve sola pasada la semana, así que «ahora no» deja de ser
   * indistinguible de «nunca» — que es lo que era descartar.
   */
  const posponer = React.useCallback(
    (item: PipelineAgendaItem) => {
      dismissTender.mutate({
        idExterno: item.licitacion_id,
        accion: "posponer",
        dias: DIAS_POSPONER,
      });
      toast(`Señal pospuesta ${DIAS_POSPONER} días`, {
        description: item.titulo ?? undefined,
        action: { label: "Deshacer", onClick: () => restoreTender.mutate(item.licitacion_id) },
      });
    },
    [dismissTender, restoreTender],
  );

  /**
   * Completar la tarea de la fila. Siempre con deshacer: es la única acción de
   * escritura que el teclado dispara, y una tecla que cierra trabajo sin vuelta
   * atrás convierte un dedo torpe en una tarea perdida.
   */
  const completarTarea = React.useCallback(
    (item: PipelineAgendaItem) => {
      const pursuitId = item.pursuit_id;
      const taskId = item.tarea_id;
      if (pursuitId == null || taskId == null) return;
      actualizarTarea.mutate(
        { pursuitId, taskId, estado: "hecha" },
        {
          onSuccess: () =>
            toast.success("Tarea completada", {
              description: tituloDe(item),
              action: {
                label: "Deshacer",
                onClick: () =>
                  actualizarTarea.mutate({ pursuitId, taskId, estado: "pendiente" }),
              },
            }),
          onError: (err) =>
            toast.error(err instanceof Error ? err.message : "No se pudo completar la tarea"),
        },
      );
    },
    [actualizarTarea],
  );

  /** La `next_action` manual no tiene fila que completar: se edita a mano. */
  const editarAccion = React.useCallback((item: PipelineAgendaItem) => {
    setFocoAccion((previo) => ({ clave: claveDe(item), n: (previo?.n ?? 0) + 1 }));
  }, []);

  const abrir = React.useCallback(
    (item: PipelineAgendaItem) => {
      if (item.kind === "senal") {
        void seguir(item);
        return;
      }
      const pursuitId =
        item.kind === "contrato" ? (item.renovacion_pursuit_id ?? item.pursuit_id) : item.pursuit_id;
      if (pursuitId != null) {
        router.push(`/oportunidades/${pursuitId}`);
        return;
      }
      void seguir(item);
    },
    [router, seguir],
  );

  // Teclado: mismo contrato que el Radar, más `C` para cerrar la tarea activa.
  // Ignorado con el foco en un campo.
  React.useEffect(() => {
    const onKey = (event: KeyboardEvent) => {
      const target = event.target as HTMLElement | null;
      const tag = target?.tagName ?? "";
      if (tag === "INPUT" || tag === "TEXTAREA" || target?.isContentEditable) return;
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
        event.preventDefault();
        if (active) abrir(active);
      }
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [abrir, active, completarTarea, descartar, editarAccion, items.length, seguir]);

  return {
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
    activeIndex,
    active,
    setSelected,
    soloMios,
    alternarSoloMios,
    seguir,
    descartar,
    posponer,
    abrir,
    completarTarea,
    editarAccion,
    focoAccion: active && focoAccion?.clave === claveDe(active) ? focoAccion.n : 0,
    verRenovacion: (pursuitId: number) => router.push(`/oportunidades/${pursuitId}`),
    irAlRadar: () => router.push("/radar"),
  };
}

export type Agenda = ReturnType<typeof useAgenda>;
