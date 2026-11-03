// PDF 도구 웹판의 화면. 데스크톱판(pdf_common.PageTab, DragTree)의 동작을 브라우저로 옮긴 것입니다.
// 처리는 모두 브라우저 안에서 하며 파일을 서버로 보내지 않습니다.

import { parsePageRanges, PageRangeError } from "./ranges.js";
import { gatherSelection, slotToPos, shiftSelection, moveSelectionTo } from "./order.js";
import { openPdf, renderPage, savePages, PdfOpenError, PDFJS_VERSION } from "./pdfio.js";
import { isImageFile, imageToPdf, ImageError } from "./imageimport.js";
import { DPI_CHOICES, DEFAULT_DPI, DEFAULT_QUALITY, imageFileNames, encodePng, encodeJpg, makeZip } from "./imageexport.js";
import { APP_VERSION, PDF_LIB_VERSION } from "./version.js";

const UNDO_LIMIT = 100;      // 실행 취소 최대 단계 수 (데스크톱판과 같음)
const THUMB_SCALE = 0.12;    // 썸네일 배율 (데스크톱판과 같음)
const THUMB_CACHE = 300;     // 썸네일 보관 개수 (데스크톱판과 같음)
const FLASH_MS = 400;        // 옮긴 직후 강조색을 보여 주는 시간
const IS_MAC = /Mac|iPhone|iPad/.test(navigator.platform);
const MOD = IS_MAC ? "Cmd" : "Ctrl";

const $ = (id) => document.getElementById(id);
const el = {
  list: $("list"), rows: $("rows"), indicator: $("indicator"), empty: $("empty"),
  preview: $("preview"), status: $("status"), notice: $("notice"), progress: $("progress"),
  range: $("range"), fileInput: $("file-input"), filename: $("filename"),
  menubar: $("menubar"), contextMenu: $("context-menu"),
  keepOutlines: $("keep-outlines"), fileBookmarks: $("file-bookmarks"),
};

// ---------------------------------------------------------------------------
// 상태
// ---------------------------------------------------------------------------
let nextId = 1;
const pages = new Map();   // 행 ID -> { source, index } (index는 0부터)
let order = [];            // 화면 순서의 행 ID
let selected = new Set();  // 선택한 행 ID
let anchor = null;         // Shift+클릭 범위의 기준 행
let focusId = null;        // 마지막으로 클릭한 행 (미리보기 대상)
let undoStack = [];        // 작업 직전의 쪽 목록 [{ source, index }, ...]
let redoStack = [];
let busy = false;          // 불러오기, 저장 중
const rowEls = new Map();  // 행 ID -> 행 요소

// 디버그와 자동 시험용으로 상태를 읽을 수 있게 함
window.pdfTool = {
  get order() { return order.slice(); },
  get selected() { return order.filter((id) => selected.has(id)); },
  get focus() { return focusId; },
  pageOf: (id) => { const p = pages.get(id); return p && { file: p.source.name, page: p.index + 1 }; },
  get busy() { return busy; },
  get thumbCacheSize() { return thumbCache.size; },
  get undoDepth() { return undoStack.length; },
};

function rowHeight() {
  return parseFloat(getComputedStyle(document.documentElement).getPropertyValue("--row-h")) || 110;
}

// ---------------------------------------------------------------------------
// 알림
// ---------------------------------------------------------------------------
let noticeTimer = null;
function notify(text, kind = "info") {
  el.notice.textContent = text;
  el.notice.className = `notice ${kind === "info" ? "" : kind}`;
  el.notice.hidden = false;
  el.notice.dataset.kind = kind;
  clearTimeout(noticeTimer);
  if (kind === "info") noticeTimer = setTimeout(() => (el.notice.hidden = true), 6000);
}

// ---------------------------------------------------------------------------
// 목록 그리기
// ---------------------------------------------------------------------------
function makeRow(id) {
  const p = pages.get(id);
  const row = document.createElement("div");
  row.className = "row";
  row.dataset.id = id;
  row.setAttribute("role", "option");
  row.innerHTML = '<span class="c-thumb"><span class="thumb pending"></span></span>' +
    '<span class="c-pos"></span><span class="c-file"></span><span class="c-page"></span>';
  row.querySelector(".c-file").textContent = p.source.name;
  row.querySelector(".c-file").title = p.source.name;
  row.querySelector(".c-page").textContent = String(p.index + 1);
  rowEls.set(id, row);
  thumbObserver.observe(row);
  return row;
}

/** order에 맞게 행 요소를 다시 배치하고 번호, 선택 표시, 상태 문구를 갱신합니다. */
function refresh() {
  for (const [id, row] of rowEls) {
    if (!pages.has(id)) {
      thumbObserver.unobserve(row);
      row.remove();
      rowEls.delete(id);
    }
  }
  const frag = document.createDocumentFragment();
  order.forEach((id, i) => {
    const row = rowEls.get(id) || makeRow(id);
    row.querySelector(".c-pos").textContent = String(i + 1);
    row.classList.toggle("selected", selected.has(id));
    row.setAttribute("aria-selected", selected.has(id) ? "true" : "false");
    frag.appendChild(row);
  });
  el.rows.replaceChildren(frag);
  el.empty.hidden = order.length > 0;
  const files = new Set(order.map((id) => pages.get(id).source)).size;
  el.status.textContent = `총 ${order.length}쪽` + (files > 1 ? ` (파일 ${files}개)` : "");
  updateButtons();
  schedulePreview();
}

