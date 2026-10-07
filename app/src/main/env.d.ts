/// <reference types="electron-vite/node" />

// MAIN_VITE_* vars come from app/.env files at build time (electron-vite)
interface ImportMetaEnv {
  readonly MAIN_VITE_API_URL?: string
}

interface ImportMeta {
  readonly env: ImportMetaEnv
}
