import type { ComponentType } from 'react';
import type { LucideIcon } from 'lucide-react';
import {
  BrainCircuit,
  BriefcaseBusiness,
  Clock3,
  DatabaseZap,
  FileChartColumn,
  Grid2x2,
  Settings2,
  ShieldCheck,
  WandSparkles,
} from 'lucide-react';
import { matchPath } from 'react-router-dom';

export type RouteAccess = 'public' | 'authenticated' | 'admin';
export type RouteModule = { default: ComponentType };

export type AppRoute = {
  id: string;
  path: string;
  access: RouteAccess;
  lazy: () => Promise<RouteModule>;
  metadata: { title: string; description?: string };
  nav?: {
    group: 'Primary' | 'Intelligence' | 'Admin';
    label: string;
    icon: LucideIcon;
    exact?: boolean;
  };
};

export const appRoutes: readonly AppRoute[] = [
  {
    id: 'login',
    path: '/login',
    access: 'public',
    lazy: () => import('../../app/login/page-view'),
    metadata: { title: 'Sign in' },
  },
  {
    id: 'register',
    path: '/register',
    access: 'public',
    lazy: () => import('../../app/register/page-view'),
    metadata: { title: 'Register' },
  },
  {
    id: 'dashboard',
    path: '/dashboard',
    access: 'authenticated',
    lazy: () => import('../../app/dashboard/page-view'),
    metadata: {
      title: 'Dashboard',
      description: 'Overview of crawler activity across your workspace.',
    },
    nav: { group: 'Primary', label: 'Dashboard', icon: Grid2x2 },
  },
  {
    id: 'crawl',
    path: '/crawl',
    access: 'authenticated',
    lazy: () => import('../../app/crawl/page-view'),
    metadata: {
      title: 'Crawl Studio',
      description: 'Configure sources, run jobs, and monitor execution.',
    },
    nav: { group: 'Primary', label: 'Crawl Studio', icon: WandSparkles },
  },
  {
    id: 'runs',
    path: '/runs',
    access: 'authenticated',
    lazy: () => import('../../app/runs/page-view'),
    metadata: {
      title: 'Run History',
      description: 'Review and manage previously submitted crawls.',
    },
    nav: { group: 'Primary', label: 'History', icon: Clock3 },
  },
  {
    id: 'jobs',
    path: '/jobs',
    access: 'authenticated',
    lazy: () => import('../../app/jobs/page-view'),
    metadata: { title: 'Jobs', description: 'Review worker activity and queued work.' },
    nav: { group: 'Primary', label: 'Jobs', icon: BriefcaseBusiness },
  },
  {
    id: 'data-enrichment',
    path: '/data-enrichment',
    access: 'authenticated',
    lazy: () => import('../../app/data-enrichment/page-view'),
    metadata: {
      title: 'Data Enrichment',
      description: 'Normalize ecommerce detail records into discovery fields.',
    },
    nav: { group: 'Intelligence', label: 'Data Enrichment', icon: FileChartColumn },
  },
  {
    id: 'product-intelligence',
    path: '/product-intelligence',
    access: 'authenticated',
    lazy: () => import('../../app/product-intelligence/page-view'),
    metadata: {
      title: 'Product Intelligence',
      description: 'Find matching product pages and compare prices.',
    },
    nav: { group: 'Intelligence', label: 'Product Intelligence', icon: BrainCircuit },
  },
  {
    id: 'ai-visibility',
    path: '/ai-visibility',
    access: 'authenticated',
    lazy: () => import('../../app/ai-visibility/page-view'),
    metadata: {
      title: 'AI Visibility',
      description: 'Benchmark brand mentions and owned-domain citations in AI-grounded search.',
    },
    nav: { group: 'Intelligence', label: 'AI Visibility', icon: BrainCircuit },
  },
  {
    id: 'domain-memory',
    path: '/domain-memory',
    access: 'authenticated',
    lazy: () => import('../../app/domain-memory/page-view'),
    metadata: {
      title: 'Domain Memory',
      description: 'Inspect run profiles, grounded learning, and extraction contracts by domain.',
    },
    nav: { group: 'Intelligence', label: 'Domain Memory', icon: DatabaseZap },
  },
  {
    id: 'admin-users',
    path: '/admin/users',
    access: 'admin',
    lazy: () => import('../../app/admin/users/page-view'),
    metadata: { title: 'Users', description: 'Manage workspace access and roles.' },
    nav: { group: 'Admin', label: 'Users', icon: ShieldCheck },
  },
  {
    id: 'admin-llm',
    path: '/admin/llm',
    access: 'admin',
    lazy: () => import('../../app/admin/llm/page-view'),
    metadata: { title: 'LLM Config', description: 'Control provider settings and prompts.' },
    nav: { group: 'Admin', label: 'LLM Config', icon: Settings2 },
  },
];

const groupOrder = ['Primary', 'Intelligence', 'Admin'] as const;

export const navGroups = groupOrder.map((label) => ({
  label,
  items: appRoutes.filter((route) => route.nav?.group === label),
}));

export function routeMetadataForPath(pathname: string) {
  const route = appRoutes.find((candidate) =>
    matchPath({ path: candidate.path, end: candidate.nav?.exact ?? false }, pathname),
  );
  return route?.metadata ?? { title: 'CrawlerAI' };
}
