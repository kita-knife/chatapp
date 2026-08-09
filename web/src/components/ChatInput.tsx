import type { ModelInfo } from '../api/client';

export type AgentMode = 'simple' | 'knowledge' | 'think';

export const AGENT_MODES: { value: AgentMode; label: string; description: string }[] = [
  { value: 'simple', label: 'Simple', description: 'straightforward chat' },
  { value: 'knowledge', label: 'Knowledge', description: 'RAG-augmented answers' },
  { value: 'think', label: 'Think', description: 'deeper reasoning' },
];

interface Props {
  input: string;
  setInput: (v: string) => void;
  onSend: () => void;
  onStop: () => void;
  streaming: boolean;
  model: string;
  setModel: (v: string) => void;
  models: ModelInfo[];
  mode: AgentMode;
  setMode: (v: AgentMode) => void;
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
  mode,
  setMode,
  checking,
}: Props) {
  return (
    <div className="chat-input">
      <div className="chat-input-row">
        <select
          className="select mode-select"
          value={mode}
          onChange={(e) => setMode(e.target.value as AgentMode)}
          disabled={streaming}
          title="Agent mode"
        >
          {AGENT_MODES.map((m) => (
            <option key={m.value} value={m.value}>
              {m.label}
            </option>
          ))}
        </select>
        <select
          className="select"
          value={model}
          onChange={(e) => setModel(e.target.value)}
          disabled={streaming}
          title="Model"
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