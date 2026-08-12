import { useState } from 'react';
import { useQueryClient } from '@tanstack/react-query';
import { useMyPreferences, useUpdateMyPreferences } from '@/features/auth/useAuth';
import { useChat } from '@/hooks/useChat';
import { AGENT_MODES } from '@/components/ChatInput';

const LANGUAGES = [
  { value: 'zh', label: '中文' },
  { value: 'en', label: 'English' },
] as const;

export function SettingsPage() {
  const prefs = useMyPreferences();
  const update = useUpdateMyPreferences();
  const chat = useChat();
  const qc = useQueryClient();
  const [saved, setSaved] = useState(false);

  const current = prefs.data;

  if (prefs.isLoading || !current) {
    return <div className="placeholder-page">Loading preferences…</div>;
  }

  const save = async (patch: Partial<typeof current>) => {
    setSaved(false);
    await update.mutateAsync({ preferences: patch });
    setSaved(true);
    setTimeout(() => setSaved(false), 2000);
  };

  return (
    <div className="settings-page">
      <div className="page-header">
        <h1>Settings</h1>
        <p className="muted">Your preferences are persisted on the server and applied to every conversation.</p>
      </div>

      {saved && <div className="ok-banner">Saved.</div>}

      <section className="admin-section">
        <h2>Default agent mode</h2>
        <p className="muted">
          Applies whenever you start a new conversation or skip the mode picker.
        </p>
        <div className="form-row-group">
          {AGENT_MODES.map((m) => (
            <button
              key={m.value}
              className={`btn-secondary ${current.default_mode === m.value ? 'btn-active' : ''}`}
              onClick={() => save({ default_mode: m.value })}
              title={m.description}
            >
              {m.label}
            </button>
          ))}
        </div>
        <p className="muted small">Current selection: <strong>{current.default_mode}</strong></p>
      </section>

      <section className="admin-section">
        <h2>Default model</h2>
        <div className="form-row-group">
          <select
            value={current.default_model ?? ''}
            onChange={(e) => {
              const newModel = e.target.value || null;
              save({ default_model: newModel });
              // Mirror to the local TanStack Query cache so ChatInput's
              // model select reflects the new default without waiting for
              // a refetch round-trip. (`save` above invalidates
              // ['auth','me','preferences'], which Settings' own select reads
              // from — but the chat input reads `['ui','model']` instead.)
              qc.setQueryData(['ui', 'model'], newModel ?? '');
              try {
                window.localStorage.setItem('chatapp.model', newModel ?? '');
              } catch {
                /* ignore */
              }
            }}
            className="select"
          >
            <option value="">Use system default ({chat.models[0]?.model ?? 'unset'})</option>
            {chat.models
              .filter((m, i, arr) => arr.findIndex((x) => x.model === m.model) === i)
              .map((m) => (
                <option key={`${m.provider}:${m.model}`} value={m.model}>
                  {m.provider} / {m.model}
                </option>
              ))}
          </select>
        </div>
      </section>

      <section className="admin-section">
        <h2>UI language</h2>
        <div className="form-row-group">
          {LANGUAGES.map((l) => (
            <button
              key={l.value}
              className={`btn-secondary ${current.ui_language === l.value ? 'btn-active' : ''}`}
              onClick={() => save({ ui_language: l.value })}
            >
              {l.label}
            </button>
          ))}
        </div>
      </section>

      <section className="admin-section">
        <h2>Current session</h2>
        <p className="muted">
          The mode for the next message will be: <strong>{chat.mode}</strong>
          {' · '}
          Model: <strong>{chat.model || 'unset'}</strong>
        </p>
        <p className="muted small">
          (The picker above the input box overrides the default for the current
          conversation.)
        </p>
      </section>
    </div>
  );
}