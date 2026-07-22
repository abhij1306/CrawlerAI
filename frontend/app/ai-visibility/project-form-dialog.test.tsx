import { fireEvent, render, screen } from '@testing-library/react';
import { beforeEach, describe, expect, it, vi } from 'vite-plus/test';

import type { AiVisibilityProjectCreate } from '../../lib/api/ai-visibility';
import { ProjectFormDialog, formToPayload, presetToForm } from './project-form-dialog';

const PRESET: AiVisibilityProjectCreate = {
  name: 'Best&Less AI Visibility',
  brand_name: 'Best&Less',
  brand_aliases: ['Best & Less', 'Best and Less'],
  owned_domains: ['bestandless.com.au'],
  unintended_domains: ['bestandless.zendesk.com'],
  competitors: [{ name: 'Kmart', aliases: ['Kmart Australia'], domains: ['kmart.com.au'] }],
  country_code: 'AU',
  language_code: 'en-AU',
  benchmark_mode: 'controlled_localized',
  prompts: [
    { text: 'best kids clothes australia', theme: 'kids', intent: 'purchase' },
    { text: 'cheap school uniforms', theme: undefined, intent: undefined },
  ],
  default_repetitions: 5,
};

function renderDialog(overrides: Partial<Parameters<typeof ProjectFormDialog>[0]> = {}) {
  const props = {
    open: true,
    onOpenChange: vi.fn(),
    preset: undefined,
    pending: false,
    onSubmit: vi.fn(),
    ...overrides,
  };
  render(<ProjectFormDialog {...props} />);
  return props;
}

describe('formToPayload / presetToForm', () => {
  it('round-trips a preset through the form model', () => {
    expect(formToPayload(presetToForm(PRESET))).toEqual({
      name: 'Best&Less AI Visibility',
      brand_name: 'Best&Less',
      brand_aliases: ['Best & Less', 'Best and Less'],
      owned_domains: ['bestandless.com.au'],
      unintended_domains: ['bestandless.zendesk.com'],
      competitors: [{ name: 'Kmart', aliases: ['Kmart Australia'], domains: ['kmart.com.au'] }],
      country_code: 'AU',
      language_code: 'en-AU',
      benchmark_mode: 'controlled_localized',
      prompts: [
        { text: 'best kids clothes australia', theme: 'kids', intent: 'purchase' },
        { text: 'cheap school uniforms', theme: undefined, intent: undefined },
      ],
      default_repetitions: 5,
    });
  });

  it('drops blank prompt/competitor rows and applies defaults', () => {
    const form = presetToForm(PRESET);
    const payload = formToPayload({
      ...form,
      name: '  My Project  ',
      country_code: ' ',
      language_code: '',
      default_repetitions: 0,
      prompts: [{ text: '   ', theme: '', intent: '' }],
      competitors: [{ name: ' ', aliases: '', domains: '' }],
    });
    expect(payload.name).toBe('My Project');
    expect(payload.country_code).toBe('AU');
    expect(payload.language_code).toBe('en');
    expect(payload.default_repetitions).toBe(1);
    expect(payload.prompts).toEqual([]);
    expect(payload.competitors).toEqual([]);
  });
});

describe('ProjectFormDialog', () => {
  beforeEach(() => {
    vi.clearAllMocks();
  });

  it('keeps submit disabled until name and brand are filled, then submits the mapped payload', () => {
    const { onSubmit } = renderDialog();

    const submit = screen.getByRole('button', { name: 'Create Project' });
    expect(submit).toBeDisabled();

    fireEvent.change(screen.getByLabelText('Project name'), { target: { value: 'My Domain' } });
    expect(submit).toBeDisabled();

    fireEvent.change(screen.getByLabelText('Brand name'), { target: { value: 'My Brand' } });
    expect(submit).toBeEnabled();

    fireEvent.change(screen.getByPlaceholderText('Best & Less, Best and Less'), {
      target: { value: 'Alias One, Alias Two' },
    });
    fireEvent.change(screen.getByPlaceholderText('bestandless.com.au'), {
      target: { value: 'example.com, shop.example.com' },
    });
    fireEvent.change(screen.getByPlaceholderText('prompt text'), {
      target: { value: 'best running shoes' },
    });

    fireEvent.click(submit);

    expect(onSubmit).toHaveBeenCalledWith({
      name: 'My Domain',
      brand_name: 'My Brand',
      brand_aliases: ['Alias One', 'Alias Two'],
      owned_domains: ['example.com', 'shop.example.com'],
      unintended_domains: [],
      competitors: [],
      country_code: 'AU',
      language_code: 'en-AU',
      benchmark_mode: 'controlled_localized',
      prompts: [{ text: 'best running shoes', theme: undefined, intent: undefined }],
      default_repetitions: 3,
    });
  });

  it('prefills the form from the sample preset', () => {
    const { onSubmit } = renderDialog({ preset: PRESET });

    fireEvent.click(screen.getByRole('button', { name: 'Prefill sample' }));

    expect(screen.getByLabelText('Project name')).toHaveValue('Best&Less AI Visibility');
    expect(screen.getByLabelText('Brand name')).toHaveValue('Best&Less');
    expect(screen.getByDisplayValue('best kids clothes australia')).toBeInTheDocument();
    expect(screen.getByDisplayValue('Kmart')).toBeInTheDocument();

    fireEvent.click(screen.getByRole('button', { name: 'Create Project' }));
    expect(onSubmit).toHaveBeenCalledWith(
      expect.objectContaining({
        name: 'Best&Less AI Visibility',
        default_repetitions: 5,
      }),
    );
  });

  it('resets the form every time the dialog is opened', () => {
    const props = {
      open: true,
      onOpenChange: vi.fn(),
      preset: undefined,
      pending: false,
      onSubmit: vi.fn(),
    };
    const { rerender } = render(<ProjectFormDialog {...props} />);

    fireEvent.change(screen.getByLabelText('Project name'), { target: { value: 'Typed name' } });
    rerender(<ProjectFormDialog {...props} open={false} />);
    rerender(<ProjectFormDialog {...props} open />);

    expect(screen.getByLabelText('Project name')).toHaveValue('');
  });

  it('adds and removes prompt rows', () => {
    renderDialog();

    expect(screen.getAllByPlaceholderText('prompt text')).toHaveLength(1);
    expect(screen.getByRole('button', { name: 'Remove prompt' })).toBeDisabled();

    fireEvent.click(screen.getByRole('button', { name: '+ Add prompt' }));
    expect(screen.getAllByPlaceholderText('prompt text')).toHaveLength(2);

    fireEvent.click(screen.getAllByRole('button', { name: 'Remove prompt' })[1]);
    expect(screen.getAllByPlaceholderText('prompt text')).toHaveLength(1);
  });
});
