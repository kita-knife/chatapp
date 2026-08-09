import { ChatInput } from '@/components/ChatInput';
import { ChatTurnView } from '@/components/ChatTurn';
import { useChat } from '@/hooks/useChat';
import { useParams } from 'react-router-dom';
import { useEffect } from 'react';

export function ChatPage() {
  const chat = useChat();
  const { sessionId } = useParams();

  useEffect(() => {
    if (sessionId && sessionId !== chat.currentSessionId) {
      chat.selectSession(sessionId);
    }
  }, [sessionId]); // eslint-disable-line react-hooks/exhaustive-deps

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
        model={chat.model}
        setModel={chat.setModel}
        models={chat.models}
        mode={chat.mode}
        setMode={chat.setMode}
        checking={chat.checkingConn}
      />
    </div>
  );
}