function updateSelectionView() {
  for (const [id, row] of rowEls) {
    row.classList.toggle("selected", selected.has(id));
    row.setAttribute("aria-selected", selected.has(id) ? "true" : "false");
  }
  updateButtons();
}

function updateButtons() {
  const has = order.length > 0;
  const sel = selected.size > 0;
  const set = (id, on) => ($(id).disabled = busy || !on);
  set("open-btn", true);
  for (const id of ["delete-btn", "up-btn", "down-btn", "top-btn", "bottom-btn", "moveto-btn"]) set(id, sel);
  set("selectall-btn", has);
  set("clear-btn", has);
  set("save-btn", has);
  set("images-btn", has);
}

/** 선택한 행 중 첫 행이 보이도록 스크롤합니다. */
function revealSelection() {
  const first = order.find((id) => selected.has(id));
  if (!first) return;
  const top = order.indexOf(first) * rowHeight();
  const last = order.length - 1 - [...order].reverse().findIndex((id) => selected.has(id));
  const bottom = (last + 1) * rowHeight();
  const view = el.list;
  if (top < view.scrollTop) view.scrollTop = top;
  else if (bottom > view.scrollTop + view.clientHeight) {
    view.scrollTop = Math.min(top, bottom - view.clientHeight);
  }
}

function flashSelection() {
  const rows = [...selected].map((id) => rowEls.get(id)).filter(Boolean);
  rows.forEach((r) => r.classList.add("flash"));
  setTimeout(() => rows.forEach((r) => r.classList.remove("flash")), FLASH_MS);
}

// ---------------------------------------------------------------------------
// 실행 취소
// ---------------------------------------------------------------------------
function snapshot() {
  return order.map((id) => pages.get(id));
}

function pushUndo(snap) {
  undoStack.push(snap);
  if (undoStack.length > UNDO_LIMIT) undoStack.splice(0, undoStack.length - UNDO_LIMIT);
  redoStack = [];
}

function restore(snap) {
  const top = el.list.scrollTop; // 스크롤 위치 유지
  pages.clear();
  order = snap.map((p) => {
    const id = nextId++;
    pages.set(id, p);
    return id;
  });
  selected = new Set();
  anchor = focusId = null;
  refresh();
  el.list.scrollTop = top;
}

function undo() {
  if (busy || !undoStack.length) return;
  redoStack.push(snapshot());
  restore(undoStack.pop());
}

function redo() {
  if (busy || !redoStack.length) return;
  undoStack.push(snapshot());
  restore(redoStack.pop());
}

/** 순서 변경 함수의 결과(새 순서 또는 null)를 반영합니다. */
function applyOrder(next) {
  if (!next) return false;
  pushUndo(snapshot());
  order = next;
  refresh();
  revealSelection();
  flashSelection();
  return true;
}

// ---------------------------------------------------------------------------
// 불러오기
// ---------------------------------------------------------------------------
async function loadFiles(files) {
  if (busy || !files.length) return;
  const rangeText = el.range.value;
  const before = snapshot();
  const errors = [];
  let added = 0;
  let firstNew = null;
  // 불러오는 동안 다른 편집과 불러오기를 막음. 막지 않으면 위의 before를 찍은 뒤에 일어난 편집이
  // 이 불러오기의 실행 취소에 섞여서, 실행 취소가 관계없는 편집까지 되돌림
  busy = true;
  updateButtons();
  document.body.style.cursor = "progress";
  try {
    for (const file of files) {
      let indices, source;
      try {
        const image = isImageFile(file.name);
        if (!image && !/\.pdf$/i.test(file.name) && file.type !== "application/pdf") {
          throw new PdfOpenError("PDF 또는 이미지 파일이 아닙니다.");
        }
        let bytes = new Uint8Array(await file.arrayBuffer());
        // 이미지는 PDF로 바꿔서 PDF와 똑같이 다룸. 쪽 범위는 PDF에만 적용함 (데스크톱판과 같음)
        if (image) bytes = await imageToPdf(bytes, file.name);
        const doc = await openPdf(bytes);
        indices = image ? [...Array(doc.numPages).keys()] : parsePageRanges(rangeText, doc.numPages);
        source = { name: file.name, bytes, doc, image };
      } catch (e) {
        if (e instanceof PdfOpenError || e instanceof PageRangeError || e instanceof ImageError) {
          errors.push(`${file.name}: ${e.message}`);
          continue;
        }
        throw e;
      }
      for (const index of indices) {
        const id = nextId++;
        pages.set(id, { source, index });
        order.push(id);
        firstNew = firstNew || id;
      }
      added += indices.length;
    }
  } finally {
    document.body.style.cursor = "";
    busy = false;
    updateButtons();
  }
  if (added) pushUndo(before);
  refresh();
  if (firstNew) el.list.scrollTop = Math.max(0, order.indexOf(firstNew) * rowHeight() - rowHeight());
  if (errors.length) notify("일부 파일을 추가하지 못했습니다.\n" + errors.join("\n"), "warn");
}

// ---------------------------------------------------------------------------
// 편집
// ---------------------------------------------------------------------------
function deleteSelected() {
  if (busy || !selected.size) return;
  pushUndo(snapshot());
  order = order.filter((id) => !selected.has(id));
  for (const id of selected) pages.delete(id);
  selected = new Set();
  if (!pages.has(focusId)) focusId = null;
  refresh();
}

function clearAll() {
  if (busy || !order.length) return;
  pushUndo(snapshot());
  order = [];
  pages.clear();
  selected = new Set();
  anchor = focusId = null;
  refresh();
}

function selectAll() {
  selected = new Set(order);
  updateSelectionView();
}

