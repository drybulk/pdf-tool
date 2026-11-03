// PDF 읽기, 그리기, 저장. 렌더링은 pdf.js, 저장은 pdf-lib(@cantoo/pdf-lib)를 사용합니다.
// 화면 코드와 분리해 두어서 나중에 Chrome 확장에서도 그대로 쓸 수 있게 합니다.

import * as pdfjsLib from "../vendor/pdfjs/pdf.min.mjs";
import { PDFDocument } from "../vendor/pdf-lib/pdf-lib.esm.min.js";

const vendor = (path) => new URL(`../vendor/${path}`, import.meta.url).href;

pdfjsLib.GlobalWorkerOptions.workerSrc = vendor("pdfjs/pdf.worker.min.mjs");

export class PdfOpenError extends Error {}

/**
 * PDF 바이트를 pdf.js로 엽니다. pdf.js는 넘겨받은 버퍼를 작업 스레드로 옮겨 버리므로 복사본을 넘깁니다.
 * 열 수 없으면 PdfOpenError를 던집니다.
 */
export async function openPdf(bytes) {
  const task = pdfjsLib.getDocument({
    data: bytes.slice(),
    cMapUrl: vendor("pdfjs/cmaps/"),
    cMapPacked: true,
    standardFontDataUrl: vendor("pdfjs/standard_fonts/"),
    wasmUrl: vendor("pdfjs/wasm/"),
    iccUrl: vendor("pdfjs/iccs/"),
    isEvalSupported: false, // Chrome 확장은 eval을 허용하지 않으므로 처음부터 쓰지 않음
    enableScripting: false,
  });
  // 비밀번호를 물으면 묻지 않고 실패로 처리함 (데스크톱판과 같음)
  task.onPassword = () => task.destroy();
  try {
    return await task.promise;
  } catch (e) {
    if (e && e.name === "PasswordException") throw new PdfOpenError("비밀번호가 설정된 PDF입니다.");
    // onPassword에서 destroy하면 이 오류가 남
    if (task.destroyed) throw new PdfOpenError("비밀번호가 설정된 PDF입니다.");
    throw new PdfOpenError(`PDF를 읽을 수 없습니다: ${e && e.message ? e.message : e}`);
  }
}

/** 쪽(0부터)의 크기를 배율 1(1pt = 1px)로 돌려줍니다. 회전이 반영된 크기입니다. */
export async function pageSize(doc, index) {
  const page = await doc.getPage(index + 1);
  const vp = page.getViewport({ scale: 1 });
  return { width: vp.width, height: vp.height };
}

/**
 * 쪽(0부터)을 canvas에 그립니다. scale은 pt당 픽셀 수입니다.
 * 그리는 중에 다른 그리기로 바뀌면 cancel()로 멈출 수 있도록 { canvas, promise, cancel }을 돌려줍니다.
 */
export function renderPage(doc, index, scale) {
  const canvas = document.createElement("canvas");
  let task = null;
  let cancelled = false;
  const promise = (async () => {
    const page = await doc.getPage(index + 1);
    if (cancelled) throw new Error("cancelled");
    const vp = page.getViewport({ scale });
    canvas.width = Math.max(1, Math.round(vp.width));
    canvas.height = Math.max(1, Math.round(vp.height));
    const ctx = canvas.getContext("2d");
    ctx.fillStyle = "#ffffff";
    ctx.fillRect(0, 0, canvas.width, canvas.height);
    task = page.render({ canvasContext: ctx, canvas, viewport: vp });
    await task.promise;
    return canvas;
  })();
  return {
    canvas,
    promise,
    cancel() {
      cancelled = true;
      if (task) task.cancel();
    },
  };
}

/** pdf-lib로 원본 PDF를 엽니다. 열람 비밀번호가 없는 암호화 PDF는 빈 비밀번호로 해제합니다. */
async function openForCopy(bytes) {
  let doc;
  try {
    doc = await PDFDocument.load(bytes);
  } catch (e) {
    if (!(e && /encrypted/i.test(e.message))) throw e;
    doc = await PDFDocument.load(bytes, { password: "" });
  }
  if (doc.isEncrypted) throw new Error("암호화된 PDF를 해제하지 못했습니다.");
  return doc;
}

/**
 * pages: [{ source, index }, ...] 순서대로 새 PDF를 만들어 바이트(Uint8Array)를 돌려줍니다.
 * source는 { name, bytes }입니다. 같은 쪽이 여러 번 들어 있어도 됩니다.
 * progress(n, total)는 원본 하나의 쪽을 모두 복사할 때마다 호출합니다.
 * 원본 북마크와 이름 붙은 대상(named destination)은 아직 옮기지 않습니다(다음 단계).
 */
export async function savePages(pages, progress) {
  const out = await PDFDocument.create();
  const total = pages.length;
  // 원본마다 필요한 쪽을 모아 copyPages를 한 번만 부름. copyPages는 한 번의 호출 안에서만 공유 자원
  // (글꼴, 그림 등)을 한 번 복사하므로, 쪽마다 따로 부르면 같은 자원이 여러 번 들어가 파일이 커짐
  const positions = new Map(); // source -> [결과에서의 위치, ...]
  pages.forEach((p, pos) => {
    if (!positions.has(p.source)) positions.set(p.source, []);
    positions.get(p.source).push(pos);
  });
  const result = new Array(total);
  let n = 0;
  for (const [source, list] of positions) {
    let doc;
    try {
      doc = await openForCopy(source.bytes);
    } catch (e) {
      throw new Error(`${source.name}: ${e && e.message ? e.message : e}`);
    }
    const copied = await out.copyPages(doc, list.map((pos) => pages[pos].index));
    list.forEach((pos, k) => (result[pos] = copied[k]));
    n += list.length;
    if (progress) progress(n, total);
  }
  for (const page of result) out.addPage(page);
  return out.save();
}
