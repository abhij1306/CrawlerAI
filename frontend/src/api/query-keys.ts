type RunListFilters = Readonly<Record<string, string | number | boolean | null | undefined>>;

type SelectorFilters = {
  domain?: string;
  surface?: string;
};

export const queryKeys = {
  auth: {
    all: ['auth'] as const,
    me: () => ['auth', 'me'] as const,
  },
  dashboard: () => ['dashboard'] as const,
  runs: {
    all: ['runs'] as const,
    list: (filters: RunListFilters = {}) => ['runs', 'list', filters] as const,
    detail: (runId: number) => ['runs', 'detail', runId] as const,
    records: (runId: number) => ['runs', 'records', runId] as const,
    tableRecords: (runId: number, pageSize: number) =>
      ['runs', 'records', runId, 'table-pages', pageSize] as const,
    jsonRecords: (runId: number, pageSize: number) =>
      ['runs', 'records', runId, 'json-pages', pageSize] as const,
    logs: (runId: number) => ['runs', 'logs', runId] as const,
    recipe: (runId: number) => ['runs', 'recipe', runId] as const,
    terminalRecordSync: (syncKey: string | null) =>
      ['runs', 'terminal-record-sync', syncKey] as const,
  },
  jobs: {
    all: ['jobs'] as const,
    active: () => ['jobs', 'active'] as const,
  },
  selectors: {
    all: ['selectors'] as const,
    list: ({ domain = '', surface = '' }: SelectorFilters = {}) =>
      ['selectors', 'list', domain, surface] as const,
  },
  domainRunProfiles: {
    all: ['domain-run-profiles'] as const,
    detail: (domain: string, surface: string) =>
      ['domain-run-profiles', 'detail', domain, surface] as const,
  },
  domainMemory: {
    all: ['domain-memory'] as const,
    domains: () => ['domain-memory', 'domains'] as const,
    workspace: (domain: string) => ['domain-memory', 'workspace', domain] as const,
    extraction: (domain: string) => ['domain-memory', 'extraction', domain] as const,
    cookieMemory: () => ['domain-memory', 'cookie-memory'] as const,
    fieldFeedback: (limit: number) => ['domain-memory', 'field-feedback', limit] as const,
  },
  knowledgeGraph: {
    all: ['knowledge-graph'] as const,
    domain: (domain: string) => ['knowledge-graph', 'domain', domain] as const,
    sites: () => ['knowledge-graph', 'sites'] as const,
  },
  diagnostics: {
    all: ['diagnostics'] as const,
    report: (runId: number) => ['diagnostics', 'report', runId] as const,
    result: (runId: number, urlResultId: number) =>
      ['diagnostics', 'result', runId, urlResultId] as const,
  },
  productIntelligence: {
    all: ['product-intelligence'] as const,
    jobs: () => ['product-intelligence', 'jobs'] as const,
    detail: (jobId: number) => ['product-intelligence', 'detail', jobId] as const,
  },
  dataEnrichment: {
    all: ['data-enrichment'] as const,
    jobs: () => ['data-enrichment', 'jobs'] as const,
    detail: (jobId: number) => ['data-enrichment', 'detail', jobId] as const,
  },
  admin: {
    users: (filters: RunListFilters = {}) => ['admin', 'users', filters] as const,
    llmProviders: () => ['admin', 'llm', 'providers'] as const,
    llmConfigs: () => ['admin', 'llm', 'configs'] as const,
    llmCosts: () => ['admin', 'llm', 'costs'] as const,
  },
} as const;