function shift(step) {
  if (!busy) applyOrder(shiftSelection(order, selected, step));
}

function moveTo(position) {
  if (!busy) applyOrder(moveSelectionTo(order, selected, position));
}

function moveToDialog() {
  if (busy) return;
  if (!selected.size) {
    notify("이동할 쪽을 먼저 선택해 주세요.");
    return;
  }
  const answer = window.prompt(`선택한 쪽을 몇 번째 위치로 옮길까요? (1~${order.length})`, "1");
  if (answer === null) return;
  const pos = Number(answer.trim());
  if (!Number.isInteger(pos) || pos < 1 || pos > order.length) {
    notify(`1부터 ${order.length} 사이의 정수를 입력해 주세요.`, "error");
    return;
  }
  moveTo(pos);
}

// ---------------------------------------------------------------------------
// 저장
// ---------------------------------------------------------------------------
/** Blob을 name이라는 이름으로 내려받게 합니다. */
function download(blob, name) {
  const url = URL.createObjectURL(blob);
  const a = document.createElement("a");
  a.href = url;
  a.download = name;
  document.body.appendChild(a);
  a.click();
  a.remove();
  setTimeout(() => URL.revokeObjectURL(url), 60000);
}

async function save() {
  if (busy) return;
  if (!order.length) {
    notify("저장할 쪽이 없습니다. 먼저 PDF나 이미지를 불러와 주세요.");
    return;
  }
  let name = el.filename.value.trim() || "extracted.pdf";
  if (!/\.pdf$/i.test(name)) name += ".pdf";
  const list = snapshot();
  busy = true;
  updateButtons();
  el.progress.value = 0;
  try {
    const options = { keepOutlines: el.keepOutlines.checked, fileBookmarks: el.fileBookmarks.checked };
    const bytes = await savePages(list, options, (n, total) => (el.progress.value = Math.round((n / total) * 90)));
    download(new Blob([bytes], { type: "application/pdf" }), name);
    el.progress.value = 100;
    notify(`저장이 완료되었습니다. 총 ${list.length}쪽\n${name} (브라우저의 다운로드 폴더를 확인해 주세요)`);
  } catch (e) {
    notify(`저장 실패: ${e && e.message ? e.message : e}`, "error");
  } finally {
    busy = false;
    updateButtons();
  }
}

// ---------------------------------------------------------------------------
// 썸네일 (화면에 보이는 행만 그림)
// ---------------------------------------------------------------------------
const thumbCache = new Map();  // "원본번호:쪽" -> 그림 URL (Map의 순서를 최근 사용 순서로 씀)
const thumbFailed = new Set();
const thumbQueue = new Set();  // 그려야 할 행 ID
const visibleRows = new Set();
let thumbRunning = false;
let sourceSeq = 0;
const sourceKey = new WeakMap();

function thumbKey(p) {
  if (!sourceKey.has(p.source)) sourceKey.set(p.source, ++sourceSeq);
  return `${sourceKey.get(p.source)}:${p.index}`;
}

const thumbObserver = new IntersectionObserver((entries) => {
  for (const entry of entries) {
    const id = Number(entry.target.dataset.id);
    if (entry.isIntersecting) {
      visibleRows.add(id);
      thumbQueue.add(id);
    } else {
      visibleRows.delete(id);
      thumbQueue.delete(id);
    }
  }
  pumpThumbs();
}, { root: el.list, rootMargin: "220px 0px" }); // 위아래 2행 정도를 미리 그림

function showThumb(id, url) {
  const row = rowEls.get(id);
  if (!row) return;
  const box = row.querySelector(".thumb");
  box.classList.remove("pending", "failed");
  let img = box.querySelector("img");
  if (!img) {
    img = document.createElement("img");
    img.alt = "";
    box.appendChild(img);
  }
  if (img.src !== url) img.src = url;
}

function evictThumbs() {
  while (thumbCache.size > THUMB_CACHE) {
    const [key, url] = thumbCache.entries().next().value;
    thumbCache.delete(key);
    URL.revokeObjectURL(url);
    // 버린 그림을 붙인 행에서 떼어 냄 (데스크톱판 _on_thumb_evicted와 같음)
    for (const [id, row] of rowEls) {
      const p = pages.get(id);
      if (p && thumbKey(p) === key) {
        const box = row.querySelector(".thumb");
        box.replaceChildren();
        box.classList.add("pending");
        if (visibleRows.has(id)) thumbQueue.add(id);
      }
    }
  }
}

async function pumpThumbs() {
  if (thumbRunning) return;
  thumbRunning = true;
  try {
    while (thumbQueue.size) {
      const id = thumbQueue.values().next().value;
      thumbQueue.delete(id);
      const p = pages.get(id);
      if (!p || !visibleRows.has(id)) continue;
      const key = thumbKey(p);
      if (thumbCache.has(key)) {
        const url = thumbCache.get(key);
        thumbCache.delete(key);
        thumbCache.set(key, url); // 최근 사용으로 옮김
        showThumb(id, url);
        continue;
      }
      if (thumbFailed.has(key)) {
        rowEls.get(id)?.querySelector(".thumb").classList.replace("pending", "failed");
        continue;
      }
      try {
        const page = await p.source.doc.getPage(p.index + 1);
        const vp = page.getViewport({ scale: 1 });
        const box = { w: 72, h: 102 };
        const scale = Math.min(THUMB_SCALE, box.w / vp.width, box.h / vp.height) * (window.devicePixelRatio || 1);
        const canvas = await renderPage(p.source.doc, p.index, scale).promise;
        const blob = await new Promise((res) => canvas.toBlob(res, "image/png"));
        const url = URL.createObjectURL(blob);
        thumbCache.set(key, url);
        evictThumbs();
        // 같은 쪽이 여러 행에 있으면 보이는 행 모두에 붙임
        for (const vid of visibleRows) {
          const q = pages.get(vid);
          if (q && thumbKey(q) === key) showThumb(vid, url);
        }
      } catch (e) {
        thumbFailed.add(key); // 그리지 못한 쪽은 회색 칸으로 두고 다시 시도하지 않음
        rowEls.get(id)?.querySelector(".thumb").classList.replace("pending", "failed");
      }
    }
  } finally {
    thumbRunning = false;
  }
}

