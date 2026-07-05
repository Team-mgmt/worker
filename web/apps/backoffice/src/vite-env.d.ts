/// <reference types="vite/client" />
/// <reference types="vite-plugin-svgr/client" />

interface ImportMetaEnv {
  readonly VITE_BASE_URL: string;
  readonly VITE_ASSET_BASE_URL: string;
  readonly VITE_WORKER_BASE_URL?: string;
}

interface ImportMeta {
  readonly env: ImportMetaEnv;
}
