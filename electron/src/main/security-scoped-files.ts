import { app } from 'electron';

import { currentDistributionProfile } from './distribution';

export function securityScopedFileAccessSupported(
  packaged = app.isPackaged,
  platform = process.platform,
): boolean {
  return (
    packaged &&
    platform === 'darwin' &&
    currentDistributionProfile().fileAccess === 'sandbox-scoped'
  );
}

export function securityScopedDialogOptions<T extends object>(
  options: T,
  enabled = securityScopedFileAccessSupported(),
): T & { securityScopedBookmarks?: boolean } {
  return enabled ? { ...options, securityScopedBookmarks: true } : options;
}

export async function withSecurityScopedBookmark<T>(
  bookmark: string | undefined,
  operation: () => Promise<T>,
  enabled = securityScopedFileAccessSupported(),
  startAccess = (value: string) => app.startAccessingSecurityScopedResource(value),
): Promise<T> {
  if (!enabled) return operation();
  if (!bookmark) throw new Error('The selected file did not include sandbox authorization');
  const stopAccess = startAccess(bookmark);
  try {
    return await operation();
  } finally {
    stopAccess();
  }
}
