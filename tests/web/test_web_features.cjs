// 웹판 두 번째 단계의 기능 테스트: 이미지 불러오기, 저장 옵션(북마크), 메뉴 막대와 우클릭 메뉴, 이미지로 저장.
// 실행: node tests/web/test_web_features.cjs [창너비x창높이]
// 저장 결과의 북마크와 이름 붙은 대상은 tests/web/test_web_save.py가 데스크톱판과 비교해서 검사합니다.
"use strict";

const fs = require("fs");
const path = require("path");
const zlib = require("zlib");
const { chromium } = require("playwright");

const { serve } = require("./serve.cjs");

function assert(cond, msg) {
  if (!cond) throw new Error("검사 실패: " + msg);
}
function eq(a, b, msg) {
  const ja = JSON.stringify(a), jb = JSON.stringify(b);
  if (ja !== jb) throw new Error(`검사 실패: ${msg}\n  실제: ${ja}\n  기대: ${jb}`);
}
const sleep = (ms) => new Promise((r) => setTimeout(r, ms));

/** 압축하지 않은 zip을 읽어 [{ name, flags, method, crc, data }]를 돌려줍니다. */
function readZip(buf) {
  const out = [];
  let p = 0;
  while (p + 4 <= buf.length && buf.readUInt32LE(p) === 0x04034b50) {
    const nlen = buf.readUInt16LE(p + 26), xlen = buf.readUInt16LE(p + 28), size = buf.readUInt32LE(p + 18);
    const start = p + 30 + nlen + xlen;
    out.push({
      name: buf.subarray(p + 30, p + 30 + nlen).toString("utf8"),
      flags: buf.readUInt16LE(p + 6), method: buf.readUInt16LE(p + 8), crc: buf.readUInt32LE(p + 14),
      data: buf.subarray(start, start + size),
    });
    p = start + size;
  }
  // 중앙 디렉터리 끝 레코드의 항목 수도 확인
  const end = buf.lastIndexOf(Buffer.from([0x50, 0x4b, 0x05, 0x06]));
  assert(end > 0 && buf.readUInt16LE(end + 10) === out.length, "zip 중앙 디렉터리 항목 수");
  return out;
}

/** PNG의 크기와 pHYs(1미터당 화소 수) */
function pngInfo(buf) {
  assert(buf.subarray(0, 8).equals(Buffer.from([137, 80, 78, 71, 13, 10, 26, 10])), "PNG 서명");
  const info = { width: buf.readUInt32BE(16), height: buf.readUInt32BE(20), ppm: null };
  let p = 8;
  while (p < buf.length) {
    const len = buf.readUInt32BE(p);
    const type = buf.subarray(p + 4, p + 8).toString("latin1");
    const crc = zlib.crc32(buf.subarray(p + 4, p + 8 + len));
    assert(crc === buf.readUInt32BE(p + 8 + len), `PNG ${type} 청크 CRC`);
    if (type === "pHYs") info.ppm = [buf.readUInt32BE(p + 8), buf.readUInt32BE(p + 12), buf[p + 16]];
    if (type === "IEND") break;
    p += 12 + len;
  }
  return info;
}

/** JPG의 크기와 JFIF 해상도 */
function jpgInfo(buf) {
  assert(buf[0] === 0xff && buf[1] === 0xd8, "JPG 서명");
  const info = { density: buf.subarray(6, 11).toString("latin1") === "JFIF\0" ? [buf[13], buf.readUInt16BE(14), buf.readUInt16BE(16)] : null };
  let p = 2;
  while (p < buf.length) {
    const m = buf[p + 1];
    const len = buf.readUInt16BE(p + 2);
    if (m >= 0xc0 && m <= 0xc3) {
      info.height = buf.readUInt16BE(p + 5);
      info.width = buf.readUInt16BE(p + 7);
      break;
    }
    p += 2 + len;
  }
  return info;
}

