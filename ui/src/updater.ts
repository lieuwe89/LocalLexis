import { platform } from './platform';
export const checkForUpdates = (silent = false) => platform.checkForUpdates(silent);
