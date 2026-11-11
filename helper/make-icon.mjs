// Render app/public/favicon.svg into helper/slanki.ico (PNG-compressed sizes
// 16–256) for the Windows executable. Run after changing the logo:
//   node helper/make-icon.mjs
import { readFileSync, writeFileSync } from "node:fs";
import { chromium } from "playwright";

const svg = readFileSync(new URL("../app/public/favicon.svg", import.meta.url));
const sizes = [16, 20, 24, 32, 40, 48, 64, 128, 256];
const browser = await chromium.launch({ channel: "chrome" });
const images = [];
try {
  for (const size of sizes) {
    const page = await browser.newPage({ viewport: { width: size, height: size } });
    await page.setContent(
      `<html><body style="margin:0;background:transparent"><img src="data:image/svg+xml;base64,${svg.toString("base64")}" width="${size}" height="${size}" style="display:block"></body></html>`,
    );
    images.push(await page.screenshot({ omitBackground: true }));
    await page.close();
  }
} finally {
  await browser.close();
}

const header = Buffer.alloc(6 + 16 * sizes.length);
header.writeUInt16LE(0, 0);
header.writeUInt16LE(1, 2); // icon
header.writeUInt16LE(sizes.length, 4);
let offset = header.length;
sizes.forEach((size, i) => {
  const entry = 6 + 16 * i;
  header.writeUInt8(size >= 256 ? 0 : size, entry);
  header.writeUInt8(size >= 256 ? 0 : size, entry + 1);
  header.writeUInt16LE(1, entry + 4); // planes
  header.writeUInt16LE(32, entry + 6); // bits per pixel
  header.writeUInt32LE(images[i].length, entry + 8);
  header.writeUInt32LE(offset, entry + 12);
  offset += images[i].length;
});
writeFileSync(new URL("./slanki.ico", import.meta.url), Buffer.concat([header, ...images]));
console.log(`helper/slanki.ico: ${sizes.join(", ")} px`);
