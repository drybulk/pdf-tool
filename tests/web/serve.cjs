// 테스트용 정적 파일 서버: web/ 폴더를 127.0.0.1의 빈 포트로 제공합니다.
// launch()는 테스트용 브라우저를 띄웁니다. 환경 변수 PDF_TOOL_EXTENSION에 확장 폴더(build/extension)를 주면
// 웹 서버 대신 그 확장을 설치한 Chromium에서 확장의 페이지(chrome-extension://...)로 같은 테스트를 실행합니다.
"use strict";

const http = require("http");
const fs = require("fs");
const path = require("path");

const ROOT = path.resolve(__dirname, "..", "..", "web");
const TYPES = {
  ".html": "text/html; charset=utf-8", ".js": "text/javascript", ".mjs": "text/javascript",
  ".css": "text/css", ".png": "image/png", ".wasm": "application/wasm", ".bcmap": "application/octet-stream",
  ".pfb": "application/octet-stream", ".icc": "application/octet-stream",
};

function serve() {
  const server = http.createServer((req, res) => {
    const url = decodeURIComponent(new URL(req.url, "http://x").pathname);
    const file = path.join(ROOT, url === "/" ? "index.html" : url);
    if (!file.startsWith(ROOT) || !fs.existsSync(file) || fs.statSync(file).isDirectory()) {
      res.writeHead(404);
      res.end();
      return;
    }
    res.writeHead(200, { "Content-Type": TYPES[path.extname(file)] || "application/octet-stream" });
    fs.createReadStream(file).pipe(res);
  });
  return new Promise((resolve) => server.listen(0, "127.0.0.1", () => resolve(server)));
}

/**
 * 테스트용 브라우저를 띄우고 { context, base, worker, close }를 돌려줍니다. base는 index.html이 있는 주소입니다.
 * size: [창너비, 창높이]
 */
async function launch(size) {
  const { chromium } = require("playwright");
  // 로캘이 비어 있는 Linux 컨테이너에서는 Chromium이 한국어 다운로드 파일 이름을 "download"로 바꿈
  const env = { ...process.env, LANG: process.env.LANG || "C.UTF-8" };
  const viewport = { width: size[0], height: size[1] };
  const ext = process.env.PDF_TOOL_EXTENSION;
  if (ext) {
    const dir = path.resolve(ext);
    // 확장은 persistent context에서만 설치할 수 있고, 창 없이 실행하려면 channel "chromium"(새 headless)이 필요함
    const context = await chromium.launchPersistentContext("", {
      channel: "chromium", headless: true, env, viewport, acceptDownloads: true,
      args: [`--disable-extensions-except=${dir}`, `--load-extension=${dir}`],
    });
    let [worker] = context.serviceWorkers();
    if (!worker) worker = await context.waitForEvent("serviceworker");
    const id = new URL(worker.url()).host;
    return { context, base: `chrome-extension://${id}/`, worker, close: () => context.close() };
  }
  const server = await serve();
  const browser = await chromium.launch({ env });
  const context = await browser.newContext({ viewport, acceptDownloads: true });
  return {
    context, base: `http://127.0.0.1:${server.address().port}/`, worker: null,
    close: async () => { await browser.close(); server.close(); },
  };
}

module.exports = { serve, launch, ROOT };
