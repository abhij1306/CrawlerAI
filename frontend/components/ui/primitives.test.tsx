import { fireEvent, render, screen } from '@testing-library/react';
import { describe, expect, it, vi } from 'vite-plus/test';

import { Dropdown, Skeleton, Toggle } from './primitives';
import { Tooltip } from './tooltip';

describe('Dropdown', () => {
  it('uses native keyboard, change, and disabled behavior', () => {
    const handleChange = vi.fn();

    render(
      <Dropdown
        ariaLabel="Surface"
        value="jobs / detail"
        onChange={handleChange}
        options={[
          { value: 'jobs / detail', label: 'Jobs Detail' },
          { value: 'commerce:listing', label: 'Commerce Listing' },
        ]}
      />,
    );

    const combobox = screen.getByRole('combobox', { name: 'Surface' });
    expect(combobox.tagName).toBe('SELECT');
    fireEvent.change(combobox, { target: { value: 'commerce:listing' } });
    expect(handleChange).toHaveBeenCalledWith('commerce:listing');

    const { rerender } = render(<div />);
    rerender(
      <Dropdown
        ariaLabel="Disabled surface"
        value="jobs / detail"
        onChange={handleChange}
        options={[{ value: 'jobs / detail', label: 'Jobs Detail' }]}
        disabled
      />,
    );
    expect(screen.getByRole('combobox', { name: 'Disabled surface' })).toBeDisabled();
  });
});

describe('Tooltip', () => {
  it('opens from its focusable child and wires aria-describedby', () => {
    render(
      <Tooltip content="Helpful context">
        <button type="button" aria-label="More information">
          i
        </button>
      </Tooltip>,
    );

    const trigger = screen.getByRole('button', { name: 'More information' });
    fireEvent.focus(trigger);
    const tooltip = screen.getByRole('tooltip');
    expect(trigger).toHaveAttribute('aria-describedby', tooltip.id);
    fireEvent.blur(trigger);
    expect(screen.queryByRole('tooltip')).toBeNull();
  });

  it('appends its description to an existing aria-describedby value', () => {
    render(
      <Tooltip content="Helpful context">
        <button type="button" aria-label="Details" aria-describedby="existing-description">
          i
        </button>
      </Tooltip>,
    );

    const trigger = screen.getByRole('button', { name: 'Details' });
    fireEvent.focus(trigger);
    const tooltip = screen.getByRole('tooltip');
    expect(trigger).toHaveAttribute('aria-describedby', `existing-description ${tooltip.id}`);
  });
});

describe('Toggle', () => {
  it('uses dedicated track tokens instead of button accent tokens', () => {
    const handleChange = vi.fn();

    const { rerender } = render(
      <Toggle checked={false} onChange={handleChange} ariaLabel="Proxy" />,
    );

    const toggle = screen.getByRole('switch', { name: 'Proxy' });
    expect(toggle).toHaveClass('toggle-track-off');
    expect(toggle).not.toHaveClass('bg-accent');

    rerender(<Toggle checked={true} onChange={handleChange} ariaLabel="Proxy" />);

    expect(toggle).toHaveClass('toggle-track-on');
    expect(toggle).not.toHaveClass('bg-accent');
  });
});

describe('Skeleton', () => {
  it('stays purely decorative for assistive tech', () => {
    render(<Skeleton className="h-4 w-12" />);

    const skeleton = document.querySelector('.skeleton');
    expect(skeleton).toHaveAttribute('aria-hidden', 'true');
  });
});
