import { check } from '@tauri-apps/plugin-updater';
import { ask } from '@tauri-apps/plugin-dialog';
import { relaunch } from '@tauri-apps/plugin-process';

export async function checkForUpdates(silent = false): Promise<void> {
  let update;
  try {
    update = await check();
  } catch (err) {
    if (!silent) console.error('Update check failed:', err);
    return;
  }
  if (!update?.available) return;

  const proceed = await ask(
    `LocalLexis ${update.version} is available.\n\n${update.body ?? ''}`.trim(),
    { title: 'Update available', kind: 'info', okLabel: 'Install and restart', cancelLabel: 'Later' },
  );
  if (!proceed) return;

  await update.downloadAndInstall();
  await relaunch();
}
