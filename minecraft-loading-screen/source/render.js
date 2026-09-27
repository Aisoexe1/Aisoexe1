// Rasterize an HTML/SVG file with headless Chromium (Playwright), keeping transparency.
// usage: node render.js <input.html> <output.png> <width> <height> [deviceScaleFactor]
const path = require('path');

function loadPlaywright() {
  try {
    return require('playwright');
  } catch (e) {
    const globalRoot = require('child_process').execSync('npm root -g').toString().trim();
    return require(path.join(globalRoot, 'playwright'));
  }
}

(async () => {
  const [, , input, output, w, h, scale] = process.argv;
  const { chromium } = loadPlaywright();
  const browser = await chromium.launch();
  const page = await browser.newPage({
    viewport: { width: +w, height: +h },
    deviceScaleFactor: +(scale || 1),
  });
  await page.goto('file://' + path.resolve(input));
  await page.screenshot({ path: output, omitBackground: true });
  await browser.close();
})().catch((e) => {
  console.error(e);
  process.exit(1);
});
