import { chromium } from 'playwright';
import Tesseract from 'tesseract.js';

async function extractTapList(url: string) {
  // 1. Launch browser and navigate
  const browser = await chromium.launch();
  const page = await browser.newPage();
  await page.goto(url, { waitUntil: 'networkidle' });

  // 2. Take full-page screenshot
  const screenshotBuffer = await page.screenshot({ fullPage: true });
  await browser.close();

  // 3. Run OCR on the screenshot
  const {
    data: { text },
  } = await Tesseract.recognize(screenshotBuffer, 'eng', {
    logger: m => console.log(m),
  });

  // 4. Simple parsing (adjust regex as needed)
  const lines = text
    .split('\n')
    .map(l => l.trim())
    .filter(Boolean);

  // Example: lines containing beer names and descriptions
  const taplist = lines.map(line => {
    const [name, ...rest] = line.split(/–|-|:/);
    return {
      name: name.trim(),
      desc: rest.join(' ').trim(),
    };
  });

  return taplist;
}

// Example usage
(async () => {
  const url = 'https://example-brewery.com/taps';
  const taplist = await extractTapList(url);
  console.log(taplist);
})();
