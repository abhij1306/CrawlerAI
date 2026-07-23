import { render, screen } from '@testing-library/react';
import { describe, expect, it } from 'vite-plus/test';

import { ExternalCandidateImage } from './product-intelligence-components';

describe('ExternalCandidateImage', () => {
  it('renders https images with a no-referrer policy', () => {
    render(
      <ExternalCandidateImage
        src="https://cdn.example.com/product.png"
        alt="Candidate product"
        className="h-full w-full"
      />,
    );
    const image = screen.getByRole('img', { name: 'Candidate product' });
    expect(image).toHaveAttribute('src', 'https://cdn.example.com/product.png');
    expect(image).toHaveAttribute('referrerpolicy', 'no-referrer');
    expect(image).toHaveAttribute('loading', 'lazy');
  });

  it('renders http images', () => {
    render(<ExternalCandidateImage src="http://example.com/p.png" alt="Candidate" className="" />);
    expect(screen.getByRole('img', { name: 'Candidate' })).toBeInTheDocument();
  });

  it.each(['javascript:alert(1)', 'data:image/png;base64,iVBORw0KGgo=', ''])(
    'renders nothing for unsafe src %j',
    (src) => {
      const { container } = render(
        <ExternalCandidateImage src={src} alt="Candidate product" className="h-full" />,
      );
      expect(container.querySelector('img')).toBeNull();
    },
  );
});
