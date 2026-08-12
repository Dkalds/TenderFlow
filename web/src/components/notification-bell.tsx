"use client";

import * as React from "react";
import Link from "next/link";
import { Bell } from "lucide-react";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import {
  DropdownMenu,
  DropdownMenuTrigger,
  DropdownMenuContent,
} from "@/components/ui/dropdown-menu";
import { fetchWithAuth, apiMutate } from "@/lib/api-client";
import { reportError } from "@/lib/report-error";

interface NotificationBellProps {
  className?: string;
}

interface NotificationItem {
  id: string;
  titulo: string | null;
  importe: number | null;
  organo_contratacion: string | null;
  read: boolean;
}

interface AlertItem {
  id: number;
  created_at: string | null;
  type: string;
  title: string | null;
  body: string | null;
  licitacion_id: string | null;
  rule_id: number | null;
  read: boolean;
}

interface HoyCounters {
  calientes: number;
  vencen_48h: number;
  nuevas_24h: number;
  total_activas: number;
}

interface NotificationsResult {
  items: NotificationItem[];
  unread_count: number;
  alerts: AlertItem[];
  alerts_unread_count: number;
  hoy: HoyCounters;
}

/** Live item pushed via SSE (not yet persisted in the novedades feed). */
interface LiveItem {
  id: string;
  message: string;
}

const MAX_RECONNECT_DELAY = 60_000;
const INITIAL_RECONNECT_DELAY = 1_000;
const NOTIFICATIONS_KEY = ["notifications"] as const;

