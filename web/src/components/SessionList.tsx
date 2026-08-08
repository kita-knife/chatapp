import type { ChatSession, ConnectivityResult, User } from '../api/client';

interface Props {
  sessions: ChatSession[];
  currentSessionId: string | null;
  health: string;
  connectivity: ConnectivityResult | null;
  user: User | null;
  isRoot: boolean;
  onSelect: (id: string) => void;
  onDelete: (id: string) => void;
  onProbe: () => void;
  onLogout: () => void;
  onAdmin: () => void;
}

const ROLE_LABEL: Record<string, string> = {
  root: 'root',
  admin: 'admin',
  user: 'user',
};

export function SessionList({
  sessions,
  currentSessionId,
  health,
  connectivity,
  user,
  isRoot,
  onSelect,
  onDelete,
  onProbe,
  onLogout,
  onAdmin,
}: Props) {
  const connLabel = connectivity
    ? connectivity.ok
      ? `LLM ${connectivity.latency_ms}ms`
      : `LLM ✗`
    : 'LLM ?';
  return (
    <aside className="sidebar">
      <div className="sidebar-header">
        <div className="brand">ChatApp-PG</div>
        <div className="pill-row">
          <div className={`health-pill health-${health}`}>API: {health}</div>
          <div
            className={`health-pill ${connectivity?.ok ? 'health-ok' : 'health-down'}`}
            title={connectivity?.error ?? `${connectivity?.provider} ${connectivity?.model}`}
            onClick={onProbe}
            style={{ cursor: 'pointer' }}
          >
            {connLabel}
          </div>
        </div>
      </div>
      <div className="sidebar-list">
        {sessions.length === 0 ? (
          <div className="sidebar-empty">No conversations yet</div>
        ) : (
          sessions.map((s) => (
            <div
              key={s.id}
              className={`sidebar-item ${currentSessionId === s.id ? 'active' : ''}`}
              onClick={() => onSelect(s.id)}
            >
              <div className="sidebar-item-title">{s.title}</div>
              <div className="sidebar-item-meta">
                <span>{s.model}</span>
                <button
                  className="icon-btn"
                  onClick={(e) => {
                    e.stopPropagation();
                    onDelete(s.id);
                  }}
                  title="Delete"
                >
                  ×
                </button>
              </div>
            </div>
          ))
        )}
      </div>
      <div className="sidebar-footer">
        {isRoot && (
          <button className="sidebar-footer-btn" onClick={onAdmin} title="Admin panel">
            ⚙ Admin
          </button>
        )}
        <div className="user-card">
          <div className={`user-avatar role-${user?.role || 'user'}`}>
            {(user?.username || '?').charAt(0).toUpperCase()}
          </div>
          <div className="user-info">
            <div className="user-name">{user?.username}</div>
            <div className={`user-role role-${user?.role || 'user'}`}>
              {ROLE_LABEL[user?.role || 'user']}
            </div>
          </div>
          <button className="icon-btn logout-btn" onClick={onLogout} title="Logout">
            ⎋
          </button>
        </div>
      </div>
    </aside>
  );
}
