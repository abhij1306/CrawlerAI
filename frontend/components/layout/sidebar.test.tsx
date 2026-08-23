import { QueryClientProvider } from '@tanstack/react-query';
import { fireEvent, render, screen, waitFor } from '@testing-library/react';
import { MemoryRouter, useLocation } from 'react-router-dom';
import { beforeEach, describe, expect, it, vi } from 'vite-plus/test';

import { STORAGE_KEYS } from '../../lib/constants/storage-keys';
import { createAppQueryClient } from '../../src/api/query-client';
import { AUTH_SESSION_QUERY_KEY } from './auth-session-query';
import { Sidebar } from './sidebar';

function LocationProbe() {
  const location = useLocation();
  return <output data-testid="location-probe">{location.pathname}</output>;
}

function renderSidebar() {
  const queryClient = createAppQueryClient();
  queryClient.setQueryData(AUTH_SESSION_QUERY_KEY, {
    id: 1,
    email: 'admin@example.com',
    role: 'admin',
    is_active: true,
    created_at: '2026-05-19T00:00:00Z',
    updated_at: '2026-05-19T00:00:00Z',
  });
  queryClient.setQueryData(['runs', 'list'], [{ id: 1 }]);
  render(
    <QueryClientProvider client={queryClient}>
      <MemoryRouter initialEntries={['/dashboard']}>
        <Sidebar pathname="/dashboard" isAdmin accountEmail="admin@example.com" />
        <LocationProbe />
      </MemoryRouter>
    </QueryClientProvider>,
  );
  return queryClient;
}

beforeEach(() => {
  vi.unstubAllGlobals();
  const storage = new Map<string, string>();
  Object.defineProperty(globalThis, 'localStorage', {
    writable: true,
    value: {
      getItem: vi.fn((key: string) => storage.get(key) ?? null),
      setItem: vi.fn((key: string, value: string) => storage.set(key, value)),
      removeItem: vi.fn((key: string) => storage.delete(key)),
      clear: vi.fn(() => storage.clear()),
    },
  });
  Object.defineProperty(globalThis, 'matchMedia', {
    writable: true,
    value: vi.fn().mockImplementation(() => ({
      matches: false,
      media: '',
      onchange: null,
      addListener: vi.fn(),
      removeListener: vi.fn(),
      addEventListener: vi.fn(),
      removeEventListener: vi.fn(),
      dispatchEvent: vi.fn(),
    })),
  });
});

describe('Sidebar logout', () => {
  it('shows the active account in place of the old theme section', () => {
    renderSidebar();

    expect(screen.getByText('Account')).toBeInTheDocument();
    expect(screen.getByText('admin@example.com')).toBeInTheDocument();
  });

  it('posts to the logout endpoint, clears cached queries, and navigates to /login', async () => {
    const fetchMock = vi.fn().mockResolvedValue(new Response(null, { status: 204 }));
    vi.stubGlobal('fetch', fetchMock);

    const queryClient = renderSidebar();
    fireEvent.click(screen.getByRole('button', { name: 'Log out' }));

    await waitFor(() => {
      expect(screen.getByTestId('location-probe')).toHaveTextContent('/login');
    });

    expect(fetchMock).toHaveBeenCalledTimes(1);
    const [url, init] = fetchMock.mock.calls[0] as [string, RequestInit];
    expect(String(url)).toContain('/api/auth/logout');
    expect(init.method).toBe('POST');
    expect(queryClient.getQueryData(AUTH_SESSION_QUERY_KEY)).toBeNull();
    expect(queryClient.getQueryData(['runs', 'list'])).toBeUndefined();
  });

  it('still clears the session and navigates when the logout request fails', async () => {
    const fetchMock = vi.fn().mockRejectedValue(new Error('network down'));
    vi.stubGlobal('fetch', fetchMock);

    const queryClient = renderSidebar();
    fireEvent.click(screen.getByRole('button', { name: 'Log out' }));

    await waitFor(() => {
      expect(screen.getByTestId('location-probe')).toHaveTextContent('/login');
    });

    expect(fetchMock).toHaveBeenCalledTimes(1);
    expect(queryClient.getQueryData(AUTH_SESSION_QUERY_KEY)).toBeNull();
    expect(queryClient.getQueryData(['runs', 'list'])).toBeUndefined();
  });

  it('still navigates when the server answers with an error status', async () => {
    const fetchMock = vi.fn().mockResolvedValue(new Response('Not Found', { status: 404 }));
    vi.stubGlobal('fetch', fetchMock);

    const queryClient = renderSidebar();
    fireEvent.click(screen.getByRole('button', { name: 'Log out' }));

    await waitFor(() => {
      expect(screen.getByTestId('location-probe')).toHaveTextContent('/login');
    });

    expect(fetchMock).toHaveBeenCalledTimes(1);
    expect(queryClient.getQueryData(AUTH_SESSION_QUERY_KEY)).toBeNull();
  });

  it('renders the collapsed rail logout as an icon-only button with a tooltip', () => {
    window.localStorage.setItem(STORAGE_KEYS.SIDEBAR_COLLAPSED, 'true');

    renderSidebar();

    const logout = screen.getByRole('button', { name: 'Log out' });
    expect(logout.textContent).toBe('');
    expect(logout).toHaveAttribute('aria-describedby');
  });
});