export function NotificationBell({ className: _className }: NotificationBellProps) {
  const queryClient = useQueryClient();
  const [liveItems, setLiveItems] = React.useState<LiveItem[]>([]);
  const [liveUnread, setLiveUnread] = React.useState(0);
  const [connected, setConnected] = React.useState(false);

  // Persistent notifications (novedades since last visit + "today" counters).
  const { data } = useQuery<NotificationsResult>({
    queryKey: NOTIFICATIONS_KEY,
    queryFn: () => fetchWithAuth<NotificationsResult>("/api/v1/notifications"),
    refetchInterval: 5 * 60_000,
    meta: { silent: true },
  });

  // Live push of brand-new licitaciones via SSE.
  React.useEffect(() => {
    let es: EventSource | null = null;
    let reconnectTimer: ReturnType<typeof setTimeout>;
    let reconnectDelay = INITIAL_RECONNECT_DELAY;

    function connect() {
      try {
        es = new EventSource("/api/v1/licitaciones/stream", { withCredentials: true });

        es.onopen = () => {
          setConnected(true);
          reconnectDelay = INITIAL_RECONNECT_DELAY;
        };

        es.addEventListener("licitaciones_nuevas", (event) => {
          try {
            const payload = JSON.parse(event.data);
            const item: LiveItem = {
              id: crypto.randomUUID(),
              message: payload.message ?? `${payload.count ?? 1} nuevas licitaciones`,
            };
            setLiveItems((prev) => [item, ...prev].slice(0, 5));
            setLiveUnread((prev) => prev + 1);
            // Refresh the persistent feed so new tenders surface in the list.
            queryClient.invalidateQueries({ queryKey: NOTIFICATIONS_KEY });
          } catch (parseError) {
            reportError("NotificationBell.parse", parseError);
          }
        });

        es.onerror = () => {
          setConnected(false);
          es?.close();
          reconnectTimer = setTimeout(() => {
            reconnectDelay = Math.min(reconnectDelay * 2, MAX_RECONNECT_DELAY);
            connect();
          }, reconnectDelay);
        };
      } catch (connError) {
        reportError("NotificationBell.connect", connError);
        setConnected(false);
        reconnectTimer = setTimeout(() => {
          reconnectDelay = Math.min(reconnectDelay * 2, MAX_RECONNECT_DELAY);
          connect();
        }, reconnectDelay);
      }
    }

    connect();
    return () => {
      es?.close();
      clearTimeout(reconnectTimer);
    };
  }, [queryClient]);

  const items = data?.items ?? [];
  const alerts = data?.alerts ?? [];
  const hoy = data?.hoy;
  const unreadCount = (data?.unread_count ?? 0) + (data?.alerts_unread_count ?? 0) + liveUnread;

  /** Mark unread novedades + alerts as read and clear the live badge. */
  const markAllRead = async () => {
    setLiveUnread(0);
    const unreadIds = items.filter((n) => !n.read).map((n) => n.id);
    const unreadAlertIds = alerts.filter((a) => !a.read).map((a) => a.id);
    try {
      if (unreadIds.length > 0) {
        await apiMutate("POST", "/api/v1/notifications/read", { ids: unreadIds });
      }
      if (unreadAlertIds.length > 0) {
        await apiMutate("POST", "/api/v1/notifications/alerts/read", { ids: unreadAlertIds });
      }
      queryClient.invalidateQueries({ queryKey: NOTIFICATIONS_KEY });
    } catch (err) {
      reportError("NotificationBell.markRead", err);
    }
  };

  return (
    <DropdownMenu>
      <DropdownMenuTrigger
        className="relative rounded-md p-2 hover:bg-accent transition-colors"
        aria-label={`Notificaciones${unreadCount > 0 ? ` (${unreadCount} sin leer)` : ""}`}
        onClick={markAllRead}
      >
        <Bell className="h-5 w-5" />
        {unreadCount > 0 && (
          <span className="absolute -top-0.5 -right-0.5 flex h-4 min-w-4 items-center justify-center rounded-full bg-destructive px-1 text-xs font-bold text-destructive-foreground">
            {unreadCount > 99 ? "99+" : unreadCount}
          </span>
        )}
      </DropdownMenuTrigger>
      <DropdownMenuContent align="end" className="w-80 p-2">
        <h4 className="mb-2 px-2 text-xs font-semibold text-muted-foreground">Notificaciones</h4>

        {hoy && (hoy.nuevas_24h > 0 || hoy.vencen_48h > 0 || hoy.calientes > 0) && (
          <div className="mb-2 grid grid-cols-3 gap-1 px-1">
            <HoyStat label="Nuevas 24h" value={hoy.nuevas_24h} />
            <HoyStat label="Vencen 48h" value={hoy.vencen_48h} accent />
            {/* Importe ≥ P75 y en plazo — no la banda "Caliente" del score. */}
            <HoyStat label="Grandes" value={hoy.calientes} />
          </div>
        )}

        {liveItems.length > 0 && (
          <ul className="mb-1 space-y-1">
            {liveItems.map((n) => (
              // Genuinely live data (pushed via SSE, prepended as it
              // arrives) — fade+slide instead of popping in with no
              // transition (find-animation-opportunities: "preventing a
              // jarring change"). Keyed by a fresh uuid per push, so this
              // only plays once per item, on its own mount.
              <li
                key={n.id}
                className="animate-in fade-in-0 slide-in-from-top-2 rounded-sm bg-primary/5 px-2 py-1.5 text-sm"
              >
                <p>{n.message}</p>
              </li>
            ))}
          </ul>
        )}

        {items.length === 0 && liveItems.length === 0 && alerts.length === 0 ? (
          <p className="px-2 py-4 text-center text-sm text-muted-foreground">
            Sin notificaciones
          </p>
        ) : (
          <>
            {alerts.length > 0 && (
              <>
                <h5 className="mb-1 mt-2 px-2 text-xs font-semibold text-muted-foreground">Alertas</h5>
                <ul className="mb-2 space-y-0.5">
                  {alerts.slice(0, 5).map((a) => (
                    <li key={a.id}>
                      {a.licitacion_id ? (
                        <Link
                          href={`/detalle?lic=${encodeURIComponent(a.licitacion_id)}`}
                          className="block rounded-sm px-2 py-1.5 text-sm hover:bg-accent transition-colors"
                        >
                          <span className="flex items-center gap-2">
                            {!a.read && (
                              <span className="h-1.5 w-1.5 shrink-0 rounded-full bg-primary" aria-hidden="true" />
                            )}
                            <span className="truncate">{a.title ?? a.type}</span>
                          </span>
                        </Link>
                      ) : (
                        <div className="rounded-sm px-2 py-1.5 text-sm">
                          <span className="flex items-center gap-2">
                            {!a.read && (
                              <span className="h-1.5 w-1.5 shrink-0 rounded-full bg-primary" aria-hidden="true" />
                            )}
                            <span className="truncate">{a.title ?? a.type}</span>
                          </span>
                        </div>
                      )}
                    </li>
                  ))}
                </ul>
              </>
            )}
            <ul className="space-y-0.5">
              {items.map((n) => (
                <li key={n.id}>
                  <Link
                    href={`/detalle?lic=${encodeURIComponent(n.id)}`}
                    className="block rounded-sm px-2 py-1.5 text-sm hover:bg-accent transition-colors"
                  >
                    <span className="flex items-center gap-2">
                      {!n.read && (
                        <span className="h-1.5 w-1.5 shrink-0 rounded-full bg-primary" aria-hidden="true" />
                      )}
                      <span className="truncate">{n.titulo ?? n.id}</span>
                    </span>
                    {n.organo_contratacion && (
                      <span className="block truncate pl-3.5 text-xs text-muted-foreground">
                        {n.organo_contratacion}
                      </span>
                    )}
                  </Link>
                </li>
              ))}
            </ul>
          </>
        )}

        {!connected && (
          <p className="mt-2 px-2 text-xs text-muted-foreground">Sin conexión en vivo</p>
        )}
      </DropdownMenuContent>
    </DropdownMenu>
  );
}

function HoyStat({ label, value, accent }: { label: string; value: number; accent?: boolean }) {
  return (
    <div className="rounded-md border border-border/60 bg-background/50 px-2 py-1.5 text-center">
      <div className={`text-sm font-semibold ${accent ? "text-destructive" : "text-foreground"}`}>
        {value}
      </div>
      <div className="text-[10px] leading-tight text-muted-foreground">{label}</div>
    </div>
  );
}
