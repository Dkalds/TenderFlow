"use client";

/**
 * Hilo de la conversación del modo «Preguntar».
 *
 * Convive con la lista de resultados en vez de sustituirla: antes se excluían y
 * preguntar por un resultado hacía perder la lista desde la que se preguntaba.
 */

import { Panel, PanelTitle } from "@/components/console/panel";
import { Button } from "@/components/ui/button";
import { ChatThread } from "@/components/chat-thread";
import type { UseChatResult } from "@/hooks/use-ask";

export function InvestigadorChatPanel({ chat }: { chat: UseChatResult }) {
  return (
    <Panel>
      <PanelTitle
        as="h2"
        title="Conversación"
        actions={
          chat.messages.length > 0 && !chat.loading ? (
            <Button variant="ghost" size="sm" onClick={chat.reset}>
              Nueva conversación
            </Button>
          ) : undefined
        }
      />
      <ChatThread
        messages={chat.messages}
        streaming={chat.streaming}
        loading={chat.loading}
        error={chat.error}
      />
    </Panel>
  );
}
