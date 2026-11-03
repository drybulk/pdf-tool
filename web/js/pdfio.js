// PDF 읽기와 그리기(pdf.js). 저장(pdf-lib)은 pdfsave.js에 있습니다.
// 화면 코드와 분리해 두어서 나중에 Chrome 확장에서도 그대로 쓸 수 있게 합니다.

import * as pdfjsLib from "../vendor/pdfjs/pdf.min.mjs";

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

// 저장은 pdfsave.js에 있습니다(북마크와 이름 붙은 대상 처리 포함).
export { savePages } from "./pdfsave.js";
export const PDFJS_VERSION = pdfjsLib.version;
