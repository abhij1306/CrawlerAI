/// <reference types="vite-plus/client" />

type RuntimeEnv = {
  readonly VITE_API_BASE_URL?: string;
  readonly NODE_ENV?: string;
};

interface ImportMetaEnv extends RuntimeEnv {}

interface ImportMeta {
  readonly env: ImportMetaEnv;
}
