import assert from 'node:assert/strict';
import { existsSync, mkdtempSync, readFileSync } from 'node:fs';
import { tmpdir } from 'node:os';
import { join } from 'node:path';
import test from 'node:test';

import { createSnapStoreAssets } from '../../scripts/create_snap_store_assets.mjs';

test('derives a bounded Snap Store media set from canonical listing assets', () => {
  const outputDir = mkdtempSync(join(tmpdir(), 'voicestudio-snap-assets-'));
  const manifest = createSnapStoreAssets({ outputDir });

  assert.equal(manifest.canonicalSource, 'store/assets.json');
  assert.equal(manifest.icon.width, 512);
  assert.equal(manifest.icon.height, 512);
  assert.equal(manifest.screenshots.length, 5);
  assert(existsSync(join(outputDir, manifest.icon.file)));
  for (const screenshot of manifest.screenshots) {
    assert(screenshot.width >= 480 && screenshot.height >= 480);
    assert(screenshot.width / screenshot.height >= 0.5);
    assert(screenshot.width / screenshot.height <= 2);
    assert(screenshot.bytes <= 2 * 1024 * 1024);
    assert.match(screenshot.sha256, /^[a-f0-9]{64}$/);
    assert(existsSync(join(outputDir, screenshot.file)));
  }
  assert.deepEqual(
    JSON.parse(readFileSync(join(outputDir, 'listing-assets.json'), 'utf8')),
    manifest,
  );
});
