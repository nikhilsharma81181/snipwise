import type { SnipwiseApi } from './index'

declare global {
  interface Window {
    snipwise: SnipwiseApi
  }
}
