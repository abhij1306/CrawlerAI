import { useEffect, useRef, useState } from 'react';
import { useNavigate } from 'react-router-dom';

import { httpErrorStatus } from '@/api/client';
import { dashboardApi } from '../../lib/api/dashboard';
import { trapFocus } from '../../lib/focus-trap';

const resetForbiddenMessage =
  'The API refused reset (admin-only on an older backend build, or a stale session). Stop and restart the FastAPI server so it loads the latest code, then try again, or sign out and sign back in.';

export function useWorkspaceReset(canResetWorkspace: boolean) {
  const navigate = useNavigate();
  const [resetPending, setResetPending] = useState(false);
  const [resetDialogOpen, setResetDialogOpen] = useState(false);
  const [resetError, setResetError] = useState('');
  const resetTriggerRef = useRef<HTMLButtonElement | null>(null);
  const resetDialogRef = useRef<HTMLDialogElement | null>(null);
  const resetConfirmRef = useRef<HTMLButtonElement | null>(null);
  const resetPreviousFocusRef = useRef<HTMLElement | null>(null);
  const resetPendingRef = useRef(resetPending);

  useEffect(() => {
    resetPendingRef.current = resetPending;
  }, [resetPending]);

  useEffect(() => {
    if (!resetDialogOpen) {
      return;
    }
    const previousFocusRef = resetPreviousFocusRef;
    const resetTrigger = resetTriggerRef.current;
    const previousFocus = previousFocusRef.current;
    const previousOverflow = document.body.style.overflow;
    const previousTouchAction = document.body.style.touchAction;
    document.body.style.overflow = 'hidden';
    document.body.style.touchAction = 'none';
    const frame = window.requestAnimationFrame(() => resetConfirmRef.current?.focus());
    const handleKeyDown = (event: KeyboardEvent) => {
      if (event.key === 'Escape') {
        if (resetPendingRef.current) {
          return;
        }
        event.preventDefault();
        setResetDialogOpen(false);
        return;
      }
      trapFocus(event, resetDialogRef.current);
    };
    document.addEventListener('keydown', handleKeyDown);
    return () => {
      window.cancelAnimationFrame(frame);
      document.removeEventListener('keydown', handleKeyDown);
      document.body.style.overflow = previousOverflow;
      document.body.style.touchAction = previousTouchAction;
      const restoreTarget = previousFocus?.isConnected ? previousFocus : resetTrigger;
      restoreTarget?.focus();
      previousFocusRef.current = null;
    };
  }, [resetDialogOpen]);

  async function executeReset() {
    if (!canResetWorkspace) return;
    setResetPending(true);
    setResetError('');
    try {
      await dashboardApi.resetApplicationData();
      globalThis.location.reload();
    } catch (error) {
      const status = httpErrorStatus(error);
      if (status === 401) {
        navigate('/login', { replace: true });
        return;
      }
      if (status === 403) {
        setResetError(resetForbiddenMessage);
        return;
      }
      setResetError(error instanceof Error ? error.message : 'Failed to reset workspace data.');
    } finally {
      setResetPending(false);
    }
  }

  function handleSelectedReset() {
    if (!canResetWorkspace) return;
    setResetError('');
    resetPreviousFocusRef.current =
      document.activeElement instanceof HTMLElement
        ? document.activeElement
        : resetTriggerRef.current;
    setResetDialogOpen(true);
  }

  return {
    executeReset,
    handleSelectedReset,
    resetConfirmRef,
    resetDialogOpen,
    resetDialogRef,
    resetError,
    resetLabel: resetPending ? 'Resetting Workspace...' : 'Reset Workspace',
    resetPending,
    resetTriggerRef,
    setResetDialogOpen,
  };
}
