import { ChatInput } from './components/ChatInput';
import { ChatMessageView } from './components/ChatMessage';
import { SessionList } from './components/SessionList';
import { useChat } from './hooks/useChat';
import './styles/app.css';

export default function App() {
  const chat = useChat();

  return (
    <div className="app">
      <SessionList
        sessions={chat.sessions}
        currentSessionId={chat.currentSessionId}
        health={chat.health}
        onSelect={chat.selectSession}
        onDelete={chat.removeSession}
      />
      <main className="main">
        <div className="main-header">
          <div className="model-tag">
            {chat.model || 'no model'}
          </div>
          {chat.error && <div className="error-banner">{chat.error}</div>}
        </div>
        <div className="messages">
          {chat.messages.length === 0 ? (
            <div className="empty">
              <h1>Hello from ChatApp-PG</h1>
              <p>Start a new chat and send a message. The response will stream in real time.</p>
            </div>
          ) : (
            chat.messages.map((m) => <ChatMessageView key={m.id} message={m} />)
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
          onNewSession={chat.newSession}
        />
      </main>
    </div>
  );
}
