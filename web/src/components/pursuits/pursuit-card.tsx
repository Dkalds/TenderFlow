import Link from "next/link";
import { ArrowRight, CalendarClock, UserRound } from "lucide-react";
import { Card, CardContent } from "@/components/ui/card";
import { PursuitCommentsButton } from "@/components/pursuits/pursuit-comments";
import { PursuitDecisionBadge, PursuitStatusBadge, daysUntil, formatDate } from "@/components/pursuits/pursuit-presenters";
import type { Pursuit } from "@/hooks/use-pursuits";

export function PursuitCard({ pursuit }: { pursuit: Pursuit }) {
  const deadline = daysUntil(pursuit.tender_deadline);
  return (
    <Card className="group relative overflow-hidden hover:-translate-y-0.5">
      <CardContent className="p-0">
        <div className="border-l-4 border-l-primary p-4">
          <div className="flex items-start justify-between gap-3">
            <div className="min-w-0">
              <Link href={`/oportunidades/${pursuit.id}`} className="font-semibold leading-snug hover:text-primary hover:underline">
                {pursuit.tender_title ?? `Licitación ${pursuit.licitacion_id}`}
              </Link>
              <p className="mt-1 truncate text-xs text-muted-foreground">Referencia {pursuit.licitacion_id}</p>
            </div>
            <PursuitStatusBadge status={pursuit.status} />
          </div>

          <div className="mt-4 flex flex-wrap items-center gap-x-4 gap-y-2 text-xs text-muted-foreground">
            <span className="inline-flex items-center gap-1.5"><CalendarClock className="h-3.5 w-3.5" />{deadline ?? formatDate(pursuit.tender_deadline)}</span>
            <span className="inline-flex items-center gap-1.5"><UserRound className="h-3.5 w-3.5" />{pursuit.responsible_name ?? "Sin responsable"}</span>
          </div>

          <div className="mt-4 flex items-center gap-3 border-t border-border/60 pt-3">
            <PursuitDecisionBadge decision={pursuit.decision} />
            <div className="flex-1" />
            {/* El chat del equipo se abre aquí mismo, en un panel lateral:
                comentar una oportunidad no obliga a salir del tablero. */}
            <PursuitCommentsButton pursuit={pursuit} />
            <Link href={`/oportunidades/${pursuit.id}`} className="inline-flex items-center gap-1 text-xs font-semibold text-primary hover:underline">
              Abrir ficha <ArrowRight className="h-3.5 w-3.5" />
            </Link>
          </div>
        </div>
      </CardContent>
    </Card>
  );
}