// ---------------------------------------------------------------------------
// 미리보기 (포커스 행, 없으면 선택한 첫 행)
// ---------------------------------------------------------------------------
let previewTimer = null;
let previewTask = null;
let previewShown = null;
let previewReq = 0;        // 미리보기 요청 번호. 늦게 끝난 이전 요청의 결과를 버리는 데 씀

function schedulePreview(delay = 0) {
  clearTimeout(previewTimer);
  previewTimer = setTimeout(drawPreview, delay);
}

async function drawPreview() {
  const id = pages.has(focusId) ? focusId : order.find((x) => selected.has(x));
  const p = id && pages.get(id);
  const w = el.preview.clientWidth - 16;
  const h = el.preview.clientHeight - 16;
  const key = p ? `${thumbKey(p)}@${w}x${h}` : null;
  // 이전 요청은 결과가 같든 다르든 먼저 무효로 함. A를 보이는 중에 B를 고르고 다시 A를 고르면
  // 아래의 조기 반환으로 끝나는데, 이때 B의 그리기가 남아 있으면 끝난 뒤에 B로 바뀜
  const req = ++previewReq;
  if (previewTask) previewTask.cancel();
  previewTask = null;
  if (key === previewShown) return;
  if (!p || w < 20 || h < 20) {
    el.preview.replaceChildren();
    previewShown = key;
    return;
  }
  try {
    const page = await p.source.doc.getPage(p.index + 1);
    if (req !== previewReq) return;
    const vp = page.getViewport({ scale: 1 });
    const fit = Math.min(w / vp.width, h / vp.height);
    const dpr = window.devicePixelRatio || 1;
    const task = renderPage(p.source.doc, p.index, fit * dpr);
    previewTask = task;
    const canvas = await task.promise;
    if (req !== previewReq) return;
    canvas.style.width = `${Math.round(vp.width * fit)}px`;
    canvas.style.height = `${Math.round(vp.height * fit)}px`;
    canvas.dataset.id = id;
    el.preview.replaceChildren(canvas);
    previewShown = key;
  } catch (e) {
    // 다른 쪽으로 바뀌어 취소된 경우 등은 무시함
  }
}

new ResizeObserver(() => schedulePreview(150)).observe(el.preview);

// ---------------------------------------------------------------------------
// 마우스: 선택과 드래그 (데스크톱판 DragTree와 같은 규칙)
// ---------------------------------------------------------------------------
const drag = { active: false, moved: false, pressId: null, lastY: 0, timer: null, pointerId: null };

function rowIdAt(clientY) {
  const rect = el.list.getBoundingClientRect();
  const y = clientY - rect.top + el.list.scrollTop;
  const i = Math.floor(y / rowHeight());
  return i >= 0 && i < order.length ? order[i] : null;
}

/**
 * 마우스 y 좌표에 놓으면 들어갈 자리(행 사이의 경계 번호, 0부터)를 돌려줍니다.
 * 행의 위쪽 절반이면 그 행 앞, 아래쪽 절반이면 그 행 뒤입니다.
 */
function dropSlot(clientY) {
  const rect = el.list.getBoundingClientRect();
  const h = rowHeight();
  const top = el.list.scrollTop;
  const y = Math.min(Math.max(clientY - rect.top, 0), el.list.clientHeight - 1) + top;
  return Math.min(Math.max(Math.floor((y + h / 2) / h), 0), order.length);
}

function updateIndicator() {
  if (!drag.active || !drag.moved) {
    el.indicator.hidden = true;
    return;
  }
  const slot = dropSlot(drag.lastY);
  el.indicator.style.top = `${slot * rowHeight() - 1}px`;
  el.indicator.hidden = false;
}

function autoScroll() {
  const rect = el.list.getBoundingClientRect();
  const y = drag.lastY;
  const h = rowHeight();
  if (y < rect.top) el.list.scrollTop -= (1 + Math.floor((rect.top - y) / 10)) * h / 4;
  else if (y > rect.bottom) el.list.scrollTop += (1 + Math.floor((y - rect.bottom) / 10)) * h / 4;
}

function setFocus(id) {
  if (focusId !== id) {
    focusId = id;
    schedulePreview();
  }
}

