import type { Metadata } from 'next';

import PageAuditPage from './page-audit-page';

export const metadata: Metadata = {
  title: 'Page Technical Audit',
  description: 'Audit source HTML, rendered DOM, and crawler-visible differences.',
};

export default PageAuditPage;
