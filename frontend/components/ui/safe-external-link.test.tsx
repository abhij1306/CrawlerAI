import { render, screen } from '@testing-library/react';
import { describe, expect, it } from 'vite-plus/test';

import { SafeExternalLink } from './safe-external-link';

describe('SafeExternalLink', () => {
  it('renders an anchor for https URLs', () => {
    render(
      <SafeExternalLink href="https://example.com/product" className="link-accent">
        Example
      </SafeExternalLink>,
    );
    const link = screen.getByRole('link', { name: 'Example' });
    expect(link).toHaveAttribute('href', 'https://example.com/product');
    expect(link).toHaveAttribute('target', '_blank');
    expect(link).toHaveAttribute('rel', 'noopener noreferrer');
    expect(link).toHaveClass('link-accent');
  });

  it('renders an anchor for http URLs', () => {
    render(<SafeExternalLink href="http://example.com">Example</SafeExternalLink>);
    expect(screen.getByRole('link', { name: 'Example' })).toHaveAttribute(
      'href',
      'http://example.com',
    );
  });

  it.each([
    'javascript:alert(1)',
    'data:text/html,<script>alert(1)</script>',
    'vbscript:msgbox(1)',
  ])('renders muted plain text instead of an anchor for %s', (href) => {
    render(
      <SafeExternalLink href={href} className="text-accent">
        evil link
      </SafeExternalLink>,
    );
    expect(screen.queryByRole('link')).not.toBeInTheDocument();
    const text = screen.getByText('evil link');
    expect(text.tagName).toBe('SPAN');
    expect(text).not.toHaveAttribute('href');
    expect(text).toHaveClass('text-muted');
  });

  it('renders muted plain text for malformed URLs', () => {
    render(<SafeExternalLink href="not a url">broken</SafeExternalLink>);
    expect(screen.queryByRole('link')).not.toBeInTheDocument();
    expect(screen.getByText('broken')).toHaveClass('text-muted');
  });

  it('preserves title and aria-label on both render paths', () => {
    const { rerender } = render(
      <SafeExternalLink href="https://example.com" title="Open original URL" ariaLabel="Open">
        <span>icon</span>
      </SafeExternalLink>,
    );
    expect(screen.getByRole('link', { name: 'Open' })).toHaveAttribute(
      'title',
      'Open original URL',
    );

    rerender(
      <SafeExternalLink href="javascript:alert(1)" title="Open original URL" ariaLabel="Open">
        <span>icon</span>
      </SafeExternalLink>,
    );
    expect(screen.queryByRole('link')).not.toBeInTheDocument();
    expect(screen.getByLabelText('Open')).toHaveAttribute('title', 'Open original URL');
  });
});
