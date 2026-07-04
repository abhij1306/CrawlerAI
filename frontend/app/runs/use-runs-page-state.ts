import { useReducer } from 'react';

import type { CrawlRun, RunStatus } from '../../lib/api/types';

export type StatusFilter = '' | RunStatus;

type RunsPageState = {
  domainFilter: string;
  statusFilter: StatusFilter;
  appliedDomainFilter: string;
  appliedStatusFilter: StatusFilter;
  pendingDeleteIds: Set<number>;
  actionError: string;
  deleteTarget: CrawlRun | null;
};

type RunsPageAction =
  | { type: 'domainFilterChanged'; value: string }
  | { type: 'statusFilterChanged'; value: StatusFilter }
  | { type: 'filtersApplied' }
  | { type: 'filtersReset' }
  | { type: 'deleteStarted'; runId: number }
  | { type: 'deleteSucceeded' }
  | { type: 'deleteFailed'; message: string }
  | { type: 'deleteSettled'; runId: number }
  | { type: 'deleteRequested'; run: CrawlRun }
  | { type: 'deleteDialogClosed' };

const initialRunsPageState: RunsPageState = {
  domainFilter: '',
  statusFilter: '',
  appliedDomainFilter: '',
  appliedStatusFilter: '',
  pendingDeleteIds: new Set(),
  actionError: '',
  deleteTarget: null,
};

function addPendingDeleteId(state: RunsPageState, runId: number) {
  const pendingDeleteIds = new Set(state.pendingDeleteIds);
  pendingDeleteIds.add(runId);
  return pendingDeleteIds;
}

function removePendingDeleteId(state: RunsPageState, runId: number) {
  const pendingDeleteIds = new Set(state.pendingDeleteIds);
  pendingDeleteIds.delete(runId);
  return pendingDeleteIds;
}

const runsPageHandlers = {
  domainFilterChanged: (
    state: RunsPageState,
    action: Extract<RunsPageAction, { type: 'domainFilterChanged' }>,
  ) => ({ ...state, domainFilter: action.value }),
  statusFilterChanged: (
    state: RunsPageState,
    action: Extract<RunsPageAction, { type: 'statusFilterChanged' }>,
  ) => ({ ...state, statusFilter: action.value }),
  filtersApplied: (state: RunsPageState) => ({
    ...state,
    appliedDomainFilter: state.domainFilter.trim(),
    appliedStatusFilter: state.statusFilter,
  }),
  filtersReset: (state: RunsPageState) => ({
    ...state,
    domainFilter: '',
    statusFilter: '',
    appliedDomainFilter: '',
    appliedStatusFilter: '',
  }),
  deleteStarted: (
    state: RunsPageState,
    action: Extract<RunsPageAction, { type: 'deleteStarted' }>,
  ) => ({
    ...state,
    pendingDeleteIds: addPendingDeleteId(state, action.runId),
    actionError: '',
  }),
  deleteSucceeded: (state: RunsPageState) => ({ ...state, actionError: '', deleteTarget: null }),
  deleteFailed: (
    state: RunsPageState,
    action: Extract<RunsPageAction, { type: 'deleteFailed' }>,
  ) => ({ ...state, actionError: action.message }),
  deleteSettled: (
    state: RunsPageState,
    action: Extract<RunsPageAction, { type: 'deleteSettled' }>,
  ) => ({ ...state, pendingDeleteIds: removePendingDeleteId(state, action.runId) }),
  deleteRequested: (
    state: RunsPageState,
    action: Extract<RunsPageAction, { type: 'deleteRequested' }>,
  ) => ({ ...state, deleteTarget: action.run }),
  deleteDialogClosed: (state: RunsPageState) => ({ ...state, deleteTarget: null }),
} satisfies {
  [K in RunsPageAction['type']]: (
    state: RunsPageState,
    action: Extract<RunsPageAction, { type: K }>,
  ) => RunsPageState;
};

function runsPageReducer(state: RunsPageState, action: RunsPageAction): RunsPageState {
  const handler = runsPageHandlers[action.type] as (
    currentState: RunsPageState,
    currentAction: RunsPageAction,
  ) => RunsPageState;
  return handler(state, action);
}

export function useRunsPageState() {
  const [state, dispatch] = useReducer(runsPageReducer, initialRunsPageState);
  return { state, dispatch };
}