el.list.addEventListener("pointerdown", (ev) => {
  if (ev.button !== 0 || busy) return;
  el.list.focus({ preventScroll: true });
  const id = rowIdAt(ev.clientY);
  // 스크롤 막대를 누른 경우는 브라우저에 맡김
  if (ev.clientX > el.list.getBoundingClientRect().left + el.list.clientWidth) return;
  ev.preventDefault();
  if (!id) {
    selected = new Set();
    updateSelectionView();
    return;
  }
  setFocus(id);
  if (IS_MAC ? ev.metaKey : ev.ctrlKey) {
    selected.has(id) ? selected.delete(id) : selected.add(id);
    anchor = id;
    updateSelectionView();
    return;
  }
  if (ev.shiftKey && anchor && pages.has(anchor)) {
    const [a, b] = [order.indexOf(anchor), order.indexOf(id)].sort((x, y) => x - y);
    selected = new Set(order.slice(a, b + 1));
    updateSelectionView();
    return;
  }
  // 이미 선택된 행을 누르면 선택을 유지한 채 끌 수 있게 함 (여러 행 동시 이동)
  if (!selected.has(id)) {
    selected = new Set([id]);
    updateSelectionView();
  }
  anchor = id;
  Object.assign(drag, { active: true, moved: false, pressId: id, lastY: ev.clientY, pointerId: ev.pointerId });
  el.list.setPointerCapture(ev.pointerId);
  drag.timer = setInterval(() => {
    autoScroll();
    updateIndicator();
  }, 30);
});

el.list.addEventListener("pointermove", (ev) => {
  if (!drag.active) return;
  drag.lastY = ev.clientY;
  // 누른 행을 벗어나야 드래그로 간주함 (같은 행 안에서 조금 움직인 것은 클릭으로 처리)
  if (!drag.moved && rowIdAt(ev.clientY) !== drag.pressId) drag.moved = true;
  updateIndicator();
});

function endDrag(ev, cancelled) {
  if (!drag.active) return;
  drag.active = false;
  clearInterval(drag.timer);
  el.indicator.hidden = true;
  if (el.list.hasPointerCapture(drag.pointerId)) el.list.releasePointerCapture(drag.pointerId);
  if (cancelled) return;
  if (!drag.moved) {
    // 끌지 않고 클릭만 했다면 그 행 하나만 선택
    if (pages.has(drag.pressId)) {
      selected = new Set([drag.pressId]);
      updateSelectionView();
    }
    return;
  }
  const slot = dropSlot(ev.clientY);
  applyOrder(gatherSelection(order, selected, slotToPos(order, selected, slot)));
}

el.list.addEventListener("pointerup", (ev) => endDrag(ev, false));
el.list.addEventListener("pointercancel", (ev) => endDrag(ev, true));

// ---------------------------------------------------------------------------
// 목록과 미리보기 사이의 폭 조절
// ---------------------------------------------------------------------------
$("splitter").addEventListener("pointerdown", (ev) => {
  const wrap = document.querySelector(".list-wrap");
  const startX = ev.clientX;
  const startW = wrap.getBoundingClientRect().width;
  const move = (e) => document.documentElement.style.setProperty("--list-w", `${Math.max(260, startW + e.clientX - startX)}px`);
  const up = () => {
    window.removeEventListener("pointermove", move);
    window.removeEventListener("pointerup", up);
    schedulePreview(150);
  };
  window.addEventListener("pointermove", move);
  window.addEventListener("pointerup", up);
  ev.preventDefault();
});

// ---------------------------------------------------------------------------
// 이미지로 저장 (데스크톱판 렌더링판의 save_images, ImageSaveDialog와 같은 선택지)
// ---------------------------------------------------------------------------
const imageDialog = {
  dialog: $("image-dialog"), form: $("image-form"), quality: $("jpg-quality"), dpi: $("dpi"),
  error: $("image-error"), cancel: $("image-cancel"),
};
for (const dpi of DPI_CHOICES) imageDialog.dpi.add(new Option(String(dpi), String(dpi), false, dpi === DEFAULT_DPI));

/** 이미지 저장 대화 상자를 띄우고, 고른 옵션 { scope, format, dpi, quality } 또는 취소하면 null을 돌려줍니다. */
function askImageOptions(nSelected, nAll) {
  const d = imageDialog;
  const radio = (name, value) => d.form.querySelector(`input[name="${name}"][value="${value}"]`);
  $("scope-selected-label").textContent = `선택한 쪽 (${nSelected}쪽)`;
  $("scope-all-label").textContent = `목록 전체 (${nAll}쪽)`;
  radio("scope", "selected").disabled = nSelected === 0;
  radio("scope", nSelected ? "selected" : "all").checked = true;
  d.error.hidden = true;
  return new Promise((resolve) => {
    let result = null;
    const onSubmit = (ev) => {
      const format = d.form.querySelector('input[name="format"]:checked').value;
      const quality = Number(d.quality.value);
      if (format === "jpg" && !(Number.isInteger(quality) && quality >= 1 && quality <= 95)) {
        ev.preventDefault();
        d.error.textContent = "JPG 품질은 1부터 95 사이의 숫자로 입력해 주세요.";
        d.error.hidden = false;
        d.quality.focus();
        return;
      }
      result = {
        scope: d.form.querySelector('input[name="scope"]:checked').value,
        format, quality, dpi: Number(d.dpi.value),
      };
    };
    const onCancel = () => d.dialog.close();
    const onClose = () => {
      d.form.removeEventListener("submit", onSubmit);
      d.cancel.removeEventListener("click", onCancel);
      d.dialog.removeEventListener("close", onClose);
      resolve(result);
    };
    d.form.addEventListener("submit", onSubmit);
    d.cancel.addEventListener("click", onCancel);
    d.dialog.addEventListener("close", onClose);
    d.dialog.showModal();
  });
}

const stemOf = (name) => name.replace(/\.[^.]*$/, "");

