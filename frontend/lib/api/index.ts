import { adminApi } from './admin';
import { authApi } from './auth';
import { crawlsApi } from './crawls';
import { dashboardApi } from './dashboard';
import { dataEnrichmentApi } from './data-enrichment';
import { domainMemoryApi } from './domain-memory';
import { jobsApi } from './jobs';
import { knowledgeApi } from './knowledge';
import { productIntelligenceApi } from './product-intelligence';
import { selectorsApi } from './selectors';

export const api = {
  ...authApi,
  ...dashboardApi,
  ...crawlsApi,
  ...productIntelligenceApi,
  ...dataEnrichmentApi,
  ...domainMemoryApi,
  ...adminApi,
  ...selectorsApi,
  ...knowledgeApi,
  ...jobsApi,
};
