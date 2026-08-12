import { RouterProvider } from 'react-router-dom';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { router } from './app/router';
import { setQueryClient, setupGlobal401Handler } from './authGuard';
import './styles/global.css';

// Module-level QueryClient — stable across re-renders. The authGuard
// module subscribes to its caches to detect 401s.
const queryClient = new QueryClient({
  defaultOptions: {
    queries: {
      staleTime: 30_000,
      refetchOnWindowFocus: false,
      retry: 1,
    },
  },
});

// Register the QueryClient BEFORE React renders. This avoids the
// useNavigate() bug from the earlier implementation (calling
// useNavigate outside a <Router> throws at runtime).
setQueryClient(queryClient);
setupGlobal401Handler();

export default function App() {
  return (
    <QueryClientProvider client={queryClient}>
      <RouterProvider router={router} />
    </QueryClientProvider>
  );
}