async function main() {
  const size = (process.argv[2] || "1200x750").split("x").map(Number);
  const server = await serve();
  const base = `http://127.0.0.1:${server.address().port}/`;
  // 로캘이 비어 있는 Linux 컨테이너에서는 Chromium이 한국어 다운로드 파일 이름을 "download"로 바꿈
  const browser = await chromium.launch({ env: { ...process.env, LANG: process.env.LANG || "C.UTF-8" } });
  const context = await browser.newContext({ viewport: { width: size[0], height: size[1] }, acceptDownloads: true });
  const page = await context.newPage();
  const problems = [];
  page.on("pageerror", (e) => problems.push("페이지 오류: " + e.message));
  page.on("console", (m) => m.type() === "error" && problems.push("콘솔 오류: " + m.text()));
  page.on("requestfailed", (r) => problems.push("요청 실패: " + r.url()));
  page.on("response", (r) => r.status() >= 400 && problems.push(`응답 ${r.status()}: ${r.url()}`));
  page.on("dialog", (d) => d.dismiss());

  try {
    await page.goto(base);
    await page.waitForSelector("html[data-ready='1']");

    // ---------- 1. 버전이 데스크톱판과 같음 ----------
    const pyVersion = fs.readFileSync(path.join(__dirname, "..", "..", "pdf_common.py"), "utf8").match(/^APP_VERSION = "([^"]+)"/m)[1];
    const webVersion = await page.evaluate(async () => (await import("./js/version.js")).APP_VERSION);
    eq(webVersion, pyVersion, "web/js/version.js의 APP_VERSION과 pdf_common.APP_VERSION");
    console.log("1. 버전 OK");

    // ---------- 시험용 파일 만들기 ----------
    const made = await page.evaluate(async () => {
      const { PDFDocument, StandardFonts } = await import("./vendor/pdf-lib/pdf-lib.esm.min.js");
      async function makePdf(prefix, n) {
        const doc = await PDFDocument.create();
        const font = await doc.embedFont(StandardFonts.Helvetica);
        for (let i = 1; i <= n; i++) doc.addPage([595, 842]).drawText(`${prefix}${i}`, { x: 60, y: 400, size: 48, font });
        return Array.from(await doc.save());
      }
      const blobBytes = (canvas, type, q) => new Promise((res) => canvas.toBlob(async (b) => res(Array.from(new Uint8Array(await b.arrayBuffer()))), type, q));
      // 왼쪽 절반 빨강, 오른쪽 절반 파랑인 200×100 그림
      const rb = document.createElement("canvas");
      rb.width = 200; rb.height = 100;
      let ctx = rb.getContext("2d");
      ctx.fillStyle = "#ff0000"; ctx.fillRect(0, 0, 100, 100);
      ctx.fillStyle = "#0000ff"; ctx.fillRect(100, 0, 100, 100);
      // 왼쪽 절반 초록, 오른쪽 절반 투명인 40×20 PNG
      const alpha = document.createElement("canvas");
      alpha.width = 40; alpha.height = 20;
      ctx = alpha.getContext("2d");
      ctx.fillStyle = "#00ff00"; ctx.fillRect(0, 0, 20, 20);
      // 회색조 PNG
      const gray = document.createElement("canvas");
      gray.width = 30; gray.height = 30;
      ctx = gray.getContext("2d");
      ctx.fillStyle = "#808080"; ctx.fillRect(0, 0, 30, 30);
      ctx.fillStyle = "#202020"; ctx.fillRect(0, 0, 15, 15);
      return {
        A: await makePdf("A", 3), B: await makePdf("B", 1),
        jpg: await blobBytes(rb, "image/jpeg", 0.95), png: await blobBytes(rb, "image/png"),
        alpha: await blobBytes(alpha, "image/png"), gray: await blobBytes(gray, "image/png"),
      };
    });
    /** JPG의 SOI 바로 뒤에 Exif 방향(orientation) 하나만 담은 APP1을 넣습니다. */
    const withExif = (jpg, orientation) => {
      const app1 = Buffer.from([
        0xff, 0xe1, 0x00, 0x22, 0x45, 0x78, 0x69, 0x66, 0x00, 0x00,       // APP1, 길이 34, "Exif\0\0"
        0x4d, 0x4d, 0x00, 0x2a, 0x00, 0x00, 0x00, 0x08,                   // TIFF 머리글 (big-endian), IFD 위치 8
        0x00, 0x01, 0x01, 0x12, 0x00, 0x03, 0x00, 0x00, 0x00, 0x01,       // 항목 1개: 0x0112(방향), SHORT, 1개
        0x00, orientation, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00,            // 값, 다음 IFD 없음
      ]);
      return [...jpg.slice(0, 2), ...app1, ...jpg.slice(2)];
    };
    made.jpg6 = withExif(made.jpg, 6);
    made.jpg2 = withExif(made.jpg, 2);
    made.jpg3 = withExif(made.jpg, 3);

    const file = (name, arr, mimeType = "application/pdf") => ({ name, mimeType, buffer: Buffer.from(arr) });
    const input = page.locator("#file-input");
    const state = () => page.evaluate(() => {
      const t = window.pdfTool;
      const label = (id) => { const p = t.pageOf(id); return `${p.file}:${p.page}`; };
      return { order: t.order.map(label), selected: t.selected.map(label) };
    });

    // ---------- 2. 이미지 → PDF 변환 (데스크톱판 test_image_import.py와 같은 규칙) ----------
    const conv = await page.evaluate(async (m) => {
      const ii = await import("./js/imageimport.js");
      const io = await import("./js/pdfio.js");
      const text = (bytes) => new TextDecoder("latin1").decode(bytes);
      const contains = (hay, needle) => {
        outer: for (let i = 0; i + needle.length <= hay.length; i++) {
          for (let j = 0; j < needle.length; j++) if (hay[i + j] !== needle[j]) continue outer;
          return true;
        }
        return false;
      };
      async function info(bytes, name) {
        const pdf = await ii.imageToPdf(new Uint8Array(bytes), name);
        const doc = await io.openPdf(pdf);
        const pg = await doc.getPage(1);
        const vp = pg.getViewport({ scale: 1 });
        const canvas = await io.renderPage(doc, 0, 0.25).promise;
        const px = (fx, fy) => Array.from(canvas.getContext("2d").getImageData(Math.floor(canvas.width * fx), Math.floor(canvas.height * fy), 1, 1).data.slice(0, 3));
        const t = text(pdf);
        return {
          pages: doc.numPages, w: Math.round(vp.width * 100) / 100, h: Math.round(vp.height * 100) / 100,
          rotate: Number((t.match(/\/Rotate (\d+)/) || [0, -1])[1]),
          filter: (t.match(/\/Filter \/(\w+)/) || [])[1], color: (t.match(/\/ColorSpace \/(\w+)/) || [])[1],
          raw: contains(pdf, new Uint8Array(bytes)), px: [px(0.25, 0.25), px(0.75, 0.25), px(0.25, 0.75), px(0.75, 0.75)],
        };
      }
      const errors = {};
      for (const [name, bytes] of [["x.tiff", [73, 73, 42, 0, 1, 2, 3]], ["broken.png", [137, 80, 78, 71, 1, 2, 3]]]) {
        try { await ii.imageToPdf(new Uint8Array(bytes), name); errors[name] = "오류 없음"; } catch (e) { errors[name] = `${e.constructor.name}: ${e.message}`; }
      }
      return {
        width: ii.IMAGE_PAGE_WIDTH, isImage: ["a.PNG", "b.jpeg", "c.pdf", "d.tif", "e.txt"].map(ii.isImageFile),
        jpg: await info(m.jpg, "a.jpg"), jpg6: await info(m.jpg6, "b.jpg"), jpg3: await info(m.jpg3, "c.jpg"),
        jpg2: await info(m.jpg2, "d.jpg"), png: await info(m.png, "e.png"), alpha: await info(m.alpha, "f.png"),
        gray: await info(m.gray, "g.png"), errors,
      };
    }, made);
    const close = (a, b, tol = 40) => a.every((v, i) => Math.abs(v - b[i]) <= tol);
    const RED = [255, 0, 0], BLUE = [0, 0, 255], GREEN = [0, 255, 0], WHITE = [255, 255, 255];
    assert(Math.abs(conv.width - 595.28) < 0.01, "쪽 너비는 A4 너비");
    eq(conv.isImage, [true, true, false, true, false], "이미지 확장자 판정");
    // JPG: 다시 압축하지 않고 그대로 넣음, 쪽 크기는 A4 너비 × 비율
    eq([conv.jpg.pages, conv.jpg.w, conv.jpg.h, conv.jpg.rotate, conv.jpg.filter, conv.jpg.raw], [1, 595.28, 297.64, 0, "DCTDecode", true], "JPG 그대로 넣기");
    assert(close(conv.jpg.px[0], RED) && close(conv.jpg.px[1], BLUE), "JPG 그림 내용 " + JSON.stringify(conv.jpg.px));
    // Exif 방향 6: 시계 방향 90도. 쪽은 세로로 길어지고 왼쪽(빨강)이 위로 감
    eq([conv.jpg6.w, conv.jpg6.h, conv.jpg6.rotate, conv.jpg6.filter, conv.jpg6.raw], [595.28, 1190.55, 90, "DCTDecode", true], "Exif 방향 6");
    assert(close(conv.jpg6.px[0], RED) && close(conv.jpg6.px[3], BLUE), "Exif 방향 6 그림 " + JSON.stringify(conv.jpg6.px));
    // Exif 방향 3: 180도. 오른쪽(파랑)이 왼쪽으로
    eq([conv.jpg3.w, conv.jpg3.h, conv.jpg3.rotate], [595.28, 297.64, 180], "Exif 방향 3");
    assert(close(conv.jpg3.px[0], BLUE) && close(conv.jpg3.px[1], RED), "Exif 방향 3 그림 " + JSON.stringify(conv.jpg3.px));
    // Exif 방향 2(거울상): 화소를 다시 읽어 무손실로 넣음. 좌우가 바뀜
    eq([conv.jpg2.rotate, conv.jpg2.filter, conv.jpg2.raw], [0, "FlateDecode", false], "거울상 방향 JPG");
    assert(close(conv.jpg2.px[0], BLUE) && close(conv.jpg2.px[1], RED), "거울상 방향 그림 " + JSON.stringify(conv.jpg2.px));
    eq([conv.png.w, conv.png.h, conv.png.filter, conv.png.color], [595.28, 297.64, "FlateDecode", "DeviceRGB"], "PNG");
    assert(close(conv.png.px[0], RED, 2) && close(conv.png.px[1], BLUE, 2), "PNG는 무손실 " + JSON.stringify(conv.png.px));
    // 투명한 부분은 흰색
    assert(close(conv.alpha.px[0], GREEN, 2) && close(conv.alpha.px[1], WHITE, 2), "투명은 흰색 " + JSON.stringify(conv.alpha.px));
    eq(conv.gray.color, "DeviceGray", "회색조 이미지는 회색조로");
    assert(/ImageError/.test(conv.errors["x.tiff"]) && /TIFF/.test(conv.errors["x.tiff"]), "TIFF 안내: " + conv.errors["x.tiff"]);
    assert(/ImageError/.test(conv.errors["broken.png"]), "손상된 PNG: " + conv.errors["broken.png"]);
    console.log("2. 이미지 → PDF 변환 OK");

    // ---------- 3. PDF와 이미지를 섞어 불러오기 (쪽 범위는 PDF에만) ----------
    await page.fill("#range", "2");
    await input.setInputFiles([file("A.pdf", made.A), file("사진.png", made.png, "image/png"), file("회전.jpg", made.jpg6, "image/jpeg"),
      file("x.tiff", [73, 73, 42, 0, 1, 2], "image/tiff")]);
    await page.waitForFunction(() => !window.pdfTool.busy && window.pdfTool.order.length === 3);
    eq((await state()).order, ["A.pdf:2", "사진.png:1", "회전.jpg:1"], "범위는 PDF에만 적용");
    const notice = await page.textContent("#notice");
    assert(notice.includes("x.tiff") && notice.includes("TIFF"), "TIFF를 불러오지 못했다는 안내: " + notice);
    // 이미지 쪽도 썸네일이 그려짐
    await page.waitForFunction(() => document.querySelectorAll(".row .thumb img").length === 3);
    // 이미지 쪽을 저장하면 그 쪽이 들어감 (JPG는 원본 그대로)
    await page.fill("#filename", "섞어서.pdf");
    const [dlMix] = await Promise.all([page.waitForEvent("download"), page.click("#save-btn")]);
    const mixed = fs.readFileSync(await dlMix.path());
    assert(mixed.includes(Buffer.from(made.jpg6)), "저장한 PDF에 JPG 원본이 그대로 들어 있음");
    eq(dlMix.suggestedFilename(), "섞어서.pdf", "저장 파일 이름");
    const mixedInfo = await page.evaluate(async (arr) => {
      const io = await import("./js/pdfio.js");
      const doc = await io.openPdf(new Uint8Array(arr));
      const sizes = [];
      for (let i = 0; i < doc.numPages; i++) { const s = await io.pageSize(doc, i); sizes.push([Math.round(s.width), Math.round(s.height)]); }
      return sizes;
    }, Array.from(mixed));
    eq(mixedInfo, [[595, 842], [595, 298], [595, 1191]], "저장한 쪽 크기 (회전 반영)");
    await page.fill("#range", "");
    console.log("3. PDF와 이미지 섞어 불러오기, 저장 OK");

    // ---------- 4. 저장 옵션: 파일 이름 북마크 ----------
    await page.click("#clear-btn");
    await input.setInputFiles([file("A.pdf", made.A), file("보고서.pdf", made.B)]);
    await page.waitForFunction(() => !window.pdfTool.busy && window.pdfTool.order.length === 4);
    const outlineOf = (arr) => page.evaluate(async (arr) => {
      const { PDFDocument, PDFName, PDFDict } = await import("./vendor/pdf-lib/pdf-lib.esm.min.js");
      const doc = await PDFDocument.load(new Uint8Array(arr));
      const root = doc.catalog.lookup(PDFName.of("Outlines"));
      if (!(root instanceof PDFDict)) return null;
      const titles = [];
      for (let it = root.lookup(PDFName.of("First")); it instanceof PDFDict; it = it.lookup(PDFName.of("Next"))) {
        titles.push(it.lookup(PDFName.of("Title")).decodeText());
      }
      return titles;
    }, Array.from(arr));
    eq([await page.isChecked("#keep-outlines"), await page.isChecked("#file-bookmarks")], [true, false], "저장 옵션 기본값");
    const [dlA] = await Promise.all([page.waitForEvent("download"), page.click("#save-btn")]);
    eq(await outlineOf(fs.readFileSync(await dlA.path())), null, "기본값이면 북마크 없음 (원본에도 없음)");
    await page.check("#file-bookmarks");
    const [dlB] = await Promise.all([page.waitForEvent("download"), page.click("#save-btn")]);
    eq(await outlineOf(fs.readFileSync(await dlB.path())), ["A", "보고서"], "파일 이름 북마크");
    await page.uncheck("#file-bookmarks");
    console.log("4. 저장 옵션 OK");

    // ---------- 5. 메뉴 막대 ----------
    await page.click("#clear-btn");
    await page.evaluate(() => window.pdfTool); // 상태 갱신 대기용
    const menuState = () => page.$$eval("#dropdown-menu button", (bs) => bs.map((b) => [b.dataset.label, b.disabled]));
    const menuOpen = () => page.evaluate(() => !document.getElementById("dropdown-menu").hidden);
    eq(await page.$$eval("#menubar > button", (bs) => bs.map((b) => b.textContent)), ["파일", "편집", "도움말"], "메뉴 이름");
    await page.click('#menubar button[data-menu="파일"]');
    eq(await menuState(), [["PDF/이미지 불러오기...", false], ["새 PDF로 저장...", true], ["이미지로 저장...", true]], "빈 목록의 파일 메뉴");
    // 메뉴가 열린 상태에서 다른 메뉴 이름에 마우스를 올리면 그 메뉴로 바뀜
    await page.hover('#menubar button[data-menu="편집"]');
    const editItems = await menuState();
    eq(editItems.map((x) => x[0]), ["실행 취소", "다시 실행", "전체 선택", "선택 삭제", "위로", "아래로", "맨 위로", "맨 아래로",
      "위치 지정 이동...", "목록 비우기"], "편집 메뉴 항목");
    eq(editItems[0], ["실행 취소", false], "목록 비우기를 되돌릴 수 있음");
    assert(editItems.slice(2).every((x) => x[1]), "빈 목록이면 편집 항목 비활성 (실행 취소 제외)");
    await page.keyboard.press("Escape");
    assert(!(await menuOpen()), "Esc로 메뉴 닫기");
    await page.click('#menubar button[data-menu="편집"]');
    await page.click("#status");
    assert(!(await menuOpen()), "메뉴 밖을 누르면 닫힘");
    // 메뉴 항목 실행
    await page.click('#menubar button[data-menu="편집"]');
    await page.click('#dropdown-menu button[data-label="실행 취소"]');
    await page.waitForFunction(() => window.pdfTool.order.length === 4);
    assert(!(await menuOpen()), "항목을 누르면 메뉴가 닫힘");
    await page.locator(".row").nth(0).click();
    await page.click('#menubar button[data-menu="편집"]');
    eq((await menuState()).filter((x) => !x[1]).map((x) => x[0]),
      ["실행 취소", "다시 실행", "전체 선택", "선택 삭제", "위로", "아래로", "맨 위로", "맨 아래로", "위치 지정 이동...", "목록 비우기"],
      "선택한 쪽이 있을 때 편집 메뉴 (방금 실행 취소했으므로 다시 실행도 가능)");
    await page.click('#dropdown-menu button[data-label="맨 아래로"]');
    eq((await state()).order, ["A.pdf:2", "A.pdf:3", "보고서.pdf:1", "A.pdf:1"], "메뉴로 맨 아래로");
    await page.click('#menubar button[data-menu="편집"]');
    await page.click('#dropdown-menu button[data-label="실행 취소"]');
    eq((await state()).order, ["A.pdf:1", "A.pdf:2", "A.pdf:3", "보고서.pdf:1"], "메뉴로 실행 취소");
    await page.click('#menubar button[data-menu="편집"]');
    await page.click('#dropdown-menu button[data-label="다시 실행"]');
    eq((await state()).order, ["A.pdf:2", "A.pdf:3", "보고서.pdf:1", "A.pdf:1"], "메뉴로 다시 실행");
    // 키보드로 메뉴 안을 옮겨 다님
    await page.click('#menubar button[data-menu="도움말"]');
    await page.keyboard.press("ArrowDown");
    eq(await page.evaluate(() => document.activeElement.dataset.label), "단축키와 마우스 사용법", "화살표로 메뉴 항목 이동");
    await page.keyboard.press("ArrowLeft");
    eq(await page.getAttribute('#menubar button[data-menu="편집"]', "aria-expanded"), "true", "왼쪽 화살표로 옆 메뉴");
    await page.keyboard.press("Escape");
    // 도움말
    await page.click('#menubar button[data-menu="도움말"]');
    await page.click('#dropdown-menu button[data-label="프로그램 정보"]');
    const about = await page.textContent("#info-body");
    assert(about.includes(`PDF 도구 ${pyVersion} (웹판)`) && about.includes("pdf.js") && about.includes("2.11.1"), "프로그램 정보: " + about);
    // 대화 상자가 떠 있는 동안에는 본 화면의 단축키를 처리하지 않음
    const before = (await state()).order;
    await page.keyboard.press("Delete");
    await page.keyboard.press("Control+z");
    eq((await state()).order, before, "대화 상자가 떠 있을 때 Delete, Ctrl+Z 무시");
    await page.click("#info-close");
    assert(!(await page.evaluate(() => document.getElementById("info-dialog").open)), "프로그램 정보 닫기");
    await page.click('#menubar button[data-menu="도움말"]');
    await page.click('#dropdown-menu button[data-label="단축키와 마우스 사용법"]');
    assert((await page.textContent("#info-body")).includes("Shift+클릭"), "단축키 안내");
    await page.keyboard.press("Escape");
    assert(!(await page.evaluate(() => document.getElementById("info-dialog").open)), "Esc로 안내 닫기");
    // 작업 중(불러오기)에는 "항상" 항목만 사용 가능
    const busyMenu = await page.evaluate(async (arr) => {
      const dt = new DataTransfer();
      dt.items.add(new File([new Uint8Array(arr)], "A.pdf", { type: "application/pdf" }));
      window.dispatchEvent(new DragEvent("drop", { dataTransfer: dt, cancelable: true }));
      document.querySelector('#menubar button[data-menu="파일"]').click();
      const file = [...document.querySelectorAll("#dropdown-menu button")].map((b) => b.disabled);
      document.querySelector('#menubar button[data-menu="도움말"]').click();
      const help = [...document.querySelectorAll("#dropdown-menu button")].map((b) => b.disabled);
      document.querySelector('#menubar button[data-menu="도움말"]').click();
      return { busy: window.pdfTool.busy, file, help };
    }, made.A);
    eq(busyMenu, { busy: true, file: [true, true, true], help: [false, false] }, "작업 중 메뉴");
    await page.waitForFunction(() => !window.pdfTool.busy && window.pdfTool.order.length === 7);
    console.log("5. 메뉴 막대 OK");

    // ---------- 6. 우클릭 메뉴 ----------
    await page.click("#clear-btn");
    await input.setInputFiles([file("A.pdf", made.A), file("보고서.pdf", made.B), file("C.pdf", made.A)]);
    await page.waitForFunction(() => !window.pdfTool.busy && window.pdfTool.order.length === 7);
    const ctxState = () => page.$$eval("#context-menu button", (bs) => bs.map((b) => [b.dataset.label, b.disabled]));
    const ctxOpen = () => page.evaluate(() => !document.getElementById("context-menu").hidden);
    const rowAt = async (i) => {
      await page.evaluate((i) => { const l = document.getElementById("list"); l.scrollTop = Math.max(0, i * 110 - 20); }, i);
      return page.locator(".row").nth(i);
    };
    await (await rowAt(4)).click({ button: "right" });
    assert(await ctxOpen(), "우클릭 메뉴가 열림");
    eq((await state()).selected, ["C.pdf:1"], "선택되지 않은 행을 우클릭하면 그 행만 선택");
    eq(await ctxState(), [["이 파일의 쪽 모두 선택 (C.pdf)", false], ["위로", false], ["아래로", false], ["맨 위로", false],
      ["맨 아래로", false], ["위치 지정 이동...", false], ["선택 삭제", false], ["이미지로 저장...", false]], "우클릭 메뉴 항목");
    await page.click('#context-menu button[data-label^="이 파일의 쪽 모두 선택"]');
    eq((await state()).selected, ["C.pdf:1", "C.pdf:2", "C.pdf:3"], "이 파일의 쪽 모두 선택");
    assert(!(await ctxOpen()), "항목을 누르면 닫힘");
    // 이미 선택된 행을 우클릭하면 선택 유지
    await (await rowAt(5)).click({ button: "right" });
    eq((await state()).selected, ["C.pdf:1", "C.pdf:2", "C.pdf:3"], "선택된 행을 우클릭하면 선택 유지");
    eq(await page.evaluate(() => window.pdfTool.pageOf(window.pdfTool.focus)), { file: "C.pdf", page: 2 }, "우클릭한 행이 미리보기 대상");
    await page.click('#context-menu button[data-label="맨 위로"]');
    eq((await state()).order, ["C.pdf:1", "C.pdf:2", "C.pdf:3", "A.pdf:1", "A.pdf:2", "A.pdf:3", "보고서.pdf:1"], "우클릭 메뉴로 맨 위로");
    await (await rowAt(6)).click({ button: "right" });
    await page.click('#context-menu button[data-label="선택 삭제"]');
    eq((await state()).order.length, 6, "우클릭 메뉴로 삭제");
    // 메뉴는 창 밖으로 나가지 않음
    const box = await page.locator("#list").boundingBox();
    await page.mouse.click(box.x + box.width - 5, box.y + box.height - 5, { button: "right" });
    const r = await page.locator("#context-menu").boundingBox();
    const vp = page.viewportSize();
    assert(r.x + r.width <= vp.width && r.y + r.height <= vp.height && r.x >= 0 && r.y >= 0, "우클릭 메뉴가 창 안에 있음 " + JSON.stringify(r));
    await page.keyboard.press("Escape");
    assert(!(await ctxOpen()), "Esc로 우클릭 메뉴 닫기");
    // 빈 목록에서 우클릭: 행 항목은 비활성
    await page.click("#clear-btn");
    await page.click("#list", { button: "right" });
    assert((await ctxState()).every((x) => x[1]), "빈 목록의 우클릭 메뉴는 모두 비활성");
    await page.keyboard.press("Escape");
    console.log("6. 우클릭 메뉴 OK");

    // ---------- 7. 이미지로 저장 ----------
    await input.setInputFiles([file("A.pdf", made.A)]);
    await page.waitForFunction(() => !window.pdfTool.busy && window.pdfTool.order.length === 3);
    const dialogOpen = () => page.evaluate(() => document.getElementById("image-dialog").open);
    // 선택이 없으면 "선택한 쪽"은 비활성, "목록 전체"가 기본
    await page.click("#images-btn");
    assert(await dialogOpen(), "대화 상자가 열림");
    eq(await page.evaluate(() => ({
      sel: document.getElementById("scope-selected-label").textContent, all: document.getElementById("scope-all-label").textContent,
      selDisabled: document.querySelector('input[name="scope"][value="selected"]').disabled,
      checked: document.querySelector('input[name="scope"]:checked').value,
      format: document.querySelector('input[name="format"]:checked').value,
      dpi: document.getElementById("dpi").value, dpis: [...document.getElementById("dpi").options].map((o) => o.value),
      quality: document.getElementById("jpg-quality").value,
    })), { sel: "선택한 쪽 (0쪽)", all: "목록 전체 (3쪽)", selDisabled: true, checked: "all", format: "png", dpi: "150",
      dpis: ["72", "150", "200", "300"], quality: "90" }, "대화 상자 기본값");
    // 대화 상자가 창 안에 있음
    const db = await page.locator("#image-dialog").boundingBox();
    assert(db.y >= 0 && db.y + db.height <= vp.height && db.x >= 0 && db.x + db.width <= vp.width, "대화 상자가 창 안에 있음 " + JSON.stringify(db));
    // JPG 품질 검사
    await page.check('input[name="format"][value="jpg"]');
    await page.fill("#jpg-quality", "0");
    await page.click("#image-ok");
    assert(await dialogOpen(), "품질이 잘못되면 대화 상자가 닫히지 않음");
    assert((await page.textContent("#image-error")).includes("1부터 95"), "품질 오류 안내");
    // 취소하면 아무것도 내려받지 않음
    let downloads = 0;
    const countDl = () => downloads++;
    page.on("download", countDl);
    await page.click("#image-cancel");
    assert(!(await dialogOpen()), "취소");
    await page.click("#images-btn");
    await page.keyboard.press("Escape");
    assert(!(await dialogOpen()), "Esc로 취소");
    await sleep(300);
    eq(downloads, 0, "취소하면 내려받지 않음");
    page.off("download", countDl);
    eq((await page.$$eval("#context-menu, #dropdown-menu", (m) => m.map((x) => x.hidden))), [true, true], "메뉴는 닫혀 있음");

    // 선택한 2쪽을 PNG 72 DPI로 → zip
    await (await rowAt(0)).click();
    await (await rowAt(2)).click({ modifiers: ["Control"] });
    await page.click("#images-btn");
    eq(await page.evaluate(() => [document.getElementById("scope-selected-label").textContent,
      document.querySelector('input[name="scope"]:checked').value]), ["선택한 쪽 (2쪽)", "selected"], "선택이 있으면 선택한 쪽이 기본");
    await page.check('input[name="format"][value="png"]');
    await page.selectOption("#dpi", "72");
    const [dlZip] = await Promise.all([page.waitForEvent("download"), page.click("#image-ok")]);
    eq(dlZip.suggestedFilename(), "A_images.zip", "zip 파일 이름");
    const zip = readZip(fs.readFileSync(await dlZip.path()));
    eq(zip.map((f) => f.name), ["A_p0001.png", "A_p0003.png"], "zip 안의 파일 이름");
    for (const f of zip) {
      eq([f.method, f.flags & 0x0800, f.crc], [0, 0x0800, zlib.crc32(f.data)], `${f.name}: 압축 방식, UTF-8 표시, CRC`);
      const info = pngInfo(f.data);
      eq([info.width, info.height, info.ppm], [595, 842, [2835, 2835, 1]], `${f.name}: 72 DPI 크기와 pHYs`);
    }
    await page.waitForFunction(() => !window.pdfTool.busy);
    assert((await page.textContent("#notice")).includes("이미지 2개를 저장했습니다"), "완료 안내");

    // 한 쪽만이면 zip이 아니라 그림 파일 하나
    await (await rowAt(1)).click();
    await page.click("#images-btn");
    const [dlOne] = await Promise.all([page.waitForEvent("download"), page.click("#image-ok")]);
    eq(dlOne.suggestedFilename(), "A_p0002.png", "한 장이면 그림 파일로 내려받음 (마지막 선택 형식과 DPI 유지)");
    eq(pngInfo(fs.readFileSync(await dlOne.path())).width, 595, "72 DPI 유지");

    // 여러 파일, 전체, JPG 150 DPI 품질 80 → 저장 파일 이름 칸의 이름으로 zip
    await input.setInputFiles([file("보고서.pdf", made.B)]);
    await page.waitForFunction(() => !window.pdfTool.busy && window.pdfTool.order.length === 4);
    await page.fill("#filename", "묶음.pdf");
    await page.click("#images-btn");
    await page.check('input[name="scope"][value="all"]');
    await page.check('input[name="format"][value="jpg"]');
    await page.fill("#jpg-quality", "80");
    await page.selectOption("#dpi", "150");
    const [dlJpg] = await Promise.all([page.waitForEvent("download"), page.click("#image-ok")]);
    eq(dlJpg.suggestedFilename(), "묶음_images.zip", "여러 파일이면 저장 파일 이름으로 zip");
    const jz = readZip(fs.readFileSync(await dlJpg.path()));
    eq(jz.map((f) => f.name), ["A_p0001.jpg", "A_p0002.jpg", "A_p0003.jpg", "보고서_p0001.jpg"], "JPG 파일 이름 (한국어 포함)");
    const ji = jpgInfo(jz[3].data);
    eq(ji.density, [1, 150, 150], "JPG 해상도 기록");
    assert(ji.width === 1240 && Math.abs(ji.height - 1754) <= 1, `150 DPI 크기 ${ji.width}x${ji.height}`);
    // 파일 이름 규칙 (데스크톱판 image_file_names와 같음)
    eq(await page.evaluate(async () => (await import("./js/imageexport.js")).imageFileNames(
      [{ name: "a.pdf", index: 0 }, { name: "A.pdf", index: 0 }, { name: "a.pdf", index: 0 }, { name: "b.c.pdf", index: 12344 }], "png")),
    ["a_p0001.png", "A_p0001_2.png", "a_p0001_3.png", "b.c_p12345.png"], "이미지 파일 이름 규칙");
    console.log("7. 이미지로 저장 OK");

    // ---------- 8. 메뉴와 대화 상자를 더한 화면 배치 ----------
    for (const [w, h] of [[size[0], size[1]], [1100, 600], [800, 500], [640, 460], [1400, 750]]) {
      await page.setViewportSize({ width: w, height: h });
      await sleep(100);
      const ok = await page.evaluate(() => {
        const inView = (el) => {
          const b = el.getBoundingClientRect();
          return b.width > 0 && b.top >= 0 && b.bottom <= window.innerHeight + 0.5 && b.left >= 0 && b.right <= window.innerWidth + 0.5;
        };
        const ids = ["menubar", "open-btn", "keep-outlines", "file-bookmarks", "images-btn", "save-btn", "progress"];
        return { out: ids.filter((id) => !inView(document.getElementById(id))), listH: document.getElementById("list").clientHeight };
      });
      eq(ok.out, [], `${w}x${h}: 창 밖으로 나간 요소`);
      assert(ok.listH >= 110, `${w}x${h}: 목록이 한 행 이상 보여야 함 ${ok.listH}`);
      await page.click("#images-btn");
      const d = await page.locator("#image-dialog").boundingBox();
      assert(d.y >= 0 && d.y + d.height <= h && d.x >= 0 && d.x + d.width <= w, `${w}x${h}: 대화 상자가 창 안에 있음 ${JSON.stringify(d)}`);
      await page.click("#image-cancel");
    }
    console.log("8. 화면 배치 OK");

    eq(problems, [], "콘솔 오류와 실패한 요청");
    console.log("모든 웹판 기능 테스트 통과");
  } finally {
    await browser.close();
    server.close();
  }
}

main().catch((e) => {
  console.error(e.stack || e);
  process.exit(1);
});
