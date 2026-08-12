import { useState } from 'react';
import { useNavigate, useLocation } from 'react-router-dom';
import { useLogin } from './useAuth';

export function LoginPage() {
  const navigate = useNavigate();
  const location = useLocation();
  const from = (location.state as { from?: Location })?.from?.pathname || '/chat';
  const [username, setUsername] = useState('');
  const [password, setPassword] = useState('');
  const [error, setError] = useState<string | null>(null);

  const login = useLogin();

  return (
    <div className="login-page">
      <form
        className="login-card"
        onSubmit={(e) => {
          e.preventDefault();
          setError(null);
          login.mutate(
            { username, password },
            {
              onSuccess: () => navigate(from, { replace: true }),
              onError: (err: Error) => setError(err.message),
            },
          );
        }}
      >
        <h1 className="login-title">ChatApp-PG</h1>
        <p className="login-sub">Sign in to your account</p>
        <div className="form-row">
          <label>Username</label>
          <input
            type="text"
            value={username}
            onChange={(e) => setUsername(e.target.value)}
            autoComplete="username"
            autoFocus
            required
          />
        </div>
        <div className="form-row">
          <label>Password</label>
          <input
            type="password"
            value={password}
            onChange={(e) => setPassword(e.target.value)}
            autoComplete="current-password"
            required
          />
        </div>
        {error && <div className="form-error">{error}</div>}
        <button type="submit" className="btn-primary login-submit" disabled={login.isPending}>
          {login.isPending ? 'Signing in…' : 'Sign in'}
        </button>
        <p className="login-hint">
          No account? Ask a root user to create one via the Admin panel.
        </p>
      </form>
    </div>
  );
}
