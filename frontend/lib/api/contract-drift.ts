import { readFileSync } from 'node:fs';
import { z } from 'zod';

import {
  crawlRecordSchema,
  crawlRunSchema,
  domainRunProfileSchema,
  runEventSchema,
  userSchema,
} from './schemas';

const contractSchemas = {
  userSchema,
  crawlRunSchema,
  crawlRecordSchema,
  runEventSchema,
  domainRunProfileSchema,
};

const CONTRACT_SCHEMA_MAP = {
  userSchema: 'UserResponse',
  crawlRunSchema: 'CrawlRunResponse',
  crawlRecordSchema: 'CrawlRecordResponse',
  runEventSchema: 'RunEventResponse',
  domainRunProfileSchema: 'DomainRunProfilePayload',
} as const;

type ContractSchemaName = keyof typeof CONTRACT_SCHEMA_MAP;

type OpenApiSchema = {
  properties?: Record<string, unknown>;
  required?: string[];
  allOf?: OpenApiSchema[];
  $ref?: string;
};

export type OpenApiSpec = {
  components?: { schemas?: Record<string, OpenApiSchema> };
};

function unwrapToObject(schema: unknown): z.ZodObject | null {
  let current = schema;
  for (let depth = 0; depth < 8; depth += 1) {
    if (current instanceof z.ZodObject) return current;
    if (
      current instanceof z.ZodDefault ||
      current instanceof z.ZodOptional ||
      current instanceof z.ZodNullable ||
      current instanceof z.ZodReadonly
    ) {
      current = current.unwrap();
      continue;
    }
    if (current instanceof z.ZodArray) {
      current = current.element;
      continue;
    }
    return null;
  }
  return null;
}

function toleratesAbsent(schema: unknown): boolean {
  let current: unknown = schema;
  for (let depth = 0; depth < 4; depth += 1) {
    if (current instanceof z.ZodOptional || current instanceof z.ZodDefault) return true;
    if (current instanceof z.ZodNullable || current instanceof z.ZodReadonly) {
      current = current.unwrap();
      continue;
    }
    return false;
  }
  return false;
}

export function declaredKeysFor(name: ContractSchemaName): {
  declared: string[];
  required: string[];
} | null {
  const objectSchema = unwrapToObject(contractSchemas[name]);
  if (!objectSchema) return null;
  const declared = Object.keys(objectSchema.shape);
  const required = declared.filter((key) => !toleratesAbsent(objectSchema.shape[key]));
  return { declared, required };
}

type ResolvedComponent = {
  properties: Set<string>;
  required: Set<string>;
};

function resolveComponent(spec: OpenApiSpec, componentName: string): ResolvedComponent | null {
  const components = spec.components?.schemas ?? {};
  const root = components[componentName];
  if (!root) return null;
  const properties = new Set<string>();
  const required = new Set<string>();
  const visit = (schema: OpenApiSchema, seen: Set<string>) => {
    if (schema.$ref) {
      const prefix = '#/components/schemas/';
      const name = schema.$ref.startsWith(prefix) ? schema.$ref.slice(prefix.length) : null;
      const target = name ? components[name] : undefined;
      if (name && target && !seen.has(name)) {
        seen.add(name);
        visit(target, seen);
      }
      return;
    }
    for (const key of Object.keys(schema.properties ?? {})) properties.add(key);
    for (const key of schema.required ?? []) required.add(key);
    for (const branch of schema.allOf ?? []) visit(branch, seen);
  };
  visit(root, new Set([componentName]));
  return { properties, required };
}

export function componentProperties(spec: OpenApiSpec, componentName: string): Set<string> | null {
  return resolveComponent(spec, componentName)?.properties ?? null;
}

export function diffContract(spec: OpenApiSpec): { failures: string[]; warnings: string[] } {
  const failures: string[] = [];
  const warnings: string[] = [];
  for (const [schemaName, componentName] of Object.entries(CONTRACT_SCHEMA_MAP) as [
    ContractSchemaName,
    string,
  ][]) {
    const keys = declaredKeysFor(schemaName);
    const resolved = resolveComponent(spec, componentName);
    if (!keys || !resolved) {
      failures.push(`${schemaName}: unresolved OpenAPI mapping '${componentName}'`);
      continue;
    }
    const missing = keys.required.filter(
      (key) => !resolved.properties.has(key) || !resolved.required.has(key),
    );
    const declared = new Set(keys.declared);
    const additive = [...resolved.properties].filter((key) => !declared.has(key)).sort();
    if (missing.length > 0) {
      failures.push(`${schemaName}: backend '${componentName}' is missing ${missing.join(', ')}`);
    }
    if (additive.length > 0) {
      warnings.push(`${schemaName}: backend adds ${additive.join(', ')}`);
    }
  }
  return { failures, warnings };
}

export function readOpenApiFromEnvironment(env = process.env): OpenApiSpec | null {
  const path = env.CRAWLERAI_OPENAPI_JSON;
  if (!path) return null;
  return JSON.parse(readFileSync(path, 'utf8')) as OpenApiSpec;
}

export function contractGuardIsStrict(env = process.env): boolean {
  return env.CRAWLERAI_CONTRACT_STRICT === '1';
}
