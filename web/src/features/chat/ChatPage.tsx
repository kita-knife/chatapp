import { ChatInput, PROVIDER_ORDER } from '@/components/ChatInput';
import { ChatTurnView } from '@/components/ChatTurn';
import { useChat } from '@/hooks/useChat';
import { useParams } from 'react-router-dom';
import { useEffect, useMemo } from 'react';

export function ChatPage() {
  const chat = useChat();
  const { sessionId } = useParams();

  useEffect(() => {
    if (sessionId && sessionId !== chat.currentSessionId) {
      chat.selectSession(sessionId);
    }
  }, [sessionId]); // eslint-disable-line react-hooks/exhaustive-deps

  // Providers that have at least one model configured — used to enable
  // entries in the provider dropdown.
  const availableProviders = useMemo(() => {
    const set = new Set(chat.models.map((m) => m.provider));
    return PROVIDER_ORDER.filter((p) => set.has(p));
  }, [chat.models]);

  return (
    <div className="chat-page">
      <div className="messages">
        {chat.turns.length === 0 ? (
          <div className="empty">
            <h1>Hello from ChatApp-PG</h1>
            <p>Start a new chat and send a message. The response will stream in real time.</p>
          </div>
        ) : (
          chat.turns.map((t) => <ChatTurnView key={t.id} turn={t} />)
        )}
      </div>
      <ChatInput
        input={chat.input}
        setInput={chat.setInput}
        onSend={chat.send}
        onStop={chat.stop}
        streaming={chat.streaming}
        provider={chat.provider}
        setProvider={chat.setProvider}
        model={chat.model}
        setModel={chat.setModel}
        modelsForProvider={chat.modelsForProvider}
        availableProviders={availableProviders}
        mode={chat.mode}
        setMode={chat.setMode}
        language={chat.uiLanguage}
        setLanguage={chat.setLanguage}
        project={chat.project}
        setProject={chat.setProject}
        projects={chat.projects}
        checking={chat.checkingConn}
      />
    </div>
  );
}
