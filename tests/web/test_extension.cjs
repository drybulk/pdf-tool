// Chrome 확장 테스트. tools/build_extension.py로 확장을 만들고, 그 확장을 설치한 Chromium에서 검사합니다.
// 1) 만든 파일: manifest(버전, 권한 없음, 보안 정책), 아이콘, web/의 파일이 모두 들어 있는지, 스토어용 zip
// 2) 툴바 아이콘 동작(새 탭으로 열기), 확장의 보안 정책 안에서 pdf.js 작업 스레드와 wasm 디코더가 동작하는지
// 3) 웹판 테스트 두 개(test_web.cjs, test_web_features.cjs)를 확장의 페이지에서 그대로 실행
// 실행: node tests/web/test_extension.cjs [창너비x창높이]   (Python이 필요. PYTHON 환경 변수로 실행 파일을 지정할 수 있음)
"use strict";

const fs = require("fs");
const path = require("path");
const zlib = require("zlib");
const { spawnSync } = require("child_process");

const { launch } = require("./serve.cjs");

const REPO = path.resolve(__dirname, "..", "..");
const OUT = path.join(REPO, "build", "extension");

function assert(cond, msg) {
  if (!cond) throw new Error("검사 실패: " + msg);
}
function eq(a, b, msg) {
  const ja = JSON.stringify(a), jb = JSON.stringify(b);
  if (ja !== jb) throw new Error(`검사 실패: ${msg}\n  실제: ${ja}\n  기대: ${jb}`);
}

/** 폴더 안의 파일 목록 (슬래시로 나눈 상대 경로, 정렬) */
function listFiles(dir, skip = () => false) {
  const out = [];
  const walk = (d) => {
    for (const e of fs.readdirSync(d, { withFileTypes: true })) {
      const full = path.join(d, e.name);
      const rel = path.relative(dir, full).split(path.sep).join("/");
      if (skip(rel)) continue;
      if (e.isDirectory()) walk(full);
      else out.push(rel);
    }
  };
  walk(dir);
  return out.sort();
}

/** zip의 중앙 디렉터리에서 파일 이름 목록을 읽음 */
function zipNames(buf) {
  const end = buf.lastIndexOf(Buffer.from([0x50, 0x4b, 0x05, 0x06]));
  const count = buf.readUInt16LE(end + 10);
  let p = buf.readUInt32LE(end + 16);
  const names = [];
  for (let i = 0; i < count; i++) {
    const nlen = buf.readUInt16LE(p + 28), xlen = buf.readUInt16LE(p + 30), clen = buf.readUInt16LE(p + 32);
    names.push(buf.subarray(p + 46, p + 46 + nlen).toString("utf8"));
    p += 46 + nlen + xlen + clen;
  }
  return names.sort();
}

function pngSize(file) {
  const b = fs.readFileSync(file);
  assert(b.subarray(1, 4).toString("latin1") === "PNG", `${file}: PNG 파일`);
  return [b.readUInt32BE(16), b.readUInt32BE(20)];
}

/** 16×16 빨간 JPEG 2000 그림 (Pillow로 만든 것). pdf.js는 이 형식을 wasm(openjpeg)으로 풂 */
const RED_JP2 = "AAAADGpQICANCocKAAAAFGZ0eXBqcDIgAAAAAGpwMiAAAAAtanAyaAAAABZpaGRyAAAAEAAAABAAAwcHAAAAAAAPY29scgEAAAAAABAAAACq" +
  "anAyY/9P/1EALwAAAAAAEAAAABAAAAAAAAAAAAAAABAAAAAQAAAAAAAAAAAAAwcBAQcBAQcBAf9SAAwAAAABAAQEBAAB/1wAEEBASEhQSEhQSEhQ" +
  "SEhQ/2QAJQABQ3JlYXRlZCBieSBPcGVuSlBFRyB2ZXJzaW9uIDIuNS40/5AACgAAAAAAJgAB/5PPtAQA34AIB9+ACAeAgICAgICAgICAgID/2Q==";

