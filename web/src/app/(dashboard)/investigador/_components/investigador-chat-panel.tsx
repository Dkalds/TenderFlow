"use client";

/**
 * Hilo de la conversación del modo «Preguntar».
 *
 * Convive con la lista de resultados en vez de sustituirla: antes se excluían y
 * preguntar por un resultado hacía perder la lista desde la que se preguntaba.
 */

import { MessageSquare } from "lucide-react";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { ChatThread } from "@/components/chat-thread";
import type { UseChatResult } from "@/hooks/use-ask";

export function InvestigadorChatPanel({ chat }: { chat: UseChatResult }) {
  return (
    <Card>
      <CardHeader className="flex flex-row items-center justify-between space-y-0">
        <CardTitle className="flex items-center gap-2 text-base">
          <MessageSquare className="h-4 w-4" />
          Conversación
        </CardTitle>
        {chat.messages.length > 0 && !chat.loading && (
          <Button variant="ghost" size="sm" onClick={chat.reset}>
            Nueva conversación
          </Button>
        )}
      </CardHeader>
      <CardContent>
        <ChatThread
          messages={chat.messages}
          streaming={chat.streaming}
          loading={chat.loading}
          error={chat.error}
        />
      </CardContent>
    </Card>
  );
}
