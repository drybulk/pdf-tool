// 쪽을 이미지(PNG, JPG)로 저장할 때 쓰는 함수들. 데스크톱판 pdf_render.py의 규칙(파일 이름, DPI 기록)을 따릅니다.
// 브라우저는 폴더에 파일을 바로 쓸 수 없으므로, 여러 장은 zip 파일 하나로 내려받습니다.

export const DPI_CHOICES = [72, 150, 200, 300]; // 배율 = DPI / 72
export const DEFAULT_DPI = 150;
export const DEFAULT_QUALITY = 90;

/**
 * [{ name, index }, ...]에 대해 저장할 파일 이름 목록을 같은 순서로 돌려줍니다(데스크톱판 image_file_names와 같음).
 * 이름은 "원본이름_p0721.png"처럼 원본 쪽 번호(1부터)를 4자리 이상으로 씁니다.
 * 같은 이름이 다시 나오면 뒤에 _2, _3을 붙입니다. Windows처럼 대소문자를 구분하지 않고 비교합니다.
 */
export function imageFileNames(pages, ext) {
  const used = new Set();
  return pages.map(({ name, index }) => {
    const stem = name.replace(/\.[^.]*$/, "");
    const base = `${stem}_p${String(index + 1).padStart(4, "0")}`;
    let file = `${base}.${ext}`;
    let n = 1;
    while (used.has(file.toLowerCase())) file = `${base}_${++n}.${ext}`;
    used.add(file.toLowerCase());
    return file;
  });
}

// ---------------------------------------------------------------------------
// CRC-32 (PNG 청크와 zip에서 씀)
// ---------------------------------------------------------------------------
const CRC_TABLE = (() => {
  const t = new Uint32Array(256);
  for (let n = 0; n < 256; n++) {
    let c = n;
    for (let k = 0; k < 8; k++) c = c & 1 ? 0xedb88320 ^ (c >>> 1) : c >>> 1;
    t[n] = c >>> 0;
  }
  return t;
})();

export function crc32(data, crc = 0) {
  crc = ~crc >>> 0;
  for (let i = 0; i < data.length; i++) crc = CRC_TABLE[(crc ^ data[i]) & 0xff] ^ (crc >>> 8);
  return ~crc >>> 0;
}

function canvasBytes(canvas, type, quality) {
  return new Promise((resolve, reject) => {
    canvas.toBlob(async (blob) => {
      if (!blob) reject(new Error("그림을 만들지 못했습니다. 쪽이 너무 크면 DPI를 낮춰 보세요."));
      else resolve(new Uint8Array(await blob.arrayBuffer()));
    }, type, quality);
  });
}

/** canvas를 PNG로 바꾸고, 해상도(DPI)를 pHYs 청크에 기록합니다. */
export async function encodePng(canvas, dpi) {
  const png = await canvasBytes(canvas, "image/png");
  // 서명(8) 다음의 첫 청크는 IHDR(길이 4 + 종류 4 + 내용 13 + CRC 4 = 25바이트)
  const at = 8 + 25;
  const ppm = Math.round(dpi / 0.0254); // 1미터당 화소 수
  const chunk = new Uint8Array(21);
  const v = new DataView(chunk.buffer);
  v.setUint32(0, 9);
  chunk.set([0x70, 0x48, 0x59, 0x73], 4); // "pHYs"
  v.setUint32(8, ppm);
  v.setUint32(12, ppm);
  chunk[16] = 1; // 단위: 미터
  v.setUint32(17, crc32(chunk.subarray(4, 17)));
  const out = new Uint8Array(png.length + chunk.length);
  out.set(png.subarray(0, at));
  out.set(chunk, at);
  out.set(png.subarray(at), at + chunk.length);
  return out;
}

/** canvas를 JPG로 바꾸고(품질 1~95), JFIF 머리글이 있으면 해상도(DPI)를 기록합니다. */
export async function encodeJpg(canvas, dpi, quality) {
  const jpg = await canvasBytes(canvas, "image/jpeg", quality / 100);
  // FF D8 FF E0 길이(2) "JFIF\0" 판(2) 단위(1) 가로 밀도(2) 세로 밀도(2)
  if (jpg[2] === 0xff && jpg[3] === 0xe0 && String.fromCharCode(...jpg.subarray(6, 11)) === "JFIF\0") {
    const v = new DataView(jpg.buffer, jpg.byteOffset);
    jpg[13] = 1; // 단위: 인치
    v.setUint16(14, dpi);
    v.setUint16(16, dpi);
  }
  return jpg;
}

// ---------------------------------------------------------------------------
// zip (압축하지 않고 담기만 함. PNG와 JPG는 이미 압축되어 있음)
// ---------------------------------------------------------------------------
/** files: [{ name, data(Uint8Array) }, ...] -> zip 파일 내용의 Blob */
export function makeZip(files) {
  const enc = new TextEncoder();
  const parts = [];
  const central = [];
  let offset = 0;
  const now = new Date();
  const time = (now.getHours() << 11) | (now.getMinutes() << 5) | (now.getSeconds() >> 1);
  const date = ((now.getFullYear() - 1980) << 9) | ((now.getMonth() + 1) << 5) | now.getDate();
  for (const f of files) {
    const name = enc.encode(f.name);
    const crc = crc32(f.data);
    const local = new Uint8Array(30 + name.length);
    const lv = new DataView(local.buffer);
    lv.setUint32(0, 0x04034b50, true);
    lv.setUint16(4, 20, true);
    lv.setUint16(6, 0x0800, true); // 파일 이름이 UTF-8 (한국어 이름)
    lv.setUint16(8, 0, true);      // 압축하지 않음
    lv.setUint16(10, time, true);
    lv.setUint16(12, date, true);
    lv.setUint32(14, crc, true);
    lv.setUint32(18, f.data.length, true);
    lv.setUint32(22, f.data.length, true);
    lv.setUint16(26, name.length, true);
    local.set(name, 30);
    parts.push(local, f.data);

    const cen = new Uint8Array(46 + name.length);
    const cv = new DataView(cen.buffer);
    cv.setUint32(0, 0x02014b50, true);
    cv.setUint16(4, 20, true);
    cv.setUint16(6, 20, true);
    cv.setUint16(8, 0x0800, true);
    cv.setUint16(10, 0, true);
    cv.setUint16(12, time, true);
    cv.setUint16(14, date, true);
    cv.setUint32(16, crc, true);
    cv.setUint32(20, f.data.length, true);
    cv.setUint32(24, f.data.length, true);
    cv.setUint16(28, name.length, true);
    cv.setUint32(42, offset, true);
    cen.set(name, 46);
    central.push(cen);
    offset += local.length + f.data.length;
  }
  const size = central.reduce((n, c) => n + c.length, 0);
  const end = new Uint8Array(22);
  const ev = new DataView(end.buffer);
  ev.setUint32(0, 0x06054b50, true);
  ev.setUint16(8, files.length, true);
  ev.setUint16(10, files.length, true);
  ev.setUint32(12, size, true);
  ev.setUint32(16, offset, true);
  return new Blob([...parts, ...central, end], { type: "application/zip" });
}
