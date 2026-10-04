/**
 * La red de partículas del fondo de `/login`, sin React: recibe un canvas y su
 * contexto 2D y devuelve con qué arrancarla, pararla y soltarla. Quién decide
 * si se mueve —la pausa, `prefers-reduced-motion`— es
 * `_components/fondo-particulas.tsx`.
 *
 * Es la misma red que tuvo la puerta hasta el 2026-09-26: puntos del color de
 * la marca que derivan, orbitan o siguen una corriente, unidos por líneas finas
 * cuando se acercan. Lo que aquella versión no hacía:
 *
 * - **La velocidad no depende de la pantalla**: avanzaba un paso fijo por
 *   fotograma, así que a 120 Hz iba el doble de rápido que a 60. Ahora el paso
 *   se mide en tiempo.
 * - **Cambiar el tamaño no la reinicia**: las partículas se reparten en el
 *   tamaño nuevo en vez de nacer otra vez (en móvil, cada vez que se esconde la
 *   barra del navegador).
 * - **Sigue al tema**: el color es el `color` del propio canvas y se vuelve a
 *   leer cuando `<html>` cambia de clase.
 *
 * Como antes, con la pestaña oculta el bucle se detiene.
 */

type Patron = "deriva" | "orbita" | "corriente";

interface Particula {
  x: number;
  y: number;
  /** Centro de la órbita, que también deriva. */
  anclaX: number;
  anclaY: number;
  vx: number;
  vy: number;
  r: number;
  alfa: number;
  fase: number;
  brio: number;
  radio: number;
  patron: Patron;
}

export interface Red {
  /** Arranca o detiene el bucle. Detenida, conserva el último fotograma. */
  mover(enMarcha: boolean): void;
  destruir(): void;
}

const PATRONES: readonly Patron[] = ["deriva", "orbita", "corriente"];
/** Una partícula por cada tantos px², entre un mínimo y un máximo. */
const AREA_POR_PARTICULA = 14_000;
const MIN_PARTICULAS = 36;
const MAX_PARTICULAS = 180;
/** Distancia, en px, por debajo de la cual dos partículas se unen. */
const ALCANCE_ENLACE = 110;
const OPACIDAD_ENLACE = 0.12;
/** Los pasos están calibrados a 60 fotogramas por segundo. */
const FOTOGRAMA_MS = 1000 / 60;
/** Tope del salto de tiempo: tras un parón, la red no da un brinco. */
const SALTO_MAX_MS = 50;

const azar = (min: number, max: number) => min + Math.random() * (max - min);

function nacer(ancho: number, alto: number): Particula {
  const x = Math.random() * ancho;
  const y = Math.random() * alto;
  return {
    x,
    y,
    anclaX: x,
    anclaY: y,
    vx: azar(-0.35, 0.35),
    vy: azar(-0.35, 0.35),
    r: azar(0.6, 2.2),
    alfa: azar(0.25, 0.7),
    fase: azar(0, Math.PI * 2),
    brio: azar(0.4, 1),
    radio: azar(16, 70),
    patron: PATRONES[Math.floor(Math.random() * PATRONES.length)],
  };
}

/** Lo que sale por un borde entra por el contrario, con `margen` px de holgura. */
function envolver(valor: number, limite: number, margen: number): number {
  if (valor < -margen) return limite + margen;
  if (valor > limite + margen) return -margen;
  return valor;
}

/** Campo de direcciones barato y suave: da trayectorias orgánicas. */
function rumbo(x: number, y: number, tiempo: number): number {
  return (Math.sin(x * 0.0021 + tiempo) + Math.cos(y * 0.0019 - tiempo * 0.8)) * Math.PI;
}

