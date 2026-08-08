import type { ChatSession } from '../api/client';

interface Props {
  sessions: ChatSession[];
  currentSessionId: string | null;
  health: string;
  onSelect: (id: string) => void;
  onDelete: (id: string) => void;
}

export function SessionList({
  sessions,
  currentSessionId,
  health,
  onSelect,
  onDelete,
}: Props) {
  return (
    <aside className="sidebar">
      <div className="sidebar-header">
        <div className="brand">ChatApp-PG</div>
        <div className={`health-pill health-${health}`}>
          API: {health}
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
    </aside>
  );
}