async function saveImages() {
  if (busy) return;
  if (!order.length) {
    notify("저장할 쪽이 없습니다. 먼저 PDF나 이미지를 불러와 주세요.");
    return;
  }
  const opts = await askImageOptions(selected.size, order.length);
  if (!opts || busy) return;
  const ids = opts.scope === "selected" ? order.filter((id) => selected.has(id)) : order.slice();
  if (!ids.length) return;
  const list = ids.map((id) => pages.get(id));
  const ext = opts.format;
  const names = imageFileNames(list.map((p) => ({ name: p.source.name, index: p.index })), ext);
  busy = true;
  updateButtons();
  el.progress.value = 0;
  const files = [];
  let failed = null;
  try {
    for (let i = 0; i < list.length; i++) {
      const p = list[i];
      try {
        const canvas = await renderPage(p.source.doc, p.index, opts.dpi / 72).promise;
        const data = ext === "png" ? await encodePng(canvas, opts.dpi) : await encodeJpg(canvas, opts.dpi, opts.quality);
        canvas.width = canvas.height = 0; // 큰 그림의 메모리를 바로 돌려줌
        files.push({ name: names[i], data });
      } catch (e) {
        failed = `${p.source.name} ${p.index + 1}쪽: ${e && e.message ? e.message : e}`;
        break;
      }
      el.progress.value = Math.round(((i + 1) / list.length) * 95);
    }
    if (failed) {
      notify(`이미지 저장 실패\n${failed}\n\n내려받은 파일은 없습니다.`, "error");
      return;
    }
    let name;
    if (files.length === 1) {
      name = files[0].name;
      download(new Blob([files[0].data], { type: ext === "png" ? "image/png" : "image/jpeg" }), name);
    } else {
      // 브라우저는 폴더에 여러 파일을 바로 쓸 수 없으므로 zip 하나로 내려받음
      const sources = new Set(list.map((p) => p.source));
      const stem = sources.size === 1 ? stemOf(list[0].source.name) : stemOf(el.filename.value.trim() || "extracted.pdf");
      name = `${stem}_images.zip`;
      download(makeZip(files), name);
    }
    el.progress.value = 100;
    notify(`이미지 ${files.length}개를 저장했습니다.\n${name} (브라우저의 다운로드 폴더를 확인해 주세요)`);
  } finally {
    busy = false;
    updateButtons();
  }
}

// ---------------------------------------------------------------------------
// 도움말
// ---------------------------------------------------------------------------
function showInfo(title, lines) {
  $("info-title").textContent = title;
  const table = document.createElement("table");
  for (const line of lines) {
    const tr = table.insertRow();
    const [a, b] = line.split("\t");
    if (b === undefined) {
      const td = tr.insertCell();
      td.colSpan = 2;
      td.textContent = a || " ";
    } else {
      tr.insertCell().textContent = a;
      tr.insertCell().textContent = b;
    }
  }
  $("info-body").replaceChildren(table);
  $("info-dialog").showModal();
}
$("info-close").addEventListener("click", () => $("info-dialog").close());

function showShortcuts() {
  showInfo("단축키와 마우스 사용법", [
    `${MOD}+O\tPDF/이미지 불러오기`,
    `${MOD}+S\t새 PDF로 저장`,
    `${MOD}+Z\t실행 취소 (최대 ${UNDO_LIMIT}단계)`,
    `${MOD}+Y, ${MOD}+Shift+Z\t다시 실행`,
    `${MOD}+A\t전체 선택 (쪽 목록에서)`,
    "Delete\t선택 삭제 (쪽 목록에서)",
    "",
    "마우스로 행을 끌기\t순서 바꾸기 (선택한 쪽들이 놓은 위치에 모임)",
    `${MOD}+클릭\t쪽을 하나씩 선택에 더하거나 빼기`,
    "Shift+클릭\t범위 선택",
    "우클릭\t쪽 메뉴 (이 파일의 쪽 모두 선택, 이동, 삭제, 이미지로 저장)",
    "파일을 창에 끌어다 놓기\t불러오기",
  ]);
}

function showAbout() {
  showInfo("프로그램 정보", [
    `PDF 도구 ${APP_VERSION} (웹판)`,
    "",
    `pdf.js\t${PDFJS_VERSION}`,
    `pdf-lib (@cantoo/pdf-lib)\t${PDF_LIB_VERSION}`,
    `브라우저\t${navigator.userAgent}`,
    "",
    "파일은 이 브라우저 안에서만 처리하며 어디에도 올리지 않습니다.",
  ]);
}

// ---------------------------------------------------------------------------
// 메뉴 막대와 우클릭 메뉴 (데스크톱판 menu_items, context_menu_items와 같은 구성)
// 항목은 [이름, 동작, 단축키 표시, 조건] 또는 null(구분선)입니다. 조건은 데스크톱판 _menu_condition과 같습니다.
// ---------------------------------------------------------------------------
let contextRow = null;  // 우클릭한 행 ID (행이 아닌 곳이면 null)

const openFiles = () => { if (!busy) el.fileInput.click(); };
const moveItems = () => [
  ["위로", () => shift(-1), null, "selection"],
  ["아래로", () => shift(1), null, "selection"],
  ["맨 위로", () => moveTo(1), null, "selection"],
  ["맨 아래로", () => moveTo(Number.MAX_SAFE_INTEGER), null, "selection"],
  ["위치 지정 이동...", moveToDialog, null, "selection"],
];

function menuItems() {
  return [
    ["파일", [
      ["PDF/이미지 불러오기...", openFiles, `${MOD}+O`, null],
      ["새 PDF로 저장...", save, `${MOD}+S`, "rows"],
      ["이미지로 저장...", saveImages, null, "rows"],
    ]],
    ["편집", [
      ["실행 취소", undo, `${MOD}+Z`, "undo"],
      ["다시 실행", redo, `${MOD}+Y`, "redo"],
      null,
      ["전체 선택", selectAll, `${MOD}+A`, "rows"],
      ["선택 삭제", deleteSelected, "Delete", "selection"],
      null,
      ...moveItems(),
      null,
      ["목록 비우기", clearAll, null, "rows"],
    ]],
    ["도움말", [
      ["단축키와 마우스 사용법", showShortcuts, null, "always"],
      ["프로그램 정보", showAbout, null, "always"],
    ]],
  ];
}

