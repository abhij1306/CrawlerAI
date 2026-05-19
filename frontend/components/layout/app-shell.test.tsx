import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { fireEvent, render, screen, waitFor } from '@testing-library/react';
import { beforeEach, describe, expect, it, vi } from 'vitest';

import { AppShell } from './app-shell';

const routerReplaceMock = vi.fn();

vi.mock('next/navigation', () => ({
  usePathname: () => '/dashboard',
  useRouter: () => ({
    replace: routerReplaceMock,
  }),
}));

const apiMock = vi.hoisted(() => ({
  me: vi.fn(),
  resetApplicationData: vi.fn(),
}));

vi.mock('../../lib/api', () => ({
  api: apiMock,
}));

function renderShell() {
  const queryClient = new QueryClient({
    defaultOptions: {
      mutations: { retry: false },
      queries: { retry: false },
    },
  });

  render(
    <QueryClientProvider client={queryClient}>
      <AppShell>
        <div>Child content</div>
      </AppShell>
    </QueryClientProvider>,
  );
}

describe('AppShell reset workspace', () => {
  beforeEach(() => {
    vi.clearAllMocks();
    const storage = new Map<string, string>();
    Object.defineProperty(window, 'localStorage', {
      writable: true,
      value: {
        getItem: vi.fn((key: string) => storage.get(key) ?? null),
        setItem: vi.fn((key: string, value: string) => {
          storage.set(key, value);
        }),
        removeItem: vi.fn((key: string) => {
          storage.delete(key);
        }),
        clear: vi.fn(() => {
          storage.clear();
        }),
      },
    });
    Object.defineProperty(window, 'matchMedia', {
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

  it('opens the confirm dialog when reset is clicked', async () => {
    apiMock.me.mockResolvedValue({
      id: 1,
      email: 'admin@example.com',
      role: 'admin',
      is_active: true,
      created_at: new Date('2026-05-19T00:00:00Z').toISOString(),
      updated_at: new Date('2026-05-19T00:00:00Z').toISOString(),
    });

    renderShell();

    fireEvent.click(await screen.findByRole('button', { name: /reset workspace/i }));

    expect(
      await screen.findByRole('dialog', { name: /reset workspace data/i }),
    ).toBeInTheDocument();
  });

  it('hides workspace reset for non-admin users', async () => {
    apiMock.me.mockResolvedValue({
      id: 2,
      email: 'user@example.com',
      role: 'user',
      is_active: true,
      created_at: new Date('2026-05-19T00:00:00Z').toISOString(),
      updated_at: new Date('2026-05-19T00:00:00Z').toISOString(),
    });

    renderShell();

    await waitFor(() => {
      expect(apiMock.me).toHaveBeenCalled();
    });

    expect(screen.queryByRole('button', { name: /reset workspace/i })).not.toBeInTheDocument();
  });
});
