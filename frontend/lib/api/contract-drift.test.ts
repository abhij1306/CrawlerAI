import { describe, expect, it } from 'vite-plus/test';

import {
  componentProperties,
  contractGuardIsStrict,
  declaredKeysFor,
  diffContract,
  readOpenApiFromEnvironment,
  type OpenApiSpec,
} from './contract-drift';

describe('contract drift helpers', () => {
  it('resolves OpenAPI refs and merged properties', () => {
    const spec: OpenApiSpec = {
      components: {
        schemas: {
          Base: { properties: { id: {} } },
          Child: {
            allOf: [{ $ref: '#/components/schemas/Base' }, { properties: { name: {} } }],
          },
        },
      },
    };
    expect([...(componentProperties(spec, 'Child') ?? [])].sort()).toEqual(['id', 'name']);
  });

  it('distinguishes required and absent-tolerant fields', () => {
    const keys = declaredKeysFor('crawlRunSchema');
    expect(keys?.required).toContain('id');
    expect(keys?.required).not.toContain('run_health');
  });

  it('fails on required frontend fields missing from the backend', () => {
    const result = diffContract({
      components: {
        schemas: {
          UserResponse: { properties: {} },
          CrawlRunResponse: { properties: {} },
          CrawlRecordResponse: { properties: {} },
          RunEventResponse: { properties: {} },
          DomainRunProfilePayload: { properties: {} },
        },
      },
    });
    expect(result.failures.length).toBeGreaterThan(0);
  });

  it('fails when an inherited backend property is not required', () => {
    const components: NonNullable<NonNullable<OpenApiSpec['components']>['schemas']> = {};
    const mappings = {
      userSchema: 'UserResponse',
      crawlRunSchema: 'CrawlRunResponse',
      crawlRecordSchema: 'CrawlRecordResponse',
      runEventSchema: 'RunEventResponse',
      domainRunProfileSchema: 'DomainRunProfilePayload',
    } as const;
    for (const [schemaName, componentName] of Object.entries(mappings)) {
      const keys = declaredKeysFor(schemaName as keyof typeof mappings);
      components[componentName] = {
        properties: Object.fromEntries((keys?.declared ?? []).map((key) => [key, {}])),
        required: keys?.required ?? [],
      };
    }
    const user = components.UserResponse as {
      properties: Record<string, unknown>;
      required: string[];
    };
    components.UserBase = { ...user, required: user.required.filter((key) => key !== 'email') };
    components.UserResponse = { allOf: [{ $ref: '#/components/schemas/UserBase' }] };

    const result = diffContract({ components: { schemas: components } });

    expect(result.failures).toContain("userSchema: backend 'UserResponse' is missing email");
  });
});

describe('backend contract drift guard', () => {
  it('matches the exported backend OpenAPI response models', () => {
    const spec = readOpenApiFromEnvironment();
    if (!spec) {
      if (contractGuardIsStrict()) throw new Error('CRAWLERAI_OPENAPI_JSON is required');
      return;
    }
    const result = diffContract(spec);
    for (const warning of result.warnings) console.warn(`[contract-drift] ${warning}`);
    expect(result.failures).toEqual([]);
  });
});