function contextMenuItems() {
  const p = contextRow && pages.get(contextRow);
  return [
    [p ? `이 파일의 쪽 모두 선택 (${p.source.name})` : "이 파일의 쪽 모두 선택", selectFilePages, null, "row"],
    null,
    ...moveItems(),
    null,
    ["선택 삭제", deleteSelected, "Delete", "selection"],
    null,
    ["이미지로 저장...", saveImages, null, "rows"],
  ];
}

function menuCondition(cond) {
  if (cond === "always") return true;
  if (busy) return false;
  if (cond === "rows") return order.length > 0;
  if (cond === "selection") return selected.size > 0;
  if (cond === "undo") return undoStack.length > 0;
  if (cond === "redo") return redoStack.length > 0;
  if (cond === "row") return contextRow !== null && pages.has(contextRow);
  return true;
}

/** 메뉴 요소(box)를 items로 채웁니다. 항목의 사용 가능 여부는 채울 때 정합니다(메뉴를 열 때마다 다시 채움). */
function fillMenu(box, items) {
  box.replaceChildren();
  for (const item of items) {
    if (!item) {
      box.appendChild(document.createElement("hr"));
      continue;
    }
    const [label, action, accel, cond] = item;
    const b = document.createElement("button");
    b.type = "button";
    b.setAttribute("role", "menuitem");
    b.dataset.label = label;
    const text = document.createElement("span");
    text.textContent = label;
    b.appendChild(text);
    if (accel) {
      const a = document.createElement("span");
      a.className = "accel";
      a.textContent = accel;
      b.appendChild(a);
    }
    b.disabled = !menuCondition(cond);
    b.addEventListener("click", () => {
      closeMenus();
      action();
    });
    box.appendChild(b);
  }
}

const dropdown = document.createElement("div"); // 메뉴 막대에서 연 메뉴
dropdown.className = "menu";
dropdown.id = "dropdown-menu";
dropdown.setAttribute("role", "menu");
dropdown.hidden = true;
document.body.appendChild(dropdown);
let openTop = null; // 열려 있는 메뉴 막대 단추

/** 메뉴를 (x, y)에 띄우되 창 밖으로 나가지 않게 합니다. */
function placeMenu(box, x, y) {
  box.hidden = false;
  box.style.left = "0px";
  box.style.top = "0px";
  const r = box.getBoundingClientRect();
  box.style.left = `${Math.max(0, Math.min(x, window.innerWidth - r.width - 2))}px`;
  box.style.top = `${Math.max(0, Math.min(y, window.innerHeight - r.height - 2))}px`;
}

function openTopMenu(button) {
  closeMenus();
  const items = menuItems().find(([name]) => name === button.dataset.menu)[1];
  fillMenu(dropdown, items);
  const r = button.getBoundingClientRect();
  placeMenu(dropdown, r.left, r.bottom);
  button.setAttribute("aria-expanded", "true");
  openTop = button;
}

function closeMenus() {
  dropdown.hidden = true;
  el.contextMenu.hidden = true;
  if (openTop) openTop.setAttribute("aria-expanded", "false");
  openTop = null;
}

for (const [name] of menuItems()) {
  const b = document.createElement("button");
  b.type = "button";
  b.textContent = name;
  b.dataset.menu = name;
  b.setAttribute("aria-haspopup", "menu");
  b.setAttribute("aria-expanded", "false");
  b.addEventListener("click", () => (openTop === b ? closeMenus() : openTopMenu(b)));
  // 메뉴 하나가 열려 있으면 다른 메뉴 이름에 마우스를 올리는 것만으로 바꿔 엶
  b.addEventListener("pointerenter", () => { if (openTop && openTop !== b) openTopMenu(b); });
  el.menubar.appendChild(b);
}

/** 우클릭한 행과 같은 파일의 쪽을 모두 선택합니다 (데스크톱판 select_file_pages). */
function selectFilePages() {
  const p = contextRow && pages.get(contextRow);
  if (!p) return;
  selected = new Set(order.filter((id) => pages.get(id).source === p.source));
  updateSelectionView();
}

el.list.addEventListener("contextmenu", (ev) => {
  ev.preventDefault();
  if (drag.active) return; // 끄는 중에는 띄우지 않음
  closeMenus();
  const id = rowIdAt(ev.clientY);
  contextRow = id;
  // 이미 선택된 행이면 선택을 유지하고, 아니면 그 행만 선택 (데스크톱판 select_for_context)
  if (id) {
    if (!selected.has(id)) {
      selected = new Set([id]);
      anchor = id;
      updateSelectionView();
    }
    setFocus(id);
  }
  fillMenu(el.contextMenu, contextMenuItems());
  placeMenu(el.contextMenu, ev.clientX, ev.clientY);
});

// 메뉴 밖을 누르면 닫음
document.addEventListener("pointerdown", (ev) => {
  if (dropdown.hidden && el.contextMenu.hidden) return;
  if (dropdown.contains(ev.target) || el.contextMenu.contains(ev.target) || el.menubar.contains(ev.target)) return;
  closeMenus();
}, true);
window.addEventListener("blur", closeMenus);
window.addEventListener("resize", closeMenus);