export function crearRed(lienzo: HTMLCanvasElement, ctx: CanvasRenderingContext2D): Red {
  const particulas: Particula[] = [];
  let ancho = 0;
  let alto = 0;
  let color = "";
  let enMarcha = false;
  let raf = 0;
  let t = 0;
  /** Hora del fotograma anterior; `null` en el primero tras arrancar. */
  let anterior: number | null = null;

  function leerColor() {
    color = getComputedStyle(lienzo).color;
  }

  function medir() {
    const anchoNuevo = lienzo.clientWidth;
    const altoNuevo = lienzo.clientHeight;
    if (anchoNuevo === 0 || altoNuevo === 0) return;
    if (anchoNuevo === ancho && altoNuevo === alto) return;

    const dpr = Math.min(window.devicePixelRatio || 1, 2);
    lienzo.width = Math.floor(anchoNuevo * dpr);
    lienzo.height = Math.floor(altoNuevo * dpr);
    ctx.setTransform(dpr, 0, 0, dpr, 0, 0);

    if (ancho > 0 && alto > 0) {
      const fx = anchoNuevo / ancho;
      const fy = altoNuevo / alto;
      for (const p of particulas) {
        p.x *= fx;
        p.y *= fy;
        p.anclaX *= fx;
        p.anclaY *= fy;
      }
    }
    ancho = anchoNuevo;
    alto = altoNuevo;

    const cuantas = Math.min(MAX_PARTICULAS, Math.max(MIN_PARTICULAS, Math.round((ancho * alto) / AREA_POR_PARTICULA)));
    while (particulas.length < cuantas) particulas.push(nacer(ancho, alto));
    particulas.length = cuantas;
  }

  function avanzar(p: Particula, dt: number) {
    switch (p.patron) {
      case "orbita": {
        p.anclaX = envolver(p.anclaX + p.vx * 0.25 * dt, ancho, 80);
        p.anclaY = envolver(p.anclaY + p.vy * 0.25 * dt, alto, 80);
        const angulo = p.fase + t * p.brio * 0.6;
        p.x = p.anclaX + Math.cos(angulo) * p.radio;
        p.y = p.anclaY + Math.sin(angulo) * p.radio;
        break;
      }
      case "corriente": {
        const a = rumbo(p.x, p.y, t * 0.2);
        p.x = envolver(p.x + Math.cos(a) * p.brio * 0.5 * dt, ancho, 10);
        p.y = envolver(p.y + Math.sin(a) * p.brio * 0.5 * dt, alto, 10);
        break;
      }
      default: {
        p.x = envolver(p.x + p.vx * p.brio * dt, ancho, 10);
        p.y = envolver(p.y + p.vy * p.brio * dt, alto, 10);
      }
    }
  }

  function pintar() {
    ctx.clearRect(0, 0, ancho, alto);
    ctx.fillStyle = color;
    ctx.strokeStyle = color;
    ctx.lineWidth = 1;

    const alcance2 = ALCANCE_ENLACE * ALCANCE_ENLACE;
    for (let i = 0; i < particulas.length; i++) {
      const a = particulas[i];
      for (let j = i + 1; j < particulas.length; j++) {
        const b = particulas[j];
        const dx = a.x - b.x;
        const dy = a.y - b.y;
        const d2 = dx * dx + dy * dy;
        if (d2 >= alcance2) continue;
        ctx.globalAlpha = (1 - d2 / alcance2) * OPACIDAD_ENLACE;
        ctx.beginPath();
        ctx.moveTo(a.x, a.y);
        ctx.lineTo(b.x, b.y);
        ctx.stroke();
      }
    }

    for (const p of particulas) {
      ctx.globalAlpha = p.alfa;
      ctx.beginPath();
      ctx.arc(p.x, p.y, p.r, 0, Math.PI * 2);
      ctx.fill();
    }
    ctx.globalAlpha = 1;
  }

  function fotograma(ahora: number) {
    const dt = anterior === null ? 1 : Math.min(ahora - anterior, SALTO_MAX_MS) / FOTOGRAMA_MS;
    anterior = ahora;
    t += 0.005 * dt;
    for (const p of particulas) avanzar(p, dt);
    pintar();
    raf = requestAnimationFrame(fotograma);
  }

  /** Pone el bucle de acuerdo con lo pedido y con que la pestaña se vea. */
  function ajustarBucle() {
    cancelAnimationFrame(raf);
    raf = 0;
    anterior = null;
    if (enMarcha && !document.hidden) raf = requestAnimationFrame(fotograma);
  }

  /** Con el bucle parado nadie repinta: lo que cambie hay que pintarlo aquí. */
  function repintarSiParada() {
    if (raf === 0) pintar();
  }

  const alCambiarTamano = new ResizeObserver(() => {
    medir();
    repintarSiParada();
  });
  alCambiarTamano.observe(lienzo);

  // next-themes escribe `.dark` en `<html>`; el login no tiene conmutador, pero
  // con el tema en «sistema» la clase cambia sola cuando cambia el del equipo.
  const alCambiarTema = new MutationObserver(() => {
    leerColor();
    repintarSiParada();
  });
  alCambiarTema.observe(document.documentElement, { attributes: true, attributeFilter: ["class"] });

  document.addEventListener("visibilitychange", ajustarBucle);

  leerColor();
  medir();
  pintar();

  return {
    mover(valor) {
      enMarcha = valor;
      ajustarBucle();
    },
    destruir() {
      cancelAnimationFrame(raf);
      alCambiarTamano.disconnect();
      alCambiarTema.disconnect();
      document.removeEventListener("visibilitychange", ajustarBucle);
    },
  };
}
