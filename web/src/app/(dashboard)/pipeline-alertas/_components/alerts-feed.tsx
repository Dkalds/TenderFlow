"use client";

import Link from "next/link";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import {
  Card,
  CardContent,
  CardHeader,
  CardTitle,
  CardDescription,
} from "@/components/ui/card";
import { Skeleton } from "@/components/ui/skeleton";
import { Button } from "@/components/ui/button";
import { BellRing, CheckCheck } from "lucide-react";
import { fetchWithAuth, apiMutate } from "@/lib/api-client";
import { reportError } from "@/lib/report-error";
import { formatDate } from "@/lib/utils";
import type { NotificationsResult } from "@/lib/api-types";

/** Misma queryKey que NotificationBell — marcar como leída aquí actualiza
 * también el badge de la campana (invalidación compartida). */
const NOTIFICATIONS_KEY = ["notifications"] as const;

export function AlertsFeed() {
  const qc = useQueryClient();
  const { data, isLoading } = useQuery<NotificationsResult>({
    queryKey: NOTIFICATIONS_KEY,
    queryFn: () => fetchWithAuth<NotificationsResult>("/api/v1/notifications"),
    staleTime: 60 * 1000,
  });

  const alerts = data?.alerts ?? [];
  const unread = alerts.filter((a) => !a.read);

  const markRead = async () => {
    if (unread.length === 0) return;
    try {
      await apiMutate("POST", "/api/v1/notifications/alerts/read", {
        ids: unread.map((a) => a.id),
      });
      qc.invalidateQueries({ queryKey: NOTIFICATIONS_KEY });
    } catch (err) {
      reportError("AlertsFeed.markRead", err);
    }
  };

  return (
    <Card id="ultimas-alertas">
      <CardHeader>
        <div className="flex flex-wrap items-center justify-between gap-2">
          <div>
            <CardTitle className="flex items-center gap-2 text-base">
              <BellRing className="h-4 w-4" />
              Últimas alertas
            </CardTitle>
            <CardDescription>
              Coincidencias de tus reglas suscribibles, más recientes primero.
            </CardDescription>
          </div>
          {unread.length > 0 && (
            <Button variant="outline" size="sm" onClick={markRead}>
              <CheckCheck className="mr-2 h-4 w-4" />
              Marcar leídas ({unread.length})
            </Button>
          )}
        </div>
      </CardHeader>
      <CardContent>
        {isLoading ? (
          <div className="space-y-2">
            {[1, 2, 3].map((i) => (
              <Skeleton key={i} className="h-10 w-full" />
            ))}
          </div>
        ) : alerts.length === 0 ? (
          <p className="text-sm text-muted-foreground">
            Sin alertas todavía. Crea una regla arriba para que el sistema te
            avise cuando entren licitaciones que cumplan tus criterios.
          </p>
        ) : (
          <ul className="space-y-1">
            {alerts.slice(0, 8).map((a) => {
              const content = (
                <>
                  {!a.read && (
                    <span
                      className="mt-1.5 h-1.5 w-1.5 shrink-0 rounded-full bg-primary"
                      aria-hidden="true"
                    />
                  )}
                  <span className="min-w-0 flex-1">
                    <span className="block truncate">{a.title ?? a.type}</span>
                    {a.created_at && (
                      <span className="block text-xs text-muted-foreground">
                        {formatDate(a.created_at)}
                      </span>
                    )}
                  </span>
                </>
              );
              return (
                <li key={a.id}>
                  {a.licitacion_id ? (
                    <Link
                      href={`/detalle?lic=${encodeURIComponent(a.licitacion_id)}`}
                      className="flex items-start gap-2 rounded-md px-2 py-1.5 text-sm transition-colors hover:bg-muted/50"
                    >
                      {content}
                    </Link>
                  ) : (
                    <div className="flex items-start gap-2 rounded-md px-2 py-1.5 text-sm">
                      {content}
                    </div>
                  )}
                </li>
              );
            })}
          </ul>
        )}
      </CardContent>
    </Card>
  );
}
