import { zodResolver } from '@hookform/resolvers/zod';
import { useCallback } from 'react';
import { useFieldArray, useForm, useWatch } from 'react-hook-form';
import { z } from 'zod';

import { CRAWL_DEFAULTS, CRAWL_LIMITS } from '../../lib/constants/crawl-defaults';
import type { FieldRow } from './shared';
import { parseLines } from './shared';

export type CrawlConfigFormValues = {
  targetUrl: string;
  bulkUrls: string;
  maxRecords: string;
  proxyInput: string;
  fieldRows: FieldRow[];
};

const httpUrlSchema = z
  .string()
  .trim()
  .url('Must be a valid URL.')
  .refine(
    (value) => {
      try {
        const protocol = new URL(value).protocol;
        return protocol === 'http:' || protocol === 'https:';
      } catch {
        return false;
      }
    },
    { message: 'Must be a valid URL.' },
  );

const validationStateSchema = z.enum(['idle', 'valid', 'invalid']);
const fieldRowSchema = z.object({
  id: z.string(),
  fieldName: z.string(),
  cssSelector: z.string(),
  xpath: z.string(),
  regex: z.string(),
  cssState: validationStateSchema,
  xpathState: validationStateSchema,
  regexState: validationStateSchema,
}) satisfies z.ZodType<FieldRow>;

const baseCrawlConfigSchema = {
  targetUrl: z.string(),
  bulkUrls: z.string(),
  maxRecords: z.string(),
};

type CrawlConfigSubmissionInput = Readonly<{
  mode: string;
  targetUrl: string;
  bulkUrls: string;
  maxRecords: string;
}>;

export const crawlConfigSchema = z
  .object({
    mode: z.string(),
    target_url: baseCrawlConfigSchema.targetUrl,
    bulk_urls: baseCrawlConfigSchema.bulkUrls,
    max_records: z.coerce
      .number()
      .min(CRAWL_LIMITS.MIN_RECORDS, `Max records must be at least ${CRAWL_LIMITS.MIN_RECORDS}.`)
      .max(CRAWL_LIMITS.MAX_RECORDS, `Max records must be ${CRAWL_LIMITS.MAX_RECORDS} or less.`),
  })
  .superRefine((config, context) => {
    if (config.mode === 'single') {
      const result = httpUrlSchema.safeParse(config.target_url);
      if (!result.success) {
        context.addIssue({
          code: 'custom',
          path: ['target_url'],
          message: result.error.issues[0]?.message ?? 'Must be a valid URL.',
        });
      }
    }
    if (config.mode === 'bulk' || config.mode === 'batch') {
      const urls = parseLines(config.bulk_urls);
      if (!urls.length) {
        context.addIssue({
          code: 'custom',
          path: ['bulk_urls'],
          message: 'Batch crawl needs at least one URL.',
        });
        return;
      }
      for (const url of urls) {
        const result = httpUrlSchema.safeParse(url);
        if (!result.success) {
          context.addIssue({
            code: 'custom',
            path: ['bulk_urls'],
            message: 'Every URL must be valid.',
          });
          return;
        }
      }
    }
  });

export function transformFormToSubmission(config: CrawlConfigSubmissionInput) {
  return {
    mode: config.mode,
    target_url: config.targetUrl,
    bulk_urls: config.bulkUrls,
    max_records: config.maxRecords,
  };
}

const crawlConfigFormSchema = z.object({
  ...baseCrawlConfigSchema,
  proxyInput: z.string(),
  fieldRows: z.array(fieldRowSchema),
});

export function createManualFieldRowId() {
  if (typeof crypto !== 'undefined' && typeof crypto.randomUUID === 'function') {
    return crypto.randomUUID();
  }
  return `manual-${Math.random().toString(36).slice(2)}`;
}

export function useCrawlConfig() {
  const form = useForm<CrawlConfigFormValues>({
    resolver: zodResolver(crawlConfigFormSchema),
    defaultValues: {
      targetUrl: '',
      bulkUrls: '',
      maxRecords: String(CRAWL_DEFAULTS.MAX_RECORDS),
      proxyInput: '',
      fieldRows: [],
    },
  });
  const { fields: fieldRows, replace: replaceFieldRows } = useFieldArray({
    control: form.control,
    name: 'fieldRows',
    keyName: 'formKey',
  });
  const targetUrl = useWatch({ control: form.control, name: 'targetUrl' });
  const bulkUrls = useWatch({ control: form.control, name: 'bulkUrls' });
  const maxRecords = useWatch({ control: form.control, name: 'maxRecords' });
  const proxyInput = useWatch({ control: form.control, name: 'proxyInput' });
  const setFieldRows = useCallback(
    (next: FieldRow[] | ((current: FieldRow[]) => FieldRow[])) => {
      const current = form.getValues('fieldRows');
      replaceFieldRows(typeof next === 'function' ? next(current) : next);
    },
    [form, replaceFieldRows],
  );

  return {
    ...form,
    fieldRows,
    setFieldRows,
    targetUrl,
    bulkUrls,
    maxRecords,
    proxyInput,
    isSubmitting: form.formState.isSubmitting,
  };
}
