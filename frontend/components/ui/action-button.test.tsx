import { fireEvent, render, screen } from '@testing-library/react';
import { XCircle } from 'lucide-react';
import { describe, expect, it, vi } from 'vite-plus/test';

import { ActionButton } from './action-button';

describe('ActionButton', () => {
  it('renders the label with the secondary variant by default', () => {
    render(<ActionButton label="Retry" />);
    const button = screen.getByRole('button', { name: 'Retry' });
    expect(button).toHaveClass('bg-panel');
    expect(button).not.toHaveClass('text-danger-text');
  });

  it('uses the destructive variant when danger is set', () => {
    render(<ActionButton label="Hard Kill" danger />);
    const button = screen.getByRole('button', { name: 'Hard Kill' });
    expect(button).toHaveClass('text-danger-text');
    expect(button).not.toHaveClass('bg-panel');
  });

  it('renders the optional leading icon only when provided', () => {
    const { container, rerender } = render(<ActionButton label="Hard Kill" icon={XCircle} />);
    expect(container.querySelector('svg')).not.toBeNull();

    rerender(<ActionButton label="Hard Kill" />);
    expect(container.querySelector('svg')).toBeNull();
  });

  it('fires onClick and respects disabled', () => {
    const onClick = vi.fn();
    const { rerender } = render(<ActionButton label="Hard Kill" onClick={onClick} />);
    fireEvent.click(screen.getByRole('button', { name: 'Hard Kill' }));
    expect(onClick).toHaveBeenCalledTimes(1);

    rerender(<ActionButton label="Hard Kill" onClick={onClick} disabled />);
    const button = screen.getByRole('button', { name: 'Hard Kill' });
    expect(button).toBeDisabled();
    fireEvent.click(button);
    expect(onClick).toHaveBeenCalledTimes(1);
  });
});
