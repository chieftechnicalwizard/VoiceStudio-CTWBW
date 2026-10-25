import assert from 'node:assert/strict';
import { chromium } from 'playwright';

const browser = await chromium.launch({
  ...(process.env.CHROMIUM_PATH ? { executablePath: process.env.CHROMIUM_PATH } : {}),
  headless: true,
});
try {
  const page = await browser.newPage({ viewport: { width: 1200, height: 800 } });
  await page.addInitScript(() => localStorage.setItem('voicestudio.setup.complete.v1', '1'));
  await page.route(
    (url) => url.pathname.startsWith('/api/'),
    (route) => {
      const path = new URL(route.request().url()).pathname;
      const fixtures = {
        '/api/health': { status: 'ok' },
        '/api/setup/status': { ready: true },
        '/api/models/install/status': { jobs: [] },
        '/api/profiles': [],
        '/api/history': [],
        '/api/projects': [],
      };
      return path in fixtures
        ? route.fulfill({ json: fixtures[path] })
        : route.fulfill({ status: 404, json: { detail: 'Not mocked' } });
    },
  );
  await page.goto(
    (process.env.VOICESTUDIO_UI_URL || 'http://localhost:3928') + '/#/settings/appearance',
  );
  const dark = page.getByRole('group', { name: 'Dark', exact: true });
  const original = dark.getByRole('button', { name: 'VoiceStudio Original', exact: true });
  assert.equal(
    await dark.getByRole('button', { name: 'Studio', exact: true }).getAttribute('aria-pressed'),
    'true',
  );
  assert.equal(await original.getAttribute('aria-pressed'), 'false');
  await original.click();
  assert.equal(await original.getAttribute('aria-pressed'), 'true');
  assert.equal(await page.evaluate(() => document.documentElement.dataset.themeId), 'signal');
  const originalBackground = await page.evaluate(
    () => getComputedStyle(document.body).backgroundColor,
  );
  await dark.getByRole('button', { name: 'Studio', exact: true }).click();
  let state = await page.evaluate(() => ({
    dark: document.documentElement.classList.contains('dark'),
    palette: document.documentElement.dataset.themeId ?? null,
    saved: JSON.parse(localStorage.getItem('voicestudio.theme.v2') || '{}'),
  }));
  assert.equal(state.dark, true);
  assert.equal(state.palette, null);
  assert.equal(state.saved.dark, 'default');
  assert.equal(state.saved.mode, 'dark');
  assert.notEqual(
    await page.evaluate(() => getComputedStyle(document.body).backgroundColor),
    originalBackground,
  );
  assert.equal(
    await dark.getByRole('button', { name: 'Studio', exact: true }).getAttribute('aria-pressed'),
    'true',
  );
  assert.equal(await original.getAttribute('aria-pressed'), 'false');

  const light = page.getByRole('group', { name: 'Light', exact: true });
  assert.equal(
    await light.getByRole('button', { name: 'Studio', exact: true }).getAttribute('aria-pressed'),
    'true',
  );
  await light.getByRole('button', { name: 'Studio', exact: true }).click();
  state = await page.evaluate(() => ({
    dark: document.documentElement.classList.contains('dark'),
    palette: document.documentElement.dataset.themeId ?? null,
    saved: JSON.parse(localStorage.getItem('voicestudio.theme.v2') || '{}'),
  }));
  assert.equal(state.dark, false);
  assert.equal(state.palette, null);
  assert.equal(state.saved.light, 'default');
  assert.equal(state.saved.mode, 'light');

  await page.reload();
  assert.equal(
    await page.evaluate(() => document.documentElement.classList.contains('dark')),
    false,
  );
  assert.equal(
    await light.getByRole('button', { name: 'Studio', exact: true }).getAttribute('aria-pressed'),
    'true',
  );
  console.log('PASS: Studio dark/light applies and survives reload');
} finally {
  await browser.close();
}
