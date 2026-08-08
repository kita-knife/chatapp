import type { ModelInfo } from '../api/client';

interface Props {
  input: string;
  setInput: (v: string) => void;
  onSend: () => void;
  onStop: () => void;
  streaming: boolean;
  model: string;
  setModel: (v: string) => void;
  models: ModelInfo[];
  onNewSession: () => void;
  checking?: boolean;
}

export function ChatInput({
  input,
  setInput,
  onSend,
  onStop,
  streaming,
  model,
  setModel,
  models,
  onNewSession,
  checking,
}: Props) {
  return (
    <div className="chat-input">
      <div className="chat-input-row">
        <button className="btn-secondary" onClick={onNewSession} disabled={streaming}>
          + New chat
        </button>
        <select
          className="select"
          value={model}
          onChange={(e) => setModel(e.target.value)}
          disabled={streaming}
        >
          {models.map((m) => (
            <option key={`${m.provider}:${m.model}`} value={m.model}>
              {m.provider} / {m.model}
            </option>
          ))}
        </select>
      </div>
      <div className="chat-input-row">
        <textarea
          className="textarea"
          rows={3}
          placeholder="Send a message..."
          value={input}
          onChange={(e) => setInput(e.target.value)}
          onKeyDown={(e) => {
            if (e.key === 'Enter' && (e.metaKey || e.ctrlKey)) {
              e.preventDefault();
              onSend();
            }
          }}
        />
        {streaming ? (
          <button className="btn-danger" onClick={onStop}>
            Stop
          </button>
        ) : (
          <button
            className="btn-primary"
            onClick={onSend}
            disabled={!input.trim() || checking}
          >
            {checking ? 'Checking…' : 'Send'}
          </button>
        )}
      </div>
    </div>
  );
}
