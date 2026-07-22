import { render, screen } from '@testing-library/react';
import { describe, expect, it } from 'vite-plus/test';

import { Badge } from './badge';

describe('Badge', () => {
  it('renders children with the neutral chip box by default', () => {
    render(<Badge>Run 1</Badge>);
    const badge = screen.getByText('Run 1');
    expect(badge).toHaveClass('text-muted');
    expect(badge).toHaveClass('rounded-full', 'border', 'border-border', 'bg-panel');
  });

  it('maps tones to semantic text tokens without a chip box', () => {
    render(<Badge tone="success">Completed</Badge>);
    const badge = screen.getByText('Completed');
    expect(badge).toHaveClass('text-success-text');
    expect(badge).not.toHaveClass('border-border');
  });

  it('flat neutral drops the chip box', () => {
    render(<Badge flat>Killed</Badge>);
    const badge = screen.getByText('Killed');
    expect(badge).toHaveClass('text-muted');
    expect(badge).not.toHaveClass('rounded-full');
  });

  it('pulses the dot only for the accent tone', () => {
    const { container, rerender } = render(<Badge tone="accent">Running</Badge>);
    const dot = () => container.querySelector('span > span');
    expect(dot()).toHaveClass('animate-pulse');

    rerender(<Badge tone="danger">Failed</Badge>);
    expect(dot()).not.toHaveClass('animate-pulse');
  });

  it('passes through className and span attributes', () => {
    render(
      <Badge tone="warning" className="origin-right scale-90" data-testid="status-badge">
        Paused
      </Badge>,
    );
    const badge = screen.getByTestId('status-badge');
    expect(badge).toHaveClass('origin-right', 'scale-90', 'text-warning-text');
  });
});
