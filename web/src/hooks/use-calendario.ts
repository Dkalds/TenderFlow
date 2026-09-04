"use client";

/**
 * Enlace de suscripción al calendario de compromisos.
 *
 * El endpoint `.ics` existía desde hacía meses y era inservible para los tres
 * clientes que importan: Google, Apple y Outlook no envían cabeceras
 * personalizadas al suscribirse a una URL, y aquel exigía `X-API-Key`. Además
 * se alimentaba de la watchlist y no de los pursuits, que son los que tienen
 * fecha de presentación de verdad. Ningún componente lo enlazaba.
 *
 * Este hook pide la ruta ya firmada; el origen lo pone el cliente, que es el
 * mismo host que proxya `/api` hacia la API.
 */
import { useQuery } from "@tanstack/react-query";
import { fetchWithAuth } from "@/lib/api-client";
import type { CalendarioEnlace } from "@/lib/api-types";
import { calendarioKeys } from "@/lib/query-keys";

export function useCalendarioEnlace() {
  return useQuery({
    queryKey: calendarioKeys.enlace,
    queryFn: () => fetchWithAuth<CalendarioEnlace>("/api/v1/exports/calendario/enlace"),
    // La firma no cambia entre renders y el recuento de eventos se mueve con
    // la pasada de ingesta: no hay nada que revalidar al enfocar la ventana.
    staleTime: 5 * 60 * 1000,
  });
}
