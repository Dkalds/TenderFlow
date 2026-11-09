"use client";

import * as React from "react";
import { alQuedarOcioso } from "@/lib/al-quedar-ocioso";

/**
 * Menús y popovers del marco cuyo Radix llega después de pintar.
 *
 * El marco del dashboard (rail y barra de ámbito) pinta cuatro disparadores
 * —menú de cuenta, exportar, campana y vistas guardadas— y el «+ Añadir» del
 * ámbito. Todos arrancan cerrados, y aun así Radix Menu y Radix Popover
 * viajaban en el First Load de cada pantalla. Aquí se pinta primero un
 * disparador provisional idéntico (mismas clases y mismo nombre accesible) y
 * la pieza real se descarga cuando el navegador queda ocioso, o antes si te
 * acercas, la enfocas o la pulsas. Al llegar sustituye al provisional:
 *
 * - si la pulsaste antes, se monta abierta (`abrirAlMontar`), y si fue con el
 *   teclado el foco va a la primera opción, como hace Radix;
 * - si el provisional tenía el foco, lo recoge el disparador real
 *   (`enfocarAlMontar`), así que el teclado no se pierde en el cambio.
 *
 * Se descarga con un `import()` a pelo y el componente se guarda en estado, no
 * con `next/dynamic`: `React.lazy` suspende un fotograma aunque el módulo ya
 * esté, y ese fotograma pintaría otro nodo y tiraría el foco.
 */

/** Cómo llega a montarse la pieza real. */
export interface MontajeDiferido {
  /** Se pidió abrirla desde el disparador provisional, y con qué. */
  abrirAlMontar?: "puntero" | "teclado";
  /** El disparador provisional tenía el foco. */
  enfocarAlMontar?: boolean;
}

/** Lo que el disparador provisional tiene que llevar puesto. */
export interface EventosDisparador {
  onPointerEnter: () => void;
  onPointerDown: (event: React.PointerEvent) => void;
  onFocus: () => void;
  onBlur: () => void;
  onClick: (event: React.MouseEvent) => void;
  onKeyDown: (event: React.KeyboardEvent) => void;
}

export function Diferido<P extends object>({
  cargar,
  props,
  disparador,
  abreCon,
  montarYa = false,
}: {
  /** El `import()` del módulo, resuelto al componente real. */
  cargar: () => Promise<React.ComponentType<P & MontajeDiferido>>;
  props: P;
  disparador: (eventos: EventosDisparador) => React.ReactNode;
  /**
   * Con qué abre la pieza real: un menú de Radix abre al pulsar (`pointerdown`
   * y teclas), un popover al hacer clic. Abrir el popover al pulsar haría que
   * el clic de después, ya sobre el disparador real, lo volviera a cerrar.
   */
  abreCon: "pulsar" | "clic";
  /** Algo de fuera la abre (la paleta abre las vistas guardadas): se monta ya. */
  montarYa?: boolean;
}) {
  const [Real, setReal] = React.useState<React.ComponentType<P & MontajeDiferido> | null>(null);
  const [montaje, setMontaje] = React.useState<MontajeDiferido>({});
  const [pedido, setPedido] = React.useState(false);
  const traer = React.useCallback(() => setPedido(true), []);
  const descargar = pedido || montarYa;

  React.useEffect(() => alQuedarOcioso(traer), [traer]);
  React.useEffect(() => {
    if (!descargar || Real) return;
    let vigente = true;
    cargar().then(
      (componente) => {
        if (vigente) setReal(() => componente);
      },
      () => {
        // Sin red: el provisional sigue ahí y el próximo gesto lo reintenta.
        if (vigente) setPedido(false);
      },
    );
    return () => {
      vigente = false;
    };
  }, [descargar, Real, cargar]);

  if (Real) return <Real {...props} {...montaje} />;

  const abrir = (con: "puntero" | "teclado") => {
    setMontaje((previo) => (previo.abrirAlMontar ? previo : { ...previo, abrirAlMontar: con }));
    traer();
  };

  return disparador({
    onPointerEnter: traer,
    onPointerDown: (event) => {
      if (abreCon === "pulsar" && event.button === 0 && !event.ctrlKey) abrir("puntero");
    },
    onFocus: () => {
      setMontaje((previo) => ({ ...previo, enfocarAlMontar: true }));
      traer();
    },
    onBlur: () => setMontaje((previo) => ({ ...previo, enfocarAlMontar: false })),
    // Un clic sin puntero (`detail` 0) es Intro o Espacio sobre el botón, o el
    // clic virtual de un lector de pantalla.
    onClick: (event) => abrir(event.detail === 0 ? "teclado" : "puntero"),
    onKeyDown: (event) => {
      if (abreCon === "pulsar" && ["Enter", " ", "ArrowDown"].includes(event.key)) {
        event.preventDefault();
        abrir("teclado");
      }
    },
  });
}

/**
 * Lado real: el ref del disparador y si arranca abierto. Lo que llega por
 * props se lee una vez, al montar.
 */
export function useMontajeDiferido({ abrirAlMontar, enfocarAlMontar }: MontajeDiferido) {
  const disparador = React.useRef<HTMLButtonElement>(null);
  const [inicial] = React.useState({ abrirAlMontar, enfocarAlMontar });

  React.useEffect(() => {
    if (inicial.abrirAlMontar === "teclado") {
      // Abierto con el teclado, Radix lleva el foco a la primera opción del
      // menú; aquí no puede, porque la tecla llegó antes de que él escuchara.
      // Su contenido es el que nombra el `aria-controls` del disparador. Un
      // popover no tiene opciones de menú: ahí el foco ya lo pone Radix.
      const marco = requestAnimationFrame(() => {
        const contenido = document.getElementById(disparador.current?.getAttribute("aria-controls") ?? "");
        contenido?.querySelector<HTMLElement>('[role="menuitem"]:not([data-disabled])')?.focus();
      });
      return () => cancelAnimationFrame(marco);
    }
    // Abierto, el foco lo mueve Radix al contenido; cerrado, se queda en el botón.
    if (inicial.enfocarAlMontar && !inicial.abrirAlMontar) disparador.current?.focus();
  }, [inicial]);

  return { disparador, abiertoAlMontar: inicial.abrirAlMontar !== undefined };
}
