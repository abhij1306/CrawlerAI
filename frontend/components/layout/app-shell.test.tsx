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

beforeEach(() => {
  vi.clearAllMocks();
  const storage = new Map<string, string>();
  Object.defineProperty(globalThis, 'localStorage', {
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

describe('AppShell reset workspace', () => {
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
    expect(document.body.style.overflow).toBe('hidden');
    expect(document.body.style.touchAction).toBe('none');
  });

  it('closes on Escape and restores focus to the trigger', async () => {
    apiMock.me.mockResolvedValue({
      id: 1,
      email: 'admin@example.com',
      role: 'admin',
      is_active: true,
      created_at: new Date('2026-05-19T00:00:00Z').toISOString(),
      updated_at: new Date('2026-05-19T00:00:00Z').toISOString(),
    });

    renderShell();

    const trigger = await screen.findByRole('button', { name: /reset workspace/i });
    trigger.focus();
    fireEvent.click(trigger);

    expect(
      await screen.findByRole('dialog', { name: /reset workspace data/i }),
    ).toBeInTheDocument();
    await waitFor(() => {
      expect(screen.getByRole('button', { name: /reset workspace data/i })).toHaveFocus();
    });

    fireEvent.keyDown(document, { key: 'Escape' });

    await waitFor(() => {
      expect(
        screen.queryByRole('dialog', { name: /reset workspace data/i }),
      ).not.toBeInTheDocument();
      expect(trigger).toHaveFocus();
    });
    expect(document.body.style.overflow).toBe('');
    expect(document.body.style.touchAction).toBe('');
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
      expect(screen.queryByRole('button', { name: /reset workspace/i })).not.toBeInTheDocument();
    });
  });
});

describe('AppShell sidebar toggle', () => {
  it('exposes a stable sidebar toggle for automation tools', async () => {
    apiMock.me.mockResolvedValue({
      id: 2,
      email: 'user@example.com',
      role: 'user',
      is_active: true,
      created_at: new Date('2026-05-19T00:00:00Z').toISOString(),
      updated_at: new Date('2026-05-19T00:00:00Z').toISOString(),
    });

    renderShell();

    const toggle = await screen.findByRole('button', { name: /collapse sidebar/i });
    expect(toggle).toHaveAttribute('id', 'app-sidebar-toggle');
    expect(toggle).toHaveAttribute('data-testid', 'app-sidebar-toggle');
    expect(toggle).toHaveAttribute('aria-controls', 'app-sidebar-navigation');
    expect(toggle).toHaveAttribute('aria-expanded', 'true');

    fireEvent.click(toggle);

    expect(screen.getByRole('button', { name: /expand sidebar/i })).toHaveAttribute(
      'aria-expanded',
      'false',
    );
  });
});
