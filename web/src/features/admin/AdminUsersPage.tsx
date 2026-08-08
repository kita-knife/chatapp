import { useEffect, useState } from 'react';
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query';
import { api, type User } from '@/api/client';

export function AdminUsersPage() {
  const qc = useQueryClient();
  const [error, setError] = useState<string | null>(null);
  const [newUser, setNewUser] = useState({ username: '', password: '', role: 'user' as 'admin' | 'user' });
  const [editing, setEditing] = useState<{ id: string; password: string } | null>(null);

  const users = useQuery({
    queryKey: ['admin', 'users'],
    queryFn: () => api.listUsers(),
  });

  const create = useMutation({
    mutationFn: ({ username, password, role }: { username: string; password: string; role: 'admin' | 'user' }) =>
      api.createUser(username, password, role),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ['admin', 'users'] });
      setNewUser({ username: '', password: '', role: 'user' });
    },
    onError: (err: Error) => setError(err.message),
  });

  const remove = useMutation({
    mutationFn: (id: string) => api.deleteUser(id),
    onSuccess: () => qc.invalidateQueries({ queryKey: ['admin', 'users'] }),
    onError: (err: Error) => setError(err.message),
  });

  const changePwd = useMutation({
    mutationFn: ({ id, password }: { id: string; password: string }) => api.changePassword(id, password),
    onSuccess: () => setEditing(null),
    onError: (err: Error) => setError(err.message),
  });

  useEffect(() => {
    setError(null);
  }, [users.data]);

  return (
    <div className="admin-page">
      <div className="page-header">
        <h1>Users</h1>
        <p className="muted">Manage accounts and roles. Maximum 4 root users (configurable via MAX_ROOT_USERS).</p>
      </div>

      {error && <div className="error-banner">{error}</div>}

      <section className="admin-section">
        <h2>Create user</h2>
        <form
          className="form-row-group"
          onSubmit={(e) => {
            e.preventDefault();
            create.mutate(newUser);
          }}
        >
          <input
            placeholder="username"
            value={newUser.username}
            onChange={(e) => setNewUser({ ...newUser, username: e.target.value })}
            minLength={3}
            maxLength={64}
            required
          />
          <input
            placeholder="password (≥ 8 chars)"
            type="password"
            value={newUser.password}
            onChange={(e) => setNewUser({ ...newUser, password: e.target.value })}
            minLength={8}
            required
          />
          <select
            value={newUser.role}
            onChange={(e) => setNewUser({ ...newUser, role: e.target.value as 'admin' | 'user' })}
          >
            <option value="user">user</option>
            <option value="admin">admin</option>
          </select>
          <button type="submit" className="btn-primary" disabled={create.isPending}>
            {create.isPending ? 'Creating…' : 'Create'}
          </button>
        </form>
      </section>

      <section className="admin-section">
        <h2>Existing users</h2>
        <table className="admin-table">
          <thead>
            <tr>
              <th>Username</th>
              <th>Role</th>
              <th>Last login</th>
              <th>Created</th>
              <th></th>
            </tr>
          </thead>
          <tbody>
            {users.data?.map((u: User) => (
              <tr key={u.id}>
                <td>{u.username}</td>
                <td>
                  <span className={`role-pill role-${u.role}`}>{u.role}</span>
                </td>
                <td>{u.last_login_at ? new Date(u.last_login_at).toLocaleString() : '—'}</td>
                <td>{u.created_at ? new Date(u.created_at).toLocaleString() : '—'}</td>
                <td>
                  <div className="row-actions">
                    {editing?.id === u.id ? (
                      <>
                        <input
                          type="password"
                          placeholder="new password"
                          value={editing.password}
                          onChange={(e) => setEditing({ ...editing, password: e.target.value })}
                          minLength={8}
                        />
                        <button
                          className="btn-secondary"
                          onClick={() => changePwd.mutate({ id: u.id, password: editing.password })}
                          disabled={editing.password.length < 8 || changePwd.isPending}
                        >
                          Save
                        </button>
                        <button className="btn-secondary" onClick={() => setEditing(null)}>
                          Cancel
                        </button>
                      </>
                    ) : (
                      <>
                        <button className="btn-secondary" onClick={() => setEditing({ id: u.id, password: '' })}>
                          Change password
                        </button>
                        <button
                          className="btn-danger"
                          onClick={() => {
                            if (confirm(`Delete user '${u.username}'? This cannot be undone.`)) {
                              remove.mutate(u.id);
                            }
                          }}
                        >
                          Delete
                        </button>
                      </>
                    )}
                  </div>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </section>
    </div>
  );
}