/** 열린 메뉴 안에서 위/아래 화살표로 항목을 옮겨 다님. 처리했으면 true */
function menuKey(ev) {
  const box = !dropdown.hidden ? dropdown : !el.contextMenu.hidden ? el.contextMenu : null;
  if (!box) return false;
  if (ev.key === "Escape") {
    const top = openTop;
    closeMenus();
    if (top) top.focus();
    return true;
  }
  if (ev.key === "ArrowDown" || ev.key === "ArrowUp") {
    const items = [...box.querySelectorAll("button:not(:disabled)")];
    if (items.length) {
      const i = items.indexOf(document.activeElement);
      const next = ev.key === "ArrowDown" ? (i + 1) % items.length : (i <= 0 ? items.length - 1 : i - 1);
      items[next].focus();
    }
    return true;
  }
  if (ev.key === "ArrowLeft" || ev.key === "ArrowRight") {
    if (!openTop) return true;
    const tops = [...el.menubar.children];
    const next = tops[(tops.indexOf(openTop) + (ev.key === "ArrowRight" ? 1 : tops.length - 1)) % tops.length];
    openTopMenu(next);
    return true;
  }
  return false;
}

// ---------------------------------------------------------------------------
// 키보드
// ---------------------------------------------------------------------------
function isTyping(target) {
  return target instanceof HTMLInputElement || target instanceof HTMLTextAreaElement;
}

document.addEventListener("keydown", (ev) => {
  const mod = IS_MAC ? ev.metaKey : ev.ctrlKey;
  const key = ev.key.toLowerCase();
  if (document.querySelector("dialog[open]")) {
    // 대화 상자가 떠 있으면 본 화면의 단축키는 처리하지 않음 (데스크톱판에서 다른 창의 키를 무시하는 것과 같음)
    if (mod && (key === "o" || key === "s")) ev.preventDefault(); // 브라우저 자체의 열기/저장 창도 띄우지 않음
    return;
  }
  if (menuKey(ev)) { ev.preventDefault(); return; }
  if (mod && key === "o") { ev.preventDefault(); if (!busy) el.fileInput.click(); return; }
  if (mod && key === "s") { ev.preventDefault(); save(); return; }
  if (isTyping(ev.target)) {
    if (ev.key === "Enter" && ev.target === el.range && !busy) el.fileInput.click();
    return; // 입력 칸에서는 기본 동작 유지
  }
  if (mod && key === "z" && !ev.shiftKey) { ev.preventDefault(); undo(); return; }
  if (mod && (key === "y" || (key === "z" && ev.shiftKey))) { ev.preventDefault(); redo(); return; }
  if (mod && key === "a") { ev.preventDefault(); selectAll(); return; }
  if (ev.key === "Delete" || (IS_MAC && ev.key === "Backspace")) { ev.preventDefault(); deleteSelected(); return; }
  if ((ev.key === "ArrowUp" || ev.key === "ArrowDown") && order.length) {
    ev.preventDefault();
    const cur = order.indexOf(pages.has(focusId) ? focusId : order.find((x) => selected.has(x)));
    const next = Math.min(Math.max(cur + (ev.key === "ArrowUp" ? -1 : 1), 0), order.length - 1);
    const id = order[cur < 0 ? 0 : next];
    selected = new Set([id]);
    anchor = id;
    setFocus(id);
    updateSelectionView();
    const top = order.indexOf(id) * rowHeight();
    if (top < el.list.scrollTop) el.list.scrollTop = top;
    else if (top + rowHeight() > el.list.scrollTop + el.list.clientHeight) el.list.scrollTop = top + rowHeight() - el.list.clientHeight;
  }
});

// ---------------------------------------------------------------------------
// 버튼과 파일 끌어다 놓기
// ---------------------------------------------------------------------------
$("open-btn").addEventListener("click", () => el.fileInput.click());
el.fileInput.addEventListener("change", async () => {
  const files = [...el.fileInput.files];
  el.fileInput.value = ""; // 같은 파일을 다시 고를 수 있도록
  await loadFiles(files);
});
$("delete-btn").addEventListener("click", deleteSelected);
$("up-btn").addEventListener("click", () => shift(-1));
$("down-btn").addEventListener("click", () => shift(1));
$("top-btn").addEventListener("click", () => moveTo(1));
$("bottom-btn").addEventListener("click", () => moveTo(Number.MAX_SAFE_INTEGER));
$("moveto-btn").addEventListener("click", moveToDialog);
$("selectall-btn").addEventListener("click", selectAll);
$("clear-btn").addEventListener("click", clearAll);
$("save-btn").addEventListener("click", save);
$("images-btn").addEventListener("click", () => saveImages());

let dragDepth = 0;
const hasFiles = (ev) => ev.dataTransfer && [...ev.dataTransfer.types].includes("Files");
window.addEventListener("dragenter", (ev) => {
  if (!hasFiles(ev)) return;
  dragDepth++;
  document.body.classList.add("file-over");
});
window.addEventListener("dragleave", (ev) => {
  if (!hasFiles(ev)) return;
  if (--dragDepth <= 0) { dragDepth = 0; document.body.classList.remove("file-over"); }
});
window.addEventListener("dragover", (ev) => { if (hasFiles(ev)) ev.preventDefault(); });
window.addEventListener("drop", (ev) => {
  if (!hasFiles(ev)) return;
  ev.preventDefault();
  dragDepth = 0;
  document.body.classList.remove("file-over");
  loadFiles([...ev.dataTransfer.files]);
});

refresh();
document.documentElement.dataset.ready = "1";
