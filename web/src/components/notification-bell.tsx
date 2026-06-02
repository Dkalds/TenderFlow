"use client";

import * as React from "react";
import { Bell } from "lucide-react";
import {
  DropdownMenu,
  DropdownMenuTrigger,
  DropdownMenuContent,
} from "@/components/ui/dropdown-menu";
import { reportError } from "@/lib/report-error";

interface NotificationBellProps {
  className?: string;
}

interface Notification {
  id: string;
  message: string;
  timestamp: Date;
}

const MAX_RECONNECT_DELAY = 60_000;
const INITIAL_RECONNECT_DELAY = 1_000;

export function NotificationBell({ className }: NotificationBellProps) {
  const [unreadCount, setUnreadCount] = React.useState(0);
  const [notifications, setNotifications] = React.useState<Notification[]>([]);
  const [connected, setConnected] = React.useState(false);

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
            const data = JSON.parse(event.data);
            const notif: Notification = {
              id: crypto.randomUUID(),
              message: data.message ?? `${data.count ?? 1} nuevas licitaciones`,
              timestamp: new Date(),
            };
            setNotifications((prev) => [notif, ...prev].slice(0, 5));
            setUnreadCount((prev) => prev + 1);
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
  }, []);

  return (
    <DropdownMenu>
      <DropdownMenuTrigger
        className="relative rounded-md p-2 hover:bg-accent transition-colors"
        aria-label="Notificaciones"
        onClick={() => setUnreadCount(0)}
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
        {notifications.length === 0 ? (
          <p className="px-2 py-4 text-center text-sm text-muted-foreground">
            Sin notificaciones
          </p>
        ) : (
          <ul className="space-y-1">
            {notifications.map((n) => (
              <li
                key={n.id}
                className="rounded-sm px-2 py-1.5 text-sm hover:bg-accent transition-colors"
              >
                <p>{n.message}</p>
                <p className="text-xs text-muted-foreground">
                  {n.timestamp.toLocaleTimeString("es-ES")}
                </p>
              </li>
            ))}
          </ul>
        )}
        {!connected && (
          <p className="mt-2 px-2 text-xs text-muted-foreground">Sin conexión en vivo</p>
        )}
      </DropdownMenuContent>
    </DropdownMenu>
  );
}
