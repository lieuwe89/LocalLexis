// Re-export the impl selected by vite's mode-based alias (see vite.config.ts).
// Default resolution is tauri.ts; `--mode hub` aliases this to web.ts.
export type { Platform, SidecarAuth, FileDropEvent } from './tauri';
export { platform } from './tauri';
