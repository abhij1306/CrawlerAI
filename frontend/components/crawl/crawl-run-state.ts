import type { CrawlLog } from '../../lib/api/types';
import { mergeLogs } from './shared';

export type RecipeActionPendingKey = `field:${string}:${'keep' | 'reject'}`;
export type RunActionPendingKey = 'kill';

export type CrawlRunLocalState = {
  recipeActionPending: RecipeActionPendingKey | null;
  recipeActionError: string;
  liveJumpAvailable: boolean;
  runActionPending: RunActionPendingKey | null;
  runActionError: string;
  socketLogItems: CrawlLog[];
  logSocketConnected: boolean;
  sessionStartMs: number;
};

export type CrawlRunLocalAction =
  | { type: 'recipeStarted'; pendingKey: RecipeActionPendingKey }
  | { type: 'recipeFailed'; message: string }
  | { type: 'recipeFinished' }
  | { type: 'runActionStarted'; pendingKey: RunActionPendingKey }
  | { type: 'runActionErrorCleared' }
  | { type: 'runActionFailed'; message: string }
  | { type: 'runActionFinished' }
  | { type: 'runChanged'; sessionStartMs: number }
  | { type: 'liveJumpChanged'; available: boolean }
  | { type: 'logSocketConnectionChanged'; connected: boolean }
  | { type: 'socketLogReceived'; log: CrawlLog };

export function buildInitialCrawlRunLocalState(): CrawlRunLocalState {
  return {
    recipeActionPending: null,
    recipeActionError: '',
    liveJumpAvailable: false,
    runActionPending: null,
    runActionError: '',
    socketLogItems: [],
    logSocketConnected: false,
    sessionStartMs: Date.now(),
  };
}

export function crawlRunLocalReducer(
  state: CrawlRunLocalState,
  action: CrawlRunLocalAction,
): CrawlRunLocalState {
  switch (action.type) {
    case 'recipeStarted':
      return { ...state, recipeActionPending: action.pendingKey, recipeActionError: '' };
    case 'recipeFailed':
      return { ...state, recipeActionError: action.message };
    case 'recipeFinished':
      return { ...state, recipeActionPending: null };
    case 'runActionStarted':
      return { ...state, runActionPending: action.pendingKey, runActionError: '' };
    case 'runActionErrorCleared':
      return { ...state, runActionError: '' };
    case 'runActionFailed':
      return { ...state, runActionError: action.message };
    case 'runActionFinished':
      return { ...state, runActionPending: null };
    case 'runChanged':
      return {
        ...state,
        liveJumpAvailable: false,
        socketLogItems: [],
        logSocketConnected: false,
        sessionStartMs: action.sessionStartMs,
      };
    case 'liveJumpChanged':
      return { ...state, liveJumpAvailable: action.available };
    case 'logSocketConnectionChanged':
      return { ...state, logSocketConnected: action.connected };
    case 'socketLogReceived':
      return { ...state, socketLogItems: mergeLogs(state.socketLogItems, [action.log]) };
  }
}
