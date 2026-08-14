import type { ModelInfo, ProviderKey } from '../api/client';

export type AgentMode = 'simple' | 'knowledge' | 'think';
export type UiLanguage = 'zh' | 'en';

// Re-export ProviderKey so consumers (e.g. useChat) can use a single import.
export type { ProviderKey } from '../api/client';

// The PROVIDER_LABELS dict lives in client.ts but is small enough to be
// duplicated here for the dropdown. The order is the UI's fixed order
// and matches the order in client.ts.
export const PROVIDER_LABELS: Record<ProviderKey, string> = {
  openlike: 'openlike',
  openai: 'openai',
  openai_compat: 'openai-compat',
  anthropic: 'anthropic',
  anthropic_compat: 'anthropic-compat',
  ollama: 'ollama',
};
export const PROVIDER_ORDER: ProviderKey[] = [
  'openlike',
  'openai',
  'openai_compat',
  'anthropic',
  'anthropic_compat',
  'ollama',
];

export const AGENT_MODES: { value: AgentMode; label: string; description: string }[] = [
  { value: 'simple', label: 'Simple', description: 'straightforward chat' },
  { value: 'knowledge', label: 'Knowledge', description: 'RAG-augmented answers' },
  { value: 'think', label: 'Think', description: 'deeper reasoning' },
];

export const LANGUAGES: { value: UiLanguage; label: string }[] = [
  { value: 'zh', label: '中文' },
  { value: 'en', label: 'English' },
];

interface Props {
  input: string;
  setInput: (v: string) => void;
  onSend: () => void;
  onStop: () => void;
  streaming: boolean;
  provider: ProviderKey;
  setProvider: (v: ProviderKey) => void;
  model: string;
  setModel: (v: string) => void;
  modelsForProvider: ModelInfo[];
  // Set of providers that have at least one model configured (used to
  // enable/disable provider dropdown entries).
  availableProviders: ProviderKey[];
  mode: AgentMode;
  setMode: (v: AgentMode) => void;
  language: UiLanguage;
  setLanguage: (v: UiLanguage) => void;
  project: string;
  setProject: (v: string) => void;
  projects: string[];
  checking?: boolean;
}

export function ChatInput({
  input,
  setInput,
  onSend,
  onStop,
  streaming,
  provider,
  setProvider,
  model,
  setModel,
  modelsForProvider,
  availableProviders,
  mode,
  setMode,
  language,
  setLanguage,
  project,
  setProject,
  projects,
  checking,
}: Props) {
  const projectMissing = project === '';
  return (
    <div className="chat-input">
      <div className="chat-input-row">
        <select
          className="select"
          value={language}
          onChange={(e) => setLanguage(e.target.value as UiLanguage)}
          disabled={streaming}
          title="UI language"
        >
          {LANGUAGES.map((l) => (
            <option key={l.value} value={l.value}>
              {l.label}
            </option>
          ))}
        </select>
        <select
          className="select"
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
          value={provider}
          onChange={(e) => setProvider(e.target.value as ProviderKey)}
          disabled={streaming}
          title="LLM provider"
        >
          {PROVIDER_ORDER.map((p) => (
            <option key={p} value={p} disabled={!availableProviders.includes(p)}>
              {PROVIDER_LABELS[p]}
            </option>
          ))}
        </select>
        <select
          className="select"
          value={model}
          onChange={(e) => setModel(e.target.value)}
          disabled={streaming || !modelsForProvider.length}
          title="Model"
        >
          {modelsForProvider.map((m) => (
            <option key={`${m.provider}:${m.model}`} value={m.model}>
              {m.model}
            </option>
          ))}
        </select>
        <select
          className={`select ${projectMissing ? 'select-missing' : ''}`}
          value={project}
          onChange={(e) => setProject(e.target.value)}
          disabled={streaming}
          title={projectMissing ? 'Select a project before chatting' : 'Project'}
        >
          <option value="">{projectMissing ? '— pick project —' : '(none)'}</option>
          {projects.map((p) => (
            <option key={p} value={p}>
              {p}
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
            disabled={!input.trim() || checking || projectMissing}
            title={projectMissing ? 'Pick a project first' : undefined}
          >
            {checking ? 'Checking…' : 'Send'}
          </button>
        )}
      </div>
    </div>
  );
}
