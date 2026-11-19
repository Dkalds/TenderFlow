"use client"

import * as React from "react"
import { Slot } from "@radix-ui/react-slot"
import type * as TooltipPrimitive from "@radix-ui/react-tooltip"
import { alQuedarOcioso } from "@/lib/al-quedar-ocioso"

/**
 * Tooltips con la API de Radix y su Radix fuera del First Load.
 *
 * Radix Tooltip trae su popper y floating-ui (~35 KB sin comprimir) y el marco
 * pinta tooltips en el rail y la barra de ámbito: viajaba en la carga inicial
 * de todas las pantallas. Aquí se pinta primero el disparador tal cual (mismo
 * nodo y props, `data-state="closed"`) sin contenido, que es lo que Radix pinta
 * cerrado. El Radix real (`tooltip-radix.tsx`) se descarga al quedar ocioso el
 * navegador, o antes si te acercas o enfocas un disparador; desde entonces cada
 * tooltip nace real. El cambio vuelve a montar el disparador, así que: si tenía
 * el foco, el nuevo lo recoge (sin abrir si el foco vino de un clic, como
 * Radix); si el puntero estaba encima, un `pointermove` lo abre tras su retardo
 * sin esperar a que muevas el ratón; y con un botón pulsado no se cambia, para
 * no partir el clic entre dos nodos. En táctil, como Radix: no abre con el dedo.
 */

type ModuloRadix = typeof import("./tooltip-radix")

let modulo: ModuloRadix | null = null
let pendiente: Promise<ModuloRadix> | null = null
const oyentes = new Set<() => void>()

/** Descarga el Radix real una sola vez. Lo usa también el setup de los tests. */
export function cargarTooltip(): Promise<ModuloRadix> {
  pendiente ??= import("./tooltip-radix").then(
    (cargado) => {
      modulo = cargado
      for (const oyente of oyentes) oyente()
      return cargado
    },
    (error: unknown) => {
      // Sin red: el provisional sigue y el próximo acercamiento lo reintenta.
      pendiente = null
      throw error
    },
  )
  return pendiente
}

function pedir() {
  cargarTooltip().catch(() => {})
}

function suscribir(oyente: () => void) {
  oyentes.add(oyente)
  return () => {
    oyentes.delete(oyente)
  }
}

function useRadix(): ModuloRadix | null {
  // En la hidratación, el provisional que pintó el servidor.
  return React.useSyncExternalStore(suscribir, () => modulo, () => null)
}

// `skipDelayDuration` (emil-design-eng): el primer tooltip espera su retardo y,
// visto uno, los vecinos abren al instante. Cada raíz real lleva su propio
// Provider de Radix, así que el «se ha visto uno» se lleva aquí, entre todas.
const visibles = { abiertos: 0, ultimoCierre: Number.NEGATIVE_INFINITY }

interface Config {
  delayDuration: number
  skipDelayDuration: number
  disableHoverableContent?: boolean
}

// Sin valor por defecto: un `Tooltip` sin `TooltipProvider` lanza, como en Radix.
const ConfigTooltips = React.createContext<Config | null>(null)

function useConfigTooltips(): Config {
  const config = React.useContext(ConfigTooltips)
  if (!config) throw new Error("`Tooltip` must be used within `TooltipProvider`")
  return config
}

/** Monta una vez cerca de la raíz del dashboard (`app/(dashboard)/layout.tsx`). */
function TooltipProvider({
  delayDuration = 300,
  skipDelayDuration = 300,
  disableHoverableContent,
  children,
}: Partial<Config> & { children?: React.ReactNode }) {
  React.useEffect(() => alQuedarOcioso(pedir), [])
  const config = React.useMemo(
    () => ({ delayDuration, skipDelayDuration, disableHoverableContent }),
    [delayDuration, skipDelayDuration, disableHoverableContent],
  )
  return <ConfigTooltips.Provider value={config}>{children}</ConfigTooltips.Provider>
}

/** Lo que el provisional vio y el real necesita al montarse. */
interface Marcas {
  nodo: HTMLElement | null
  conFoco: boolean
  focoPorPuntero: boolean
  /** `pointerType` del puntero que está encima, o null. */
  punteroEncima: string | null
  /** El real no debe abrir con el `focus` que le devuelve el foco. */
  silenciarFoco: boolean
}

interface Instancia {
  radix: ModuloRadix | null
  anotar: (cambios: Partial<Marcas>) => void
  /** Si este `focus` es el que devuelve el foco tras un clic (y lo consume). */
  focoDevuelto: () => boolean
  refrescar: () => void
  pulsar: () => void
}

/** Un callback ref que reparte el nodo entre varios refs. */
function juntarRefs<T>(refs: Array<React.Ref<T> | undefined>): React.RefCallback<T> {
  return (nodo) => {
    for (const ref of refs) {
      if (typeof ref === "function") ref(nodo)
      else if (ref) ref.current = nodo
    }
  }
}

const InstanciaTooltip = React.createContext<Instancia | null>(null)

function useInstancia(pieza: string): Instancia {
  const instancia = React.useContext(InstanciaTooltip)
  if (!instancia) throw new Error(`\`${pieza}\` must be used within \`Tooltip\``)
  return instancia
}

