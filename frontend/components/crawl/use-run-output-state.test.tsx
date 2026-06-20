import { fireEvent, render, screen } from '@testing-library/react';
import { MemoryRouter, useLocation } from 'react-router-dom';
import { describe, expect, it } from 'vitest';

import { useRunOutputState } from './use-run-output-state';

function Harness({ showLearningTab = true }: Readonly<{ showLearningTab?: boolean }>) {
  const location = useLocation();
  const state = useRunOutputState({ failedRunWithoutRecords: false, showLearningTab });
  return (
    <div>
      <output aria-label="active output tab">{state.outputTab}</output>
      <output aria-label="current search">{location.search}</output>
      <button type="button" onClick={() => state.setOutputTab('logs')}>
        Logs
      </button>
      <button type="button" onClick={() => state.setOutputTab('table')}>
        Table
      </button>
    </div>
  );
}

describe('useRunOutputState', () => {
  it('persists non-default output tabs and preserves the run id', () => {
    render(
      <MemoryRouter initialEntries={['/crawl?run_id=42&output=json']}>
        <Harness />
      </MemoryRouter>,
    );

    expect(screen.getByLabelText('active output tab')).toHaveTextContent('json');
    fireEvent.click(screen.getByRole('button', { name: 'Logs' }));
    expect(screen.getByLabelText('current search')).toHaveTextContent('?run_id=42&output=logs');
    fireEvent.click(screen.getByRole('button', { name: 'Table' }));
    expect(screen.getByLabelText('current search')).toHaveTextContent('?run_id=42');
  });

  it('falls back to table when a hidden learning tab is requested', () => {
    render(
      <MemoryRouter initialEntries={['/crawl?run_id=42&output=learning']}>
        <Harness showLearningTab={false} />
      </MemoryRouter>,
    );

    expect(screen.getByLabelText('active output tab')).toHaveTextContent('table');
  });
});
