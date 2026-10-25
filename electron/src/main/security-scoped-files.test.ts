// @vitest-environment node
import { expect, it, vi } from 'vitest';

import { securityScopedDialogOptions, withSecurityScopedBookmark } from './security-scoped-files';

it('leaves direct-download dialog options unchanged', () => {
  const options = { defaultPath: 'take.wav' };
  expect(securityScopedDialogOptions(options, false)).toBe(options);
});

it('requests a bookmark only for sandbox-scoped dialogs', () => {
  expect(securityScopedDialogOptions({ defaultPath: 'take.wav' }, true)).toEqual({
    defaultPath: 'take.wav',
    securityScopedBookmarks: true,
  });
});

it('holds sandbox access for the operation and always releases it', async () => {
  const stop = vi.fn();
  const start = vi.fn(() => stop);
  const operation = vi.fn(async () => {
    expect(start).toHaveBeenCalledWith('bookmark');
    expect(stop).not.toHaveBeenCalled();
    throw new Error('write failed');
  });
  await expect(withSecurityScopedBookmark('bookmark', operation, true, start)).rejects.toThrow(
    'write failed',
  );
  expect(stop).toHaveBeenCalledOnce();
});

it('fails closed when a sandbox dialog omits authorization', async () => {
  const operation = vi.fn(async () => undefined);
  await expect(withSecurityScopedBookmark(undefined, operation, true, vi.fn())).rejects.toThrow(
    'did not include sandbox authorization',
  );
  expect(operation).not.toHaveBeenCalled();
});
