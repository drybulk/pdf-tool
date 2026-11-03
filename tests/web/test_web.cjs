// 웹판(web/) 브라우저 테스트. Playwright의 Chromium으로 실제 화면을 조작해서 검사합니다.
// 실행: node tests/web/test_web.cjs [창너비x창높이]
// 준비: npm install playwright && npx playwright install chromium (이미 설치된 환경이면 생략)
"use strict";

const fs = require("fs");
const path = require("path");

const { launch } = require("./serve.cjs");

function assert(cond, msg) {
  if (!cond) throw new Error("검사 실패: " + msg);
}
function eq(a, b, msg) {
  const ja = JSON.stringify(a), jb = JSON.stringify(b);
  if (ja !== jb) throw new Error(`검사 실패: ${msg}\n  실제: ${ja}\n  기대: ${jb}`);
}
const sleep = (ms) => new Promise((r) => setTimeout(r, ms));

async function main() {
  const size = (process.argv[2] || "1200x750").split("x").map(Number);
  // PDF_TOOL_EXTENSION을 주면 Chrome 확장으로 설치한 웹판에서 실행함 (tests/web/test_extension.cjs가 사용)
  const env = await launch(size);
  const { context, base } = env;
  const page = await context.newPage();
  const problems = [];
  page.on("pageerror", (e) => problems.push("페이지 오류: " + e.message));
  page.on("console", (m) => m.type() === "error" && problems.push("콘솔 오류: " + m.text()));
  page.on("requestfailed", (r) => problems.push("요청 실패: " + r.url()));
  page.on("response", (r) => r.status() >= 400 && problems.push(`응답 ${r.status()}: ${r.url()}`));
  let dialogAnswer = null;
  page.on("dialog", (d) => (dialogAnswer === null ? d.dismiss() : d.accept(dialogAnswer)));

  try {
    await page.goto(base + "index.html");
    await page.waitForSelector("html[data-ready='1']");

    // ---------- 1. 쪽 범위 해석 (tests/test_merge.py, test_page_tab.py와 같은 사례) ----------
    const r = await page.evaluate(async () => {
      const { parsePageRanges: P } = await import("./js/ranges.js");
      const range = (a, b) => Array.from({ length: b - a }, (_, i) => a + i);
      const bad = [];
      for (const t of ["0-3", "7-900", "9-2", "abc", "-", "1-2-3"]) {
        try { P(t, 800); bad.push(t); } catch (e) { /* 오류가 나야 함 */ }
      }
      return {
        a: JSON.stringify(P("721-732", 800)) === JSON.stringify(range(720, 732)),
        b: P("1-3, 7, 10-11", 20), c: P("5-", 8), d: P("-3", 8), e: P("", 4), f: P("5,1-2", 8),
        g: P("3~4", 8), h: P("2-3, 1", 3), i: P(" 1 - 2 ; 4", 5), bad,
      };
    });
    assert(r.a, "721-732");
    eq(r.b, [0, 1, 2, 6, 9, 10], "1-3, 7, 10-11");
    eq(r.c, [4, 5, 6, 7], "5-");
    eq(r.d, [0, 1, 2], "-3");
    eq(r.e, [0, 1, 2, 3], "빈 문자열");
    eq(r.f, [4, 0, 1], "입력 순서 유지");
    eq(r.g, [2, 3], "물결표");
    eq(r.h, [1, 2, 0], "2-3, 1");
    eq(r.i, [0, 1, 3], "공백과 세미콜론");
    eq(r.bad, [], "오류가 나야 하는 범위");
    console.log("1. 쪽 범위 해석 OK");

    // ---------- 2. 순서 변경 함수 ----------
    const o = await page.evaluate(async () => {
      const m = await import("./js/order.js");
      const rows = ["a", "b", "c", "d", "e"];
      const s = (...x) => new Set(x);
      return {
        g1: m.gatherSelection(rows, s("b", "d"), 0),
        g2: m.gatherSelection(rows, s("a", "c"), 3),
        g3: m.gatherSelection(rows, s("a", "b"), 0),
        slot: m.slotToPos(rows, s("b", "d"), 4),
        sh1: m.shiftSelection(rows, s("b", "d"), -1),
        sh2: m.shiftSelection(rows, s("a"), -1),
        sh3: m.shiftSelection(rows, s("d", "e"), 1),
        sh4: m.shiftSelection(rows, s("c", "d"), 1),
        mv1: m.moveSelectionTo(rows, s("e"), 1),
        mv2: m.moveSelectionTo(rows, s("a", "c"), 1e9),
      };
    });
    eq(o.g1, ["b", "d", "a", "c", "e"], "선택을 맨 앞에 모으기");
    eq(o.g2, ["b", "d", "e", "a", "c"], "선택을 뒤에 모으기");
    eq(o.g3, null, "바뀌지 않으면 null");
    eq(o.slot, 2, "경계 번호 -> 모을 위치");
    eq(o.sh1, ["b", "a", "d", "c", "e"], "위로");
    eq(o.sh2, null, "맨 위에서 위로");
    eq(o.sh3, null, "맨 아래에서 아래로");
    eq(o.sh4, ["a", "b", "e", "c", "d"], "아래로");
    eq(o.mv1, ["e", "a", "b", "c", "d"], "맨 위로");
    eq(o.mv2, ["b", "d", "e", "a", "c"], "맨 아래로");
    console.log("2. 순서 변경 함수 OK");

    // ---------- 시험용 PDF 만들기 (각 쪽에 "A1" 같은 글자) ----------
    const made = await page.evaluate(async () => {
      const { PDFDocument, StandardFonts } = await import("./vendor/pdf-lib/pdf-lib.esm.min.js");
      async function make(prefix, n, opts = {}) {
        const doc = await PDFDocument.create();
        const font = await doc.embedFont(StandardFonts.Helvetica);
        for (let i = 1; i <= n; i++) {
          const pg = doc.addPage(opts.landscape ? [842, 595] : [595, 842]);
          pg.drawText(`${prefix}${i}`, { x: 60, y: 400, size: 48, font });
        }
        if (opts.password && doc.encrypt) doc.encrypt({ userPassword: opts.password, ownerPassword: "o" });
        return Array.from(await doc.save());
      }
      return {
        A: await make("A", 3), B: await make("B", 4), C: await make("C", 1, { landscape: true }),
        M: await make("M", 40), P: await make("P", 1, { password: "pw" }),
      };
    });
    const file = (name, arr, mimeType = "application/pdf") => ({ name, mimeType, buffer: Buffer.from(arr) });
    const input = page.locator("#file-input");
    const state = () => page.evaluate(() => {
      const t = window.pdfTool;
      const label = (id) => { const p = t.pageOf(id); return `${p.file.replace(".pdf", "")}${p.page}`; };
      return { order: t.order.map(label), selected: t.selected.map(label), ids: t.order };
    });

    // ---------- 3. 불러오기 ----------
    await input.setInputFiles([file("A.pdf", made.A), file("B.pdf", made.B)]);
    await page.waitForFunction(() => window.pdfTool.order.length === 7);
    eq((await state()).order, ["A1", "A2", "A3", "B1", "B2", "B3", "B4"], "불러온 순서");
    eq(await page.textContent("#status"), "총 7쪽 (파일 2개)", "상태 문구");
    const firstRow = await page.locator(".row").first().locator(".c-pos, .c-file, .c-page").allTextContents();
    eq(firstRow, ["1", "A.pdf", "1"], "행의 열 내용");
    console.log("3. 불러오기 OK");

    // ---------- 4. 범위를 지정해 불러오기, 잘못된 범위와 PDF가 아닌 파일 ----------
    await page.fill("#range", "3, 1");
    await input.setInputFiles([file("C.pdf", made.C), file("B2.pdf", made.B), file("note.txt", [104, 105], "text/plain")]);
    await page.waitForSelector("#notice:not([hidden])");
    const notice = await page.textContent("#notice");
    assert(notice.includes("C.pdf") && notice.includes("벗어납니다"), "C.pdf 범위 오류 안내: " + notice);
    assert(notice.includes("note.txt") && notice.includes("PDF 또는 이미지 파일이 아닙니다"), "PDF가 아닌 파일 안내: " + notice);
    eq((await state()).order.slice(7), ["B23", "B21"], "범위대로 추가");
    await page.fill("#range", "");
    console.log("4. 범위 지정, 오류 안내 OK");

    // ---------- 5. 썸네일과 미리보기 ----------
    await page.waitForFunction(() => document.querySelectorAll(".row .thumb img").length >= 3);
    const thumb = await page.evaluate(() => {
      const img = document.querySelector(".row .thumb img");
      return { w: img.naturalWidth, h: img.naturalHeight, dw: img.getBoundingClientRect().width };
    });
    assert(thumb.w > 0 && thumb.dw <= 72.5, "썸네일 크기 " + JSON.stringify(thumb));
    const rowBox = async (i) => page.locator(".row").nth(i).boundingBox();
    const clickRow = async (i, modifiers = []) => {
      await page.locator(".row").nth(i).scrollIntoViewIfNeeded();
      const b = await rowBox(i);
      await page.mouse.move(b.x + b.width / 2, b.y + b.height / 2);
      for (const k of modifiers) await page.keyboard.down(k);
      await page.mouse.down();
      await page.mouse.up();
      for (const k of modifiers) await page.keyboard.up(k);
    };
    await clickRow(1);
    if (await page.isVisible("#preview")) {
      await page.waitForFunction(() => {
        const c = document.querySelector("#preview canvas");
        return c && Number(c.dataset.id) === window.pdfTool.focus;
      });
      const pv = await page.locator("#preview canvas").boundingBox();
      const area = await page.locator("#preview").boundingBox();
      // 영역 안에 들어가고, 가로나 세로 중 한쪽은 영역에 거의 맞음
      assert(pv.width <= area.width && pv.height <= area.height &&
        (pv.width > area.width - 40 || pv.height > area.height - 40), "미리보기가 영역에 맞음 " + JSON.stringify({ pv, area }));
      // A를 보이는 중에 B를 고르고 곧바로 A로 돌아와도 미리보기는 A로 남아야 함
      const shownId = await page.evaluate(() => Number(document.querySelector("#preview canvas").dataset.id));
      await clickRow(3);
      await clickRow(1);
      await sleep(800);
      const after = await page.evaluate(() => ({ shown: Number(document.querySelector("#preview canvas").dataset.id), focus: window.pdfTool.focus }));
      eq(after, { shown: shownId, focus: shownId }, "빠르게 오간 뒤의 미리보기");
      console.log("5. 썸네일, 미리보기 OK");
    } else {
      console.log("5. 썸네일 OK (좁은 창이라 미리보기는 숨김)");
    }

    // ---------- 6. 선택 (클릭, Ctrl+클릭, Shift+클릭) ----------
    eq((await state()).selected, ["A2"], "클릭");
    await clickRow(3, ["Control"]);
    eq((await state()).selected, ["A2", "B1"], "Ctrl+클릭");
    await clickRow(0);
    await clickRow(2, ["Shift"]);
    eq((await state()).selected, ["A1", "A2", "A3"], "Shift+클릭");
    // 선택된 행을 끌지 않고 클릭하면 그 행 하나만 선택
    await clickRow(1);
    eq((await state()).selected, ["A2"], "선택된 행 클릭");
    console.log("6. 선택 OK");

    // ---------- 7. 드래그 정렬 ----------
    // 끄는 두 행이 함께 목록 안에 보여야 하므로 창이 낮으면 이 단계만 높이를 늘림
    // (목록 밖에서 놓는 경우는 12번의 자동 스크롤에서 검사함)
    if (size[1] < 750) await page.setViewportSize({ width: size[0], height: 750 });
    // 7-1. 한 행을 다른 행 앞(위쪽 가까이)으로
    async function dragRows(from, to, nearTop) {
      // 두 행이 모두 목록 안에 보이도록 위쪽 행을 목록 맨 위에 맞춤 (목록 밖에서 놓으면 자동 스크롤이 일어남)
      await page.evaluate((i) => {
        const h = document.querySelector(".row").getBoundingClientRect().height;
        document.getElementById("list").scrollTop = i * h;
      }, Math.min(from, to));
      const a = await rowBox(from);
      await page.mouse.move(a.x + a.width / 2, a.y + a.height / 2);
      await page.mouse.down();
      const b = await rowBox(to);
      const y = nearTop ? b.y + b.height * 0.25 : b.y + b.height * 0.75;
      await page.mouse.move(a.x + a.width / 2, y, { steps: 6 });
      await sleep(60);
      const shown = await page.isVisible("#indicator");
      await page.mouse.up();
      return shown;
    }
    // 창이 낮아도 두 행이 함께 보이도록 세 행 범위 안에서 끔
    await clickRow(4); // B2
    let shown = await dragRows(4, 2, true);
    assert(shown, "끄는 동안 빨간 표시선이 보여야 함");
    assert(!(await page.isVisible("#indicator")), "놓은 뒤 표시선 숨김");
    eq((await state()).order.slice(0, 7), ["A1", "A2", "B2", "A3", "B1", "B3", "B4"], "B2를 A3 앞으로");
    // 7-2. 여러 행 선택 후 끌면 상대 순서를 유지한 채 모임
    await clickRow(0);
    await clickRow(4, ["Control"]); // A1, B1
    await dragRows(4, 6, false);   // B1을 잡고 B4 뒤로
    eq((await state()).order.slice(0, 7), ["A2", "B2", "A3", "B3", "B4", "A1", "B1"], "여러 행 모으기");
    eq((await state()).selected, ["A1", "B1"], "옮긴 뒤에도 선택 유지");
    // 7-3. 같은 행 안에서만 움직이면 순서는 그대로
    const before7 = (await state()).order;
    await page.evaluate(() => (document.getElementById("list").scrollTop = 0));
    const b0 = await rowBox(0);
    await page.mouse.move(b0.x + 50, b0.y + 30);
    await page.mouse.down();
    await page.mouse.move(b0.x + 60, b0.y + 40, { steps: 3 });
    await page.mouse.up();
    eq((await state()).order, before7, "같은 행 안의 움직임은 클릭");
    eq((await state()).selected, ["A2"], "클릭으로 그 행만 선택");
    await page.setViewportSize({ width: size[0], height: size[1] });
    console.log("7. 드래그 정렬 OK");

    // ---------- 8. 실행 취소 / 다시 실행 ----------
    await page.locator("#list").focus();
    await page.keyboard.press("Control+z");
    eq((await state()).order.slice(0, 7), ["A1", "A2", "B2", "A3", "B1", "B3", "B4"], "실행 취소 1");
    await page.keyboard.press("Control+z");
    eq((await state()).order.slice(0, 7), ["A1", "A2", "A3", "B1", "B2", "B3", "B4"], "실행 취소 2");
    await page.keyboard.press("Control+y");
    eq((await state()).order.slice(0, 7), ["A1", "A2", "B2", "A3", "B1", "B3", "B4"], "다시 실행");
    await page.keyboard.press("Control+Shift+z");
    eq((await state()).order.slice(0, 7), ["A2", "B2", "A3", "B3", "B4", "A1", "B1"], "Ctrl+Shift+Z");
    console.log("8. 실행 취소 OK");

    // ---------- 9. 버튼: 위로, 아래로, 맨 위로, 맨 아래로, 위치 지정, 삭제 ----------
    await clickRow(2); // A3
    await page.click("#up-btn");
    eq((await state()).order.slice(0, 3), ["A2", "A3", "B2"], "위로");
    await page.click("#down-btn");
    eq((await state()).order.slice(0, 3), ["A2", "B2", "A3"], "아래로");
    await page.click("#top-btn");
    eq((await state()).order.slice(0, 3), ["A3", "A2", "B2"], "맨 위로");
    await page.click("#bottom-btn");
    eq((await state()).order.slice(-1), ["A3"], "맨 아래로");
    dialogAnswer = "2";
    await page.click("#moveto-btn");
    dialogAnswer = null;
    eq((await state()).order.slice(0, 3), ["A2", "A3", "B2"], "위치 지정 이동");
    const n9 = (await state()).order.length;
    await page.locator("#list").focus();
    await page.keyboard.press("Delete");
    eq((await state()).order.length, n9 - 1, "Delete 키로 삭제");
    assert(!(await state()).order.includes("A3"), "A3 삭제됨");
    await page.keyboard.press("Control+z");
    eq((await state()).order.slice(0, 3), ["A2", "A3", "B2"], "삭제 실행 취소");
    console.log("9. 버튼과 삭제 OK");

    // ---------- 10. 저장 (화면 순서 그대로, 같은 쪽 두 번) ----------
    async function readSaved(download) {
      const bytes = fs.readFileSync(await download.path());
      return page.evaluate(async (arr) => {
        const pdfjs = await import("./vendor/pdfjs/pdf.min.mjs");
        const doc = await pdfjs.getDocument({ data: new Uint8Array(arr) }).promise;
        const texts = [];
        for (let i = 1; i <= doc.numPages; i++) {
          const pg = await doc.getPage(i);
          const tc = await pg.getTextContent();
          const vp = pg.getViewport({ scale: 1 });
          texts.push(tc.items.map((x) => x.str).join("").trim() + (vp.width > vp.height ? "(가로)" : ""));
        }
        return texts;
      }, Array.from(bytes));
    }
    await page.click("#clear-btn");
    eq((await state()).order, [], "목록 비우기");
    await input.setInputFiles([file("A.pdf", made.A), file("B.pdf", made.B), file("C.pdf", made.C)]);
    await page.waitForFunction(() => window.pdfTool.order.length === 8);
    // 순서: B3, A1, C1, A1(B 파일에서 한 번 더 불러온 것이 아니라 같은 쪽을 두 번)
    await page.evaluate(() => 0);
    await clickRow(5); // B3
    await page.click("#top-btn");
    await clickRow(7); // C1
    await page.click("#top-btn");
    eq((await state()).order.slice(0, 3), ["C1", "B3", "A1"], "저장 전 순서");
    await page.fill("#filename", "결과");
    const [dl] = await Promise.all([page.waitForEvent("download"), page.click("#save-btn")]);
    eq(dl.suggestedFilename(), "결과.pdf", "확장자를 붙인 파일 이름");
    const saved = await readSaved(dl);
    eq(saved, ["C1(가로)", "B3", "A1", "A2", "A3", "B1", "B2", "B4"], "저장한 쪽 순서와 가로 쪽");
    await page.waitForFunction(() => !window.pdfTool.busy);
    assert((await page.textContent("#notice")).includes("총 8쪽"), "저장 완료 안내");
    // 같은 쪽 두 번: 범위 "1,1"로 A를 불러와 저장
    await page.click("#clear-btn");
    await page.fill("#range", "1, 1, 2");
    await input.setInputFiles([file("A.pdf", made.A)]);
    await page.waitForFunction(() => window.pdfTool.order.length === 3);
    await page.fill("#range", "");
    const [dl2] = await Promise.all([page.waitForEvent("download"), page.click("#save-btn")]);
    eq(await readSaved(dl2), ["A1", "A1", "A2"], "같은 쪽 두 번");
    const savedBytes = fs.readFileSync(await dl2.path());
    console.log(`10. 저장 OK (같은 쪽 두 번 저장한 파일 ${savedBytes.length}바이트)`);

    // ---------- 11. 비밀번호가 설정된 PDF ----------
    const hasEncrypt = await page.evaluate(async () => {
      const { PDFDocument } = await import("./vendor/pdf-lib/pdf-lib.esm.min.js");
      return typeof (await PDFDocument.create()).encrypt === "function";
    });
    if (hasEncrypt) {
      await page.evaluate(() => (document.getElementById("notice").hidden = true));
      await input.setInputFiles([file("P.pdf", made.P)]);
      await page.waitForSelector("#notice:not([hidden])");
      assert((await page.textContent("#notice")).includes("비밀번호"), "비밀번호 안내");
      eq((await state()).order.length, 3, "비밀번호 PDF는 추가하지 않음");
      // 비밀번호를 물을 때 콘솔에 남는 오류는 정상 동작이므로 제외
      for (let i = problems.length - 1; i >= 0; i--) if (/password|Worker was destroyed/i.test(problems[i])) problems.splice(i, 1);
      console.log("11. 비밀번호 PDF 안내 OK");
    } else {
      console.log("11. 건너뜀 (pdf-lib에 encrypt 없음)");
    }

    // ---------- 12. 끄는 동안 자동 스크롤 ----------
    await page.click("#clear-btn");
    const cacheBefore = await page.evaluate(() => window.pdfTool.thumbCacheSize);
    await input.setInputFiles([file("M.pdf", made.M)]);
    await page.waitForFunction(() => window.pdfTool.order.length === 40);
    await page.evaluate(() => (document.getElementById("list").scrollTop = 0));
    await sleep(800);
    // 지연 로딩: 40쪽 중 화면 근처의 쪽만 그렸는지
    const drawn = (await page.evaluate(() => window.pdfTool.thumbCacheSize)) - cacheBefore;
    assert(drawn > 0 && drawn < 15, "보이는 쪽만 썸네일을 그림: " + drawn);
    await clickRow(0);
    const a12 = await rowBox(0);
    const list = await page.locator("#list").boundingBox();
    await page.mouse.move(a12.x + a12.width / 2, a12.y + a12.height / 2);
    await page.mouse.down();
    await page.mouse.move(a12.x + a12.width / 2, list.y + list.height + 60, { steps: 8 });
    await page.waitForFunction(() => {
      const l = document.getElementById("list");
      return l.scrollTop + l.clientHeight >= l.scrollHeight - 1;
    }, null, { timeout: 15000 });
    await page.mouse.up();
    eq((await state()).order.slice(-1), ["M1"], "자동 스크롤 후 맨 끝에 놓기");
    console.log(`12. 자동 스크롤, 지연 로딩 OK (처음 화면에서 그린 썸네일 ${drawn}장)`);

    // ---------- 12-1. 불러오는 동안 편집을 막음 (실행 취소 기록이 섞이지 않게) ----------
    const during = await page.evaluate(async (arr) => {
      const dt = new DataTransfer();
      dt.items.add(new File([new Uint8Array(arr)], "A.pdf", { type: "application/pdf" }));
      window.dispatchEvent(new DragEvent("drop", { dataTransfer: dt, cancelable: true }));
      // drop 처리기는 첫 await 전에 busy를 켬
      return { busy: window.pdfTool.busy, clear: document.getElementById("clear-btn").disabled };
    }, made.A);
    eq(during, { busy: true, clear: true }, "불러오는 동안 busy와 버튼 비활성");
    await page.waitForFunction(() => !window.pdfTool.busy && window.pdfTool.order.length === 43);
    assert(!(await page.isDisabled("#clear-btn")), "불러온 뒤 버튼 다시 사용 가능");
    await page.locator("#list").focus();
    await page.keyboard.press("Control+z");
    eq((await state()).order.length, 40, "불러오기 실행 취소");
    console.log("12-1. 불러오는 동안 편집 막기 OK");

    // ---------- 13. 화면 배치: 저장 버튼과 진행 막대가 창 안에 보임 ----------
    for (const [w, h] of [[size[0], size[1]], [1100, 600], [800, 500], [640, 460], [1400, 750]]) {
      await page.setViewportSize({ width: w, height: h });
      await sleep(100);
      const ok = await page.evaluate(() => {
        const inView = (sel) => {
          const b = document.querySelector(sel).getBoundingClientRect();
          return b.width > 0 && b.top >= 0 && b.bottom <= window.innerHeight + 0.5 && b.right <= window.innerWidth + 0.5;
        };
        const listH = document.getElementById("list").clientHeight;
        // 다른 요소가 저장 버튼을 덮지 않는지 (목록이 넘쳐서 겹치는 경우)
        const sb = document.getElementById("save-btn").getBoundingClientRect();
        const hit = document.elementFromPoint(sb.left + sb.width / 2, sb.top + sb.height / 2);
        if (hit !== document.getElementById("save-btn")) return { save: false, covered: hit && hit.outerHTML.slice(0, 60) };
        return { save: inView("#save-btn"), progress: inView("#progress"), open: inView("#open-btn"), listH,
          scrollX: document.documentElement.scrollWidth <= window.innerWidth };
      });
      assert(ok.save && ok.progress && ok.open, `${w}x${h}: 버튼이 창 안에 있어야 함 ${JSON.stringify(ok)}`);
      assert(ok.listH >= 110, `${w}x${h}: 목록이 한 행 이상 보여야 함 ${ok.listH}`);
      assert(ok.scrollX, `${w}x${h}: 가로 스크롤이 생기면 안 됨`);
    }
    console.log("13. 화면 배치 OK");

    eq(problems, [], "콘솔 오류와 실패한 요청");
    console.log("모든 웹판 테스트 통과");
  } finally {
    await env.close();
  }
}

main().catch((e) => {
  console.error(e.stack || e);
  process.exit(1);
});
