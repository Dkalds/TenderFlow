"use client";

import * as React from "react";

export interface ValorDiferido<T> {
  /** Lo que muestra el campo: lo tecleado, se haya aplicado o no. */
  valor: T;
  /** Cambio de tecla: se aplica fuera cuando el valor lleva `retrasoMs` quieto. */
  cambiar: (valor: T) => void;
  /** Enter, envío o sugerencia elegida: se aplica ya, sin esperar. */
  aplicarYa: (valor: T) => void;
}

/**
 * Campo editable cuyo valor vive fuera (la URL, un store) y se escribe allí con
 * retraso.
 *
 * Existe por la búsqueda del ámbito: escribía en la URL en cada tecla, y cada
 * escritura cambia la clave de todas las consultas con filtros —en Resumen, ~7
 * agregados sobre el histórico entero por letra— y apila una entrada en el
 * historial de deshacer. Con esto la URL recibe el valor cuando se deja de
 * teclear, o en el acto si se pulsa Enter.
 *
 * El valor externo manda: si cambia desde fuera (limpiar el ámbito, deshacer,
 * un enlace), el campo se pone a su altura y lo pendiente se descarta. Para
 * saber qué cambio viene de fuera se recuerda el último valor que este campo
 * envió: la URL puede actualizarse un render más tarde que la tecla siguiente,
 * y sin esa memoria el eco de «sa» borraría la «p» recién tecleada de «sap».
 *
 * `aplicar` puede cambiar de identidad entre renders sin reiniciar la espera.
 */
export function useValorDiferido<T>(externo: T, aplicar: (valor: T) => void, retrasoMs: number): ValorDiferido<T> {
  const [valor, setValor] = React.useState(externo);
  const [enviado, setEnviado] = React.useState(externo);

  // Cambio externo: ajuste durante el render, el patrón que React documenta
  // para derivar estado de una prop, así el campo no pinta un valor viejo para
  // corregirlo en el render siguiente.
  const [externoPrevio, setExternoPrevio] = React.useState(externo);
  if (!Object.is(externo, externoPrevio)) {
    setExternoPrevio(externo);
    if (!Object.is(externo, enviado)) {
      setValor(externo);
      setEnviado(externo);
    }
  }

  const alVencer = React.useEffectEvent((pendiente: T) => {
    setEnviado(pendiente);
    aplicar(pendiente);
  });

  React.useEffect(() => {
    if (Object.is(valor, enviado)) return;
    const temporizador = setTimeout(() => alVencer(valor), retrasoMs);
    return () => clearTimeout(temporizador);
  }, [valor, enviado, retrasoMs]);

  const aplicarYa = (inmediato: T) => {
    setValor(inmediato);
    setEnviado(inmediato);
    if (!Object.is(inmediato, externo)) aplicar(inmediato);
  };

  return { valor, cambiar: setValor, aplicarYa };
}
