"use client";

import { useQuery } from "@tanstack/react-query";
import {
  Card,
  CardContent,
  CardHeader,
  CardTitle,
  CardDescription,
} from "@/components/ui/card";
import { Button } from "@/components/ui/button";
import { Badge } from "@/components/ui/badge";
import { Separator } from "@/components/ui/separator";
import { Skeleton } from "@/components/ui/skeleton";
import { Settings, AlertTriangle, Users, Key, RotateCcw, Plus } from "lucide-react";

interface QualityData {
  dlq_count?: number;
  [key: string]: unknown;
}

const MOCK_USERS = [
  { email: "admin@empresa.com", role: "admin", last_login: "2025-05-28T10:30:00Z" },
  { email: "analista@empresa.com", role: "viewer", last_login: "2025-05-27T14:15:00Z" },
  { email: "operador@empresa.com", role: "editor", last_login: "2025-05-25T09:00:00Z" },
];

const MOCK_API_KEYS = [
  { key_prefix: "sk-prod-****abcd", created: "2025-01-15", last_used: "2025-05-28" },
  { key_prefix: "sk-dev-****ef12", created: "2025-03-01", last_used: "2025-05-20" },
];

function showPlaceholderAlert() {
  alert("Funcionalidad en desarrollo");
}

export default function AdministracionPage() {
  const { data, isLoading } = useQuery<QualityData>({
    queryKey: ["analytics-quality-admin"],
    queryFn: async () => {
      const res = await fetch("/api/v1/analytics/quality", { credentials: "include" });
      if (!res.ok) throw new Error(`Error ${res.status}`);
      return res.json();
    },
  });

  return (
    <div className="space-y-6">
      <div>
        <h1 className="text-3xl font-bold tracking-tight">Administracion</h1>
        <p className="text-muted-foreground">
          Gestion de DLQ, usuarios y claves API.
        </p>
      </div>

      <Card className="border-yellow-500 bg-yellow-50/50 dark:bg-yellow-950/20">
        <CardContent className="pt-4 flex items-center gap-2 text-sm">
          <AlertTriangle className="h-4 w-4 text-yellow-600 shrink-0" />
          <span>Solo accesible para administradores</span>
        </CardContent>
      </Card>

      {/* DLQ Management */}
      <Card>
        <CardHeader>
          <CardTitle className="flex items-center gap-2">
            <RotateCcw className="h-5 w-5" />
            Gestion de DLQ
          </CardTitle>
          <CardDescription>
            Dead Letter Queue — registros que fallaron durante el procesamiento
          </CardDescription>
        </CardHeader>
        <CardContent className="flex items-center justify-between">
          <div>
            {isLoading ? (
              <Skeleton className="h-8 w-16" />
            ) : (
              <>
                <p className="text-2xl font-bold">{data?.dlq_count ?? 0}</p>
                <p className="text-sm text-muted-foreground">
                  registros en DLQ
                </p>
              </>
            )}
          </div>
          <Button variant="outline" onClick={showPlaceholderAlert}>
            <RotateCcw className="mr-2 h-4 w-4" />
            Reprocesar DLQ
          </Button>
        </CardContent>
      </Card>

      <Separator />

      {/* Users */}
      <Card>
        <CardHeader>
          <CardTitle className="flex items-center gap-2">
            <Users className="h-5 w-5" />
            Usuarios
          </CardTitle>
          <CardDescription>Gestion de usuarios y permisos</CardDescription>
        </CardHeader>
        <CardContent>
          <div className="overflow-x-auto">
            <table className="w-full text-sm">
              <thead>
                <tr className="border-b">
                  <th className="text-left py-2 pr-4 font-medium text-muted-foreground">Email</th>
                  <th className="text-left py-2 pr-4 font-medium text-muted-foreground">Rol</th>
                  <th className="text-left py-2 pr-4 font-medium text-muted-foreground">Ultimo login</th>
                  <th className="text-right py-2 font-medium text-muted-foreground">Acciones</th>
                </tr>
              </thead>
              <tbody>
                {MOCK_USERS.map((user) => (
                  <tr key={user.email} className="border-b last:border-0">
                    <td className="py-3 pr-4">{user.email}</td>
                    <td className="py-3 pr-4">
                      <Badge variant={user.role === "admin" ? "default" : "secondary"}>
                        {user.role}
                      </Badge>
                    </td>
                    <td className="py-3 pr-4 text-muted-foreground">
                      {new Date(user.last_login).toLocaleDateString("es-ES")}
                    </td>
                    <td className="py-3 text-right">
                      <Button variant="ghost" size="sm" onClick={showPlaceholderAlert}>
                        Editar
                      </Button>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </CardContent>
      </Card>

      {/* API Keys */}
      <Card>
        <CardHeader className="flex flex-row items-center justify-between">
          <div>
            <CardTitle className="flex items-center gap-2">
              <Key className="h-5 w-5" />
              API Keys
            </CardTitle>
            <CardDescription>Claves de acceso a la API</CardDescription>
          </div>
          <Button variant="outline" size="sm" onClick={showPlaceholderAlert}>
            <Plus className="mr-2 h-4 w-4" />
            Generar nueva clave
          </Button>
        </CardHeader>
        <CardContent>
          <div className="overflow-x-auto">
            <table className="w-full text-sm">
              <thead>
                <tr className="border-b">
                  <th className="text-left py-2 pr-4 font-medium text-muted-foreground">Clave</th>
                  <th className="text-left py-2 pr-4 font-medium text-muted-foreground">Creada</th>
                  <th className="text-left py-2 pr-4 font-medium text-muted-foreground">Ultimo uso</th>
                  <th className="text-right py-2 font-medium text-muted-foreground">Acciones</th>
                </tr>
              </thead>
              <tbody>
                {MOCK_API_KEYS.map((k) => (
                  <tr key={k.key_prefix} className="border-b last:border-0">
                    <td className="py-3 pr-4 font-mono text-xs">{k.key_prefix}</td>
                    <td className="py-3 pr-4 text-muted-foreground">{k.created}</td>
                    <td className="py-3 pr-4 text-muted-foreground">{k.last_used}</td>
                    <td className="py-3 text-right">
                      <Button
                        variant="ghost"
                        size="sm"
                        className="text-destructive"
                        onClick={showPlaceholderAlert}
                      >
                        Revocar
                      </Button>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </CardContent>
      </Card>
    </div>
  );
}
