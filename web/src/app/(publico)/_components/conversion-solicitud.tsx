"use client";

import { useEffect } from "react";
import { track } from "@vercel/analytics";

/** Registra la conversión solo después de que la API haya persistido el lead. */
export function ConversionSolicitud() {
  useEffect(() => {
    track("solicitud_acceso_registrada");
  }, []);

  return null;
}
