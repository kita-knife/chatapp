import { NavLink, Outlet, useMatch } from 'react-router-dom';
import { clsx } from 'clsx';
import { useChat } from '@/hooks/useChat';
import { useAuth } from '@/features/auth/useAuth';

const navItems: { to: string; label: string; adminOnly?: boolean }[] = [
  { to: '/chat', label: 'Chat' },
  { to: '/rag', label: 'Code RAG' },
  { to: '/mcp', label: 'MCP' },
  { to: '/settings', label: 'Settings' },
  { to: '/admin/users', label: 'Admin', adminOnly: true },
];

const ROLE_LABEL: Record<string, string> = {
  root: 'root',
  admin: 'admin',
  user: 'user',
};

export function AppShell() {
  const auth = useAuth();
  const chat = useChat();
  // The sidebar lives at the parent route `/`, so useParams() doesn't give
  // us the active chat id. Match the `/chat/:sessionId` pattern instead.
  const chatMatch = useMatch('/chat/:sessionId');
  const activeSessionId = chatMatch?.params.sessionId ?? null;

  return (
    <div className="app">
      <aside className="sidebar">
        <div className="sidebar-header">
          <div className="brand">ChatApp-PG</div>
          <div className="pill-row">
            <div className={`health-pill health-${chat.health}`}>API: {chat.health}</div>
            <div
              className={`health-pill ${chat.connectivity?.ok ? 'health-ok' : 'health-down'}`}
              title={chat.connectivity?.error ?? `${chat.connectivity?.provider} ${chat.connectivity?.model}`}
              onClick={() => chat.probeConnectivity()}
              style={{ cursor: 'pointer' }}
            >
              {chat.connectivity
                ? chat.connectivity.ok
                  ? `LLM ${chat.connectivity.latency_ms}ms`
                  : `LLM ✗`
                : 'LLM ?'}
            </div>
          </div>
          <button className="btn-secondary new-chat-btn" onClick={chat.newSession}>
            + New chat
          </button>
        </div>
        <div className="sidebar-list">
          {chat.sessions.length === 0 ? (
            <div className="sidebar-empty">No conversations yet</div>
          ) : (
            chat.sessions.map((s) => (
              <div
                key={s.id}
                className={clsx('sidebar-item', { active: activeSessionId === s.id })}
                onClick={() => chat.selectSession(s.id)}
              >
                <div className="sidebar-item-title">{s.title}</div>
                <div className="sidebar-item-meta">
                  <span>{s.provider ? `${s.provider} / ${s.model}` : s.model}</span>
                  <button
                    className="icon-btn"
                    onClick={(e) => {
                      e.stopPropagation();
                      chat.removeSession(s.id);
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
          {auth.user && (
            <div className="user-card">
              <div className={`user-avatar role-${auth.user.role}`}>
                {auth.user.username.charAt(0).toUpperCase()}
              </div>
              <div className="user-info">
                <div className="user-name">{auth.user.username}</div>
                <div className={`user-role role-${auth.user.role}`}>
                  {ROLE_LABEL[auth.user.role]}
                </div>
              </div>
              <button
                className="icon-btn logout-btn"
                onClick={() => chat.handleLogout()}
                title="Logout"
              >
                ⎋
              </button>
            </div>
          )}
        </div>
      </aside>
      <main className="main">
        <nav className="topnav">
          {navItems
            .filter((i) => !i.adminOnly || auth.isRoot)
            .map((item) => (
              <NavLink
                key={item.to}
                to={item.to}
                className={({ isActive }) => clsx('topnav-item', { active: isActive })}
              >
                {item.label}
              </NavLink>
            ))}
        </nav>
        {chat.error && <div className="error-banner">{chat.error}</div>}
        <div className="main-content">
          <Outlet />
        </div>
      </main>
    </div>
  );
}
