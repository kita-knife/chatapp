import { createBrowserRouter, Navigate } from 'react-router-dom';
import { AppShell } from './AppShell';
import { LoginPage } from '@/features/auth/LoginPage';
import { ChatPage } from '@/features/chat/ChatPage';
import { RagPage } from '@/features/rag/RagPage';
import { McpPage } from '@/features/mcp/McpPage';
import { SettingsPage } from '@/features/settings/SettingsPage';
import { AdminUsersPage } from '@/features/admin/AdminUsersPage';
import { ProtectedRoute } from '@/shared/components/ProtectedRoute';

export const router = createBrowserRouter([
  { path: '/login', element: <LoginPage /> },
  {
    path: '/',
    element: (
      <ProtectedRoute>
        <AppShell />
      </ProtectedRoute>
    ),
    children: [
      { index: true, element: <Navigate to="/chat" replace /> },
      { path: 'chat', element: <ChatPage /> },
      { path: 'chat/:sessionId', element: <ChatPage /> },
      { path: 'rag', element: <RagPage /> },
      { path: 'mcp', element: <McpPage /> },
      { path: 'settings', element: <SettingsPage /> },
      { path: 'admin/users', element: <AdminUsersPage /> },
    ],
  },
  { path: '*', element: <Navigate to="/" replace /> },
]);
