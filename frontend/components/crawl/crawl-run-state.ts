export type RecipeActionPendingKey = `field:${string}:${'keep' | 'reject'}`;
export type RunActionPendingKey = 'kill';

export type CrawlRunLocalState = {
  recipeActionPending: RecipeActionPendingKey | null;
  recipeActionError: string;
  runActionPending: RunActionPendingKey | null;
  runActionError: string;
  sessionStartMs: number;
};

export type CrawlRunLocalAction =
  | { type: 'recipeStarted'; pendingKey: RecipeActionPendingKey }
  | { type: 'recipeFailed'; message: string }
  | { type: 'recipeFinished' }
  | { type: 'runActionStarted'; pendingKey: RunActionPendingKey }
  | { type: 'runActionErrorCleared' }
  | { type: 'runActionFailed'; message: string }
  | { type: 'runActionFinished' };

export function buildInitialCrawlRunLocalState(): CrawlRunLocalState {
  return {
    recipeActionPending: null,
    recipeActionError: '',
    runActionPending: null,
    runActionError: '',
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
  }
}
