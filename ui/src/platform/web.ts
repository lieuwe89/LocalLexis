import type { Platform, SidecarAuth, FileDropEvent } from './tauri';

export type { Platform, SidecarAuth, FileDropEvent };

export const platform: Platform = {
  async sidecarAuth(): Promise<SidecarAuth> {
    throw new Error('web platform: sidecarAuth not implemented yet');
  },
  resetSidecarAuth() {},
  async appVersion() { return ''; },
  async openPath() {},
  async openFileDialog() { return null; },
  async audioDir() { return ''; },
  async pathJoin(...parts) { return parts.join('/'); },
  async onFileDrop() { return () => {}; },
  async checkForUpdates() {},
  async relabelTranscript(id, mapping) {
    const { api } = await import('../api/client');
    const { webRelabel } = await import('../lib/webRelabel');
    await webRelabel(api, id, mapping);
  },
};
