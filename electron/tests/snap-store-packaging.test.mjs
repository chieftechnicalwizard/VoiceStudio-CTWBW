import assert from 'node:assert/strict';
import test from 'node:test';

import { distributionPackaging } from '../electron-builder.config.mjs';
import metadata from '../../store/metadata.json' with { type: 'json' };

test('keeps direct Linux packaging and its updater unchanged', () => {
  const packaging = distributionPackaging('direct');
  assert.deepEqual(packaging.linuxTargets, ['AppImage', 'deb']);
  assert.equal(packaging.linuxExecutableName, undefined);
  assert.equal(packaging.snapcraft, undefined);
  assert.deepEqual(packaging.publish, {
    provider: 'generic',
    url: 'https://github.com/debpalash/VoiceStudio/releases/latest/download',
    channel: `electron-stable-${process.platform}-${process.arch}`,
  });
});

test('builds the Snap Store distribution as a strictly confined store-owned package', () => {
  const packaging = distributionPackaging('snap-store');
  assert.deepEqual(packaging.linuxTargets, ['snap']);
  assert.equal(packaging.linuxExecutableName, 'voicestudio');
  assert.equal(packaging.snapcraft.base, 'core22');
  assert.equal(packaging.snapcraft.core22.confinement, 'strict');
  assert.equal(packaging.snapcraft.core22.grade, 'stable');
  assert.equal(packaging.snapcraft.core22.allowNativeWayland, true);
  assert.equal(packaging.snapcraft.core22.summary, metadata.listing.shortDescription);
  assert.equal(packaging.snapcraft.core22.description, metadata.listing.description);
  assert.deepEqual(packaging.publish, { provider: 'snapStore' });

  const plugs = packaging.snapcraft.core22.plugs;
  assert(
    plugs.some(
      (plug) =>
        plug['browser-support']?.interface === 'browser-support' &&
        plug['browser-support']['allow-sandbox'] === false,
    ),
    'Strict Snap confinement replaces the privileged Chromium sandbox',
  );
  for (const plug of [
    'home',
    'network',
    'network-bind',
    'audio-playback',
    'audio-record',
    'opengl',
  ]) {
    assert(plugs.includes(plug), `Snap declares required ${plug} interface`);
  }
  assert(!plugs.includes('removable-media'), 'User-selected removable files use the portal');
});
