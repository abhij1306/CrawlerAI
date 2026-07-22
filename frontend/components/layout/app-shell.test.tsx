import { fireEvent, render, screen, waitFor } from '@testing-library/react';
import { MemoryRouter } from 'react-router-dom';
import { beforeEach, describe, expect, it, vi } from 'vite-plus/test';

import { SessionProvider } from '../../src/app/session';
import { AppShell } from './app-shell';

const apiMock = vi.hoisted(() => ({
  resetApplicationData: vi.fn(),
}));

vi.mock('../../lib/api', () => ({ api: apiMock }));

function renderShell(role: 'admin' | 'user' = 'admin') {
  render(
    <MemoryRouter initialEntries={['/dashboard']}>
      <SessionProvider
        user={{
          id: role === 'admin' ? 1 : 2,
          email: `${role}@example.com`,
          role,
          is_active: true,
          created_at: '2026-05-19T00:00:00Z',
          updated_at: '2026-05-19T00:00:00Z',
        }}
      >
        <AppShell>
          <div>Child content</div>
        </AppShell>
      </SessionProvider>
    </MemoryRouter>,
  );
}

beforeEach(() => {
  vi.clearAllMocks();
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

describe('AppShell reset workspace', () => {
  it('opens the confirm dialog when reset is clicked', async () => {
    renderShell();
    fireEvent.click(screen.getByRole('button', { name: /reset workspace/i }));
    expect(
      await screen.findByRole('dialog', { name: /reset workspace data/i }),
    ).toBeInTheDocument();
    expect(document.body.style.overflow).toBe('hidden');
    expect(document.body.style.touchAction).toBe('none');
  });

  it('closes on Escape and restores focus to the trigger', async () => {
    renderShell();
    const trigger = screen.getByRole('button', { name: /reset workspace/i });
    trigger.focus();
    fireEvent.click(trigger);
    const dialog = await screen.findByRole('dialog', { name: /reset workspace data/i });
    await waitFor(() => {
      expect(dialog.contains(document.activeElement)).toBe(true);
    });
    fireEvent.keyDown(document, { key: 'Escape' });
    await waitFor(() => {
      expect(
        screen.queryByRole('dialog', { name: /reset workspace data/i }),
      ).not.toBeInTheDocument();
      expect(trigger).toHaveFocus();
    });
  });

  it('keeps the dialog open and surfaces API errors on confirm failure', async () => {
    apiMock.resetApplicationData.mockRejectedValue(new Error('reset failed: database busy'));
    renderShell();
    fireEvent.click(screen.getByRole('button', { name: /reset workspace/i }));
    const dialog = await screen.findByRole('dialog', { name: /reset workspace data/i });
    fireEvent.click(screen.getByRole('button', { name: /reset workspace data/i }));
    expect(apiMock.resetApplicationData).toHaveBeenCalledTimes(1);
    expect(await screen.findByRole('alert')).toHaveTextContent('reset failed: database busy');
    expect(dialog).toBeInTheDocument();
  });

  it('ignores Escape while the reset is pending', async () => {
    apiMock.resetApplicationData.mockReturnValue(new Promise(() => {}));
    renderShell();
    fireEvent.click(screen.getByRole('button', { name: /reset workspace/i }));
    await screen.findByRole('dialog', { name: /reset workspace data/i });
    fireEvent.click(screen.getByRole('button', { name: /reset workspace data/i }));
    expect(await screen.findByRole('button', { name: 'Working...' })).toBeDisabled();
    fireEvent.keyDown(document, { key: 'Escape' });
    await waitFor(() => {
      expect(screen.getByRole('dialog', { name: /reset workspace data/i })).toBeInTheDocument();
    });
  });

  it('hides workspace reset and admin navigation for non-admin users', () => {
    renderShell('user');
    expect(screen.queryByRole('button', { name: /reset workspace/i })).not.toBeInTheDocument();
    expect(screen.queryByRole('link', { name: 'Users' })).not.toBeInTheDocument();
  });
});

describe('AppShell sidebar toggle', () => {
  it('exposes a stable sidebar toggle for automation tools', () => {
    renderShell('user');
    const toggle = screen.getByRole('button', { name: /collapse sidebar/i });
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
