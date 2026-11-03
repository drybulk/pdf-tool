// 웹판의 저장 함수(web/js/pdfsave.js)를 Chromium에서 실행해 결과 PDF를 파일로 씁니다.
// tests/web/test_web_save.py가 이 스크립트를 불러서, 데스크톱판 테스트와 같은 PDF와 같은 기대값으로 검사합니다.
// 실행: node tests/web/save_cases.cjs 사례.json
//   사례.json: { "cases": [ { "out": 결과 경로, "pages": [[원본 경로, 쪽 인덱스], ...],
//                              "options": { "fileBookmarks": bool, "keepOutlines": bool } }, ... ] }
"use strict";

const fs = require("fs");
const path = require("path");
const { chromium } = require("playwright");
const { serve } = require("./serve.cjs");

async function main() {
  const spec = JSON.parse(fs.readFileSync(process.argv[2], "utf8"));
  const server = await serve();
  const browser = await chromium.launch();
  try {
    const page = await browser.newPage();
    const errors = [];
    page.on("pageerror", (e) => errors.push(e.message));
    await page.goto(`http://127.0.0.1:${server.address().port}/`);
    await page.waitForSelector("html[data-ready='1']");
    const files = {};
    for (const c of spec.cases) for (const [p] of c.pages) files[p] = files[p] || Array.from(fs.readFileSync(p));
    const outputs = await page.evaluate(async ({ cases, files }) => {
      const { savePages } = await import("./js/pdfsave.js");
      // 같은 경로는 같은 원본 객체로 (화면에서 한 번 불러온 파일과 같음)
      const sources = {};
      for (const [p, bytes] of Object.entries(files)) {
        sources[p] = { name: p.split(/[\\/]/).pop(), bytes: new Uint8Array(bytes) };
      }
      const result = [];
      for (const c of cases) {
        const pages = c.pages.map(([p, index]) => ({ source: sources[p], index }));
        result.push(Array.from(await savePages(pages, c.options || {})));
      }
      return result;
    }, { cases: spec.cases, files });
    spec.cases.forEach((c, i) => fs.writeFileSync(c.out, Buffer.from(outputs[i])));
    if (errors.length) throw new Error(errors.join("\n"));
  } finally {
    await browser.close();
    server.close();
  }
}

main().catch((e) => {
  console.error(e.stack || e);
  process.exit(1);
});