function Tooltip({
  open,
  defaultOpen,
  onOpenChange,
  delayDuration,
  disableHoverableContent,
  children,
}: React.ComponentProps<typeof TooltipPrimitive.Root>) {
  const config = useConfigTooltips()
  const cargado = useRadix()
  // Solo lo tocan los eventos y los efectos, nunca el render.
  const marcas = React.useRef<Marcas>({
    nodo: null, conFoco: false, focoPorPuntero: false, punteroEncima: null, silenciarFoco: false,
  })
  const [pulsado, setPulsado] = React.useState(false)
  const [sinEspera, setSinEspera] = React.useState(false)
  const abierto = React.useRef(false)
  // Al entrar el puntero, antes del `pointermove` con el que Radix abre.
  const refrescar = React.useCallback(() => {
    setSinEspera(
      visibles.abiertos > 0 || performance.now() - visibles.ultimoCierre < config.skipDelayDuration,
    )
  }, [config.skipDelayDuration])
  const radix = pulsado ? null : cargado
  const real = radix !== null

  // Abierto desde fuera (la pista del glosario abre al tocarla) sin el Radix aún.
  React.useEffect(() => {
    if (open && !cargado) pedir()
  }, [open, cargado])

  React.useEffect(
    () => () => {
      if (abierto.current) visibles.abiertos -= 1
    },
    [],
  )

  // Al pasar del provisional al real: el disparador es otro nodo.
  React.useLayoutEffect(() => {
    if (!real) return
    const m = marcas.current
    const nodo = m.nodo
    if (!nodo) return
    if (m.conFoco && !nodo.contains(document.activeElement)) {
      m.silenciarFoco = m.focoPorPuntero
      nodo.focus()
    }
    if (m.punteroEncima && m.punteroEncima !== "touch" && typeof PointerEvent === "function") {
      nodo.dispatchEvent(new PointerEvent("pointermove", { bubbles: true, pointerType: m.punteroEncima }))
    }
  }, [real, marcas])

  const pulsar = React.useCallback(() => {
    setPulsado(true)
    const soltar = () => setPulsado(false)
    window.addEventListener("pointerup", soltar, { once: true })
    window.addEventListener("pointercancel", soltar, { once: true })
  }, [])

  const anotar = React.useCallback((cambios: Partial<Marcas>) => {
    Object.assign(marcas.current, cambios)
  }, [])
  const focoDevuelto = React.useCallback(() => {
    const devuelto = marcas.current.silenciarFoco
    marcas.current.silenciarFoco = false
    return devuelto
  }, [])

  const instancia = React.useMemo(
    () => ({ radix, anotar, focoDevuelto, refrescar, pulsar }),
    [radix, anotar, focoDevuelto, refrescar, pulsar],
  )

  if (!radix) {
    return <InstanciaTooltip.Provider value={instancia}>{children}</InstanciaTooltip.Provider>
  }

  const alCambiar = (siguiente: boolean) => {
    if (siguiente !== abierto.current) {
      abierto.current = siguiente
      visibles.abiertos += siguiente ? 1 : -1
      if (!siguiente) visibles.ultimoCierre = performance.now()
    }
    onOpenChange?.(siguiente)
  }

  return (
    <InstanciaTooltip.Provider value={instancia}>
      <radix.Raiz
        open={open}
        defaultOpen={defaultOpen}
        onOpenChange={alCambiar}
        delayDuration={sinEspera ? 0 : (delayDuration ?? config.delayDuration)}
        skipDelayDuration={config.skipDelayDuration}
        disableHoverableContent={disableHoverableContent ?? config.disableHoverableContent}
      >
        {children}
      </radix.Raiz>
    </InstanciaTooltip.Provider>
  )
}

function TooltipTrigger({
  asChild,
  ref,
  onPointerEnter,
  onPointerLeave,
  onPointerDown,
  onFocus,
  onBlur,
  ...props
}: React.ComponentProps<typeof TooltipPrimitive.Trigger>) {
  const { radix, anotar, focoDevuelto, refrescar, pulsar } = useInstancia("TooltipTrigger")
  const guardarNodo = React.useMemo(
    () => juntarRefs<HTMLButtonElement>([ref, (nodo) => anotar({ nodo })]),
    [ref, anotar],
  )

  const eventos = {
    onPointerEnter: (event: React.PointerEvent<HTMLButtonElement>) => {
      onPointerEnter?.(event)
      anotar({ punteroEncima: event.pointerType })
      // Real: el retardo se decide al entrar (¿hay otro tooltip visible?).
      if (radix) refrescar()
      else pedir()
    },
    onPointerLeave: (event: React.PointerEvent<HTMLButtonElement>) => {
      onPointerLeave?.(event)
      anotar({ punteroEncima: null })
    },
    onPointerDown: (event: React.PointerEvent<HTMLButtonElement>) => {
      onPointerDown?.(event)
      anotar({ focoPorPuntero: true })
      if (!radix) pulsar()
    },
    onFocus: (event: React.FocusEvent<HTMLButtonElement>) => {
      onFocus?.(event)
      anotar({ conFoco: true })
      // Radix no abre si el foco viene del puntero; este viene de un clic.
      if (focoDevuelto()) event.preventDefault()
      if (!radix) pedir()
    },
    onBlur: (event: React.FocusEvent<HTMLButtonElement>) => {
      onBlur?.(event)
      anotar({ conFoco: false, focoPorPuntero: false })
    },
  }

  if (radix) {
    return <radix.Disparador ref={guardarNodo} asChild={asChild} {...props} {...eventos} />
  }
  const Comp = asChild ? Slot : "button"
  return <Comp ref={guardarNodo} data-state="closed" {...props} {...eventos} />
}

function TooltipContent(props: React.ComponentProps<typeof TooltipPrimitive.Content>) {
  const { radix } = useInstancia("TooltipContent")
  // Sin Radix el tooltip está cerrado, y cerrado Radix tampoco pinta contenido.
  return radix ? <radix.Contenido {...props} /> : null
}

export { Tooltip, TooltipTrigger, TooltipContent, TooltipProvider }