async function main() {
  const sizeArg = process.argv[2] || "1200x750";
  const size = sizeArg.split("x").map(Number);

  // ---------- 1. 확장 만들기 ----------
  const python = process.env.PYTHON || (process.platform === "win32" ? "python" : "python3");
  const build = spawnSync(python, [path.join(REPO, "tools", "build_extension.py")], { encoding: "utf8", env: { ...process.env, PYTHONUTF8: "1" } });
  assert(build.status === 0, "build_extension.py 실행: " + (build.stderr || build.stdout || build.error));
  process.stdout.write(build.stdout);

  const manifest = JSON.parse(fs.readFileSync(path.join(OUT, "manifest.json"), "utf8"));
  const appVersion = fs.readFileSync(path.join(REPO, "pdf_common.py"), "utf8").match(/^APP_VERSION = "([^"]+)"/m)[1];
  eq(manifest.manifest_version, 3, "Manifest V3");
  eq(manifest.version, appVersion, "확장의 버전은 APP_VERSION");
  assert(manifest.description.length <= 132, "설명은 132자 이하 (스토어 규칙)");
  eq([manifest.permissions, manifest.host_permissions, manifest.optional_permissions], [undefined, undefined, undefined], "권한을 요청하지 않음");
  const csp = manifest.content_security_policy.extension_pages;
  assert(!/unsafe-eval'|unsafe-inline|https?:/.test(csp.replace("'wasm-unsafe-eval'", "")), "보안 정책에 eval, 인라인, 외부 주소 허용이 없음: " + csp);
  for (const [s, file] of Object.entries(manifest.icons)) eq(pngSize(path.join(OUT, file)), [Number(s), Number(s)], `아이콘 ${s}px`);
  for (const file of Object.values(manifest.action.default_icon)) assert(fs.existsSync(path.join(OUT, file)), "툴바 아이콘 " + file);
  // web/의 파일이 모두 들어 있음 (README.md 제외), 그 밖에는 확장 파일과 라이선스 문서만
  const webFiles = listFiles(path.join(REPO, "web"), (rel) => rel === "README.md");
  const extFiles = listFiles(OUT);
  const extra = extFiles.filter((f) => !webFiles.includes(f));
  eq(webFiles.filter((f) => !extFiles.includes(f)), [], "확장에 빠진 web/ 파일");
  eq(extra, ["LICENSE", "THIRD_PARTY_NOTICES.md", "background.js", "icons/icon128.png", "icons/icon16.png", "icons/icon32.png",
    "icons/icon48.png", "manifest.json"], "web/ 밖에서 넣은 파일");
  for (const f of webFiles) {
    assert(fs.readFileSync(path.join(REPO, "web", f)).equals(fs.readFileSync(path.join(OUT, f))), "web/ 파일 내용이 같음: " + f);
  }
  // 인라인 스크립트가 없음 (확장의 보안 정책은 인라인 스크립트를 막음)
  for (const name of ["index.html", "privacy.html"]) {
    const html = fs.readFileSync(path.join(OUT, name), "utf8");
    assert(!/<script(?![^>]*\bsrc=)[^>]*>/i.test(html) && !/\son[a-z]+=/i.test(html), `${name}에 인라인 스크립트나 on... 속성이 없음`);
  }
  // 스토어용 zip: 폴더와 같은 파일, manifest.json이 맨 위
  const zipPath = path.join(REPO, "build", `pdf-tool-extension-${appVersion}.zip`);
  eq(zipNames(fs.readFileSync(zipPath)), extFiles, "스토어용 zip의 파일 목록");
  console.log(`1. 확장 만들기 OK (${extFiles.length}개 파일)`);

  // ---------- 2. 설치한 확장의 동작 ----------
  process.env.PDF_TOOL_EXTENSION = OUT;
  const env = await launch(size);
  try {
    const { context, base, worker } = env;
    assert(base.startsWith("chrome-extension://"), "확장의 주소: " + base);
    eq(new URL(worker.url()).pathname, "/background.js", "백그라운드 서비스 워커");
    // 툴바 아이콘을 누른 것과 같은 동작: 새 탭으로 index.html을 엶
    const [page] = await Promise.all([context.waitForEvent("page"), worker.evaluate(() => globalThis.openApp())]);
    const problems = [];
    page.on("pageerror", (e) => problems.push("페이지 오류: " + e.message));
    page.on("console", (m) => m.type() === "error" && problems.push("콘솔 오류: " + m.text()));
    await page.waitForSelector("html[data-ready='1']");
    eq(page.url(), base + "index.html", "새 탭의 주소");
    eq(await page.title(), "PDF 도구 (웹)", "새 탭의 제목");
    const ok = await page.evaluate(async (jp2) => {
      const violations = [];
      document.addEventListener("securitypolicyviolation", (e) => violations.push(`${e.violatedDirective} ${e.blockedURI}`));
      const io = await import("./js/pdfio.js");
      const ii = await import("./js/imageimport.js");
      // JPEG 2000 그림 하나로 된 PDF를 만들어 그림: pdf.js 작업 스레드가 wasm 디코더를 써야 그려짐
      const data = Uint8Array.from(atob(jp2), (c) => c.charCodeAt(0));
      const pdf = ii.buildImagePdf([{ width: 16, height: 16, pw: 100, ph: 100, rotate: 0, color: "DeviceRGB", filter: "JPXDecode", data }]);
      const doc = await io.openPdf(pdf);
      const canvas = await io.renderPage(doc, 0, 1).promise;
      const px = Array.from(canvas.getContext("2d").getImageData(50, 50, 1, 1).data.slice(0, 3));
      // eval은 막혀 있어야 함 (확장의 보안 정책이 실제로 적용되는지)
      let evalBlocked = false;
      try { new Function("return 1")(); } catch (e) { evalBlocked = true; }
      return { px, evalBlocked, violations };
    }, RED_JP2);
    assert(ok.px[0] > 200 && ok.px[1] < 60 && ok.px[2] < 60, "JPEG 2000 그림이 wasm 디코더로 그려짐 " + JSON.stringify(ok.px));
    assert(ok.evalBlocked, "확장의 보안 정책이 eval을 막음");
    // pdf.js가 작업 스레드를 띄우지 못하면 경고만 남기고 메인 스레드에서 처리하므로, 작업 스레드가 실제로 있는지 확인
    assert(page.workers().some((w) => /pdf\.worker\.min\.mjs$/.test(w.url())), "pdf.js 작업 스레드가 확장 안에서 실행됨");
    eq(ok.violations, [], "보안 정책 위반");
    eq(problems, [], "콘솔 오류");
    console.log("2. 툴바 아이콘, 보안 정책 안의 작업 스레드와 wasm OK");
  } finally {
    await env.close();
  }

  // ---------- 3. 웹판 테스트를 확장의 페이지에서 실행 ----------
  for (const test of ["test_web.cjs", "test_web_features.cjs"]) {
    console.log(`3. ${test}를 확장에서 실행`);
    const r = spawnSync(process.execPath, [path.join(__dirname, test), sizeArg], { stdio: "inherit", env: { ...process.env, PDF_TOOL_EXTENSION: OUT } });
    assert(r.status === 0, `${test} (확장) 실패`);
  }
  console.log("모든 확장 테스트 통과");
}

main().catch((e) => {
  console.error(e.stack || e);
  process.exit(1);
});
