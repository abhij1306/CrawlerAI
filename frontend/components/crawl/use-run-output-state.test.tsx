import { fireEvent, render, screen } from '@testing-library/react';
import { beforeEach, describe, expect, it } from 'vite-plus/test';

import { routeMock } from './crawl-run-screen.test-support';
import { useRunOutputState } from './use-run-output-state';

function Harness({ showLearningTab = true }: Readonly<{ showLearningTab?: boolean }>) {
  const state = useRunOutputState({ failedRunWithoutRecords: false, showLearningTab });
  return (
    <div>
      <output aria-label="active output tab">{state.outputTab}</output>
      <button type="button" onClick={() => state.setOutputTab('events')}>
        Run Events
      </button>
      <button type="button" onClick={() => state.setOutputTab('table')}>
        Table
      </button>
    </div>
  );
}

describe('useRunOutputState', () => {
  beforeEach(() => {
    routeMock.searchParams = 'run_id=42';
  });

  it('persists non-default output tabs and preserves the run id', () => {
    routeMock.searchParams = 'run_id=42&output=json';
    render(<Harness />);

    expect(screen.getByLabelText('active output tab')).toHaveTextContent('json');
    fireEvent.click(screen.getByRole('button', { name: 'Run Events' }));
    expect(screen.getByLabelText('active output tab')).toHaveTextContent('events');
    expect(routeMock.searchParams).toBe('run_id=42&output=events');
    fireEvent.click(screen.getByRole('button', { name: 'Table' }));
    expect(screen.getByLabelText('active output tab')).toHaveTextContent('table');
    expect(routeMock.searchParams).toBe('run_id=42');
  });

  it('falls back to table when a hidden learning tab is requested', () => {
    routeMock.searchParams = 'run_id=42&output=learning';
    render(<Harness showLearningTab={false} />);

    expect(screen.getByLabelText('active output tab')).toHaveTextContent('table');
  });
});
