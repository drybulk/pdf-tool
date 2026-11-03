// 이미지 파일을 PDF 쪽으로 바꾸기. 데스크톱판 pdf_common.image_to_pdf와 같은 규칙입니다.
// - 이미지 1장이 1쪽입니다. 움직이는 GIF, WebP는 첫 장면만 씁니다.
// - 쪽 너비는 A4 너비(595.28pt)이고 높이는 가로세로 비율대로 정합니다. 여백은 없습니다.
// - JPG(RGB, 회색조)는 다시 압축하지 않고 파일 내용을 그대로 넣습니다(DCTDecode). Exif 방향 3/6/8은 쪽 회전으로 반영합니다.
// - 그 밖의 이미지(거울상 방향 JPG, CMYK JPG 포함)는 브라우저로 화소를 읽어 무손실 압축(FlateDecode)해서 넣고,
//   투명한 부분은 흰색으로 채웁니다.
// 데스크톱판과 다른 점: 화소 읽기를 브라우저에 맡기므로, 브라우저가 읽지 못하는 형식(Chrome의 TIFF 등)은 불러오지 못합니다.

export const IMAGE_EXTENSIONS = [".png", ".jpg", ".jpeg", ".bmp", ".gif", ".tif", ".tiff", ".webp"];
export const IMAGE_PAGE_WIDTH = (210 / 25.4) * 72;
const JPEG_ROTATE = { 1: 0, 3: 180, 6: 90, 8: 270 }; // Exif 방향 -> 쪽 회전(시계 방향)

export class ImageError extends Error {}

export function isImageFile(name) {
  const lower = name.toLowerCase();
  return IMAGE_EXTENSIONS.some((ext) => lower.endsWith(ext));
}

/**
 * JPG의 크기, 색 성분 수, Exif 방향을 읽습니다. JPG가 아니거나 읽을 수 없으면 null.
 */
export function jpegInfo(bytes) {
  if (bytes.length < 4 || bytes[0] !== 0xff || bytes[1] !== 0xd8) return null;
  const view = new DataView(bytes.buffer, bytes.byteOffset, bytes.byteLength);
  let pos = 2;
  let orientation = 1;
  while (pos + 4 <= bytes.length) {
    if (bytes[pos] !== 0xff) return null;
    const marker = bytes[pos + 1];
    if (marker === 0xff) { pos++; continue; }       // 채움 바이트
    if (marker === 0xd8 || (marker >= 0xd0 && marker <= 0xd7) || marker === 0x01) { pos += 2; continue; }
    const len = view.getUint16(pos + 2);
    const body = pos + 4;
    // 잘린 파일: 구간이 파일 끝을 넘으면 JPG로 읽지 않음 (그다음 브라우저로 읽다가 ImageError가 남)
    if (len < 2 || pos + 2 + len > bytes.length) return null;
    if (marker === 0xe1 && len >= 8 && String.fromCharCode(...bytes.subarray(body, body + 4)) === "Exif") {
      const o = exifOrientation(view, body + 6, Math.min(bytes.length, pos + 2 + len));
      if (o) orientation = o;
    }
    // SOF0~SOF15 (DHT C4, JPG C8, DAC CC 제외)
    if (marker >= 0xc0 && marker <= 0xcf && marker !== 0xc4 && marker !== 0xc8 && marker !== 0xcc) {
      if (len < 8) return null;
      return {
        height: view.getUint16(body + 1),
        width: view.getUint16(body + 3),
        components: bytes[body + 5],
        bits: bytes[body],
        orientation,
      };
    }
    if (marker === 0xda || marker === 0xd9) return null;
    pos += 2 + len;
  }
  return null;
}

function exifOrientation(view, tiff, end) {
  try {
    const little = view.getUint16(tiff) === 0x4949;
    const u16 = (p) => view.getUint16(p, little);
    const u32 = (p) => view.getUint32(p, little);
    const ifd = tiff + u32(tiff + 4);
    const count = u16(ifd);
    for (let i = 0; i < count; i++) {
      const entry = ifd + 2 + i * 12;
      if (entry + 12 > end) break;
      if (u16(entry) === 0x0112) return u16(entry + 8);
    }
  } catch (e) {
    // 방향 정보를 읽지 못하면 기본 방향
  }
  return null;
}

async function deflate(data) {
  // CompressionStream("deflate")는 zlib 형식이며, PDF의 FlateDecode와 같음
  const stream = new Blob([data]).stream().pipeThrough(new CompressionStream("deflate"));
  return new Uint8Array(await new Response(stream).arrayBuffer());
}

/** 브라우저로 이미지를 읽어 흰 바탕에 그린 화소를 { width, height, color, data(압축 전) }로 돌려줍니다. */
async function rasterize(bytes, type) {
  let bitmap;
  try {
    bitmap = await createImageBitmap(new Blob([bytes], { type }), { imageOrientation: "from-image" });
  } catch (e) {
    throw new ImageError("이 브라우저에서 읽을 수 없는 이미지입니다" + (/tiff/.test(type) ? " (TIFF는 Chrome과 Edge에서 읽을 수 없습니다)" : "") + ".");
  }
  const { width, height } = bitmap;
  const canvas = typeof OffscreenCanvas !== "undefined" ? new OffscreenCanvas(width, height) : Object.assign(document.createElement("canvas"), { width, height });
  const ctx = canvas.getContext("2d", { willReadFrequently: true });
  ctx.fillStyle = "#ffffff";
  ctx.fillRect(0, 0, width, height);
  ctx.drawImage(bitmap, 0, 0);
  bitmap.close();
  const rgba = ctx.getImageData(0, 0, width, height).data;
  let gray = true;
  for (let i = 0; i < rgba.length; i += 4) {
    if (rgba[i] !== rgba[i + 1] || rgba[i] !== rgba[i + 2]) { gray = false; break; }
  }
  const n = width * height;
  const data = new Uint8Array(gray ? n : n * 3);
  if (gray) for (let i = 0; i < n; i++) data[i] = rgba[i * 4];
  else for (let i = 0, j = 0; i < n; i++, j += 3) { data[j] = rgba[i * 4]; data[j + 1] = rgba[i * 4 + 1]; data[j + 2] = rgba[i * 4 + 2]; }
  return { width, height, color: gray ? "DeviceGray" : "DeviceRGB", data };
}

const MIME = {
  ".png": "image/png", ".jpg": "image/jpeg", ".jpeg": "image/jpeg", ".bmp": "image/bmp", ".gif": "image/gif",
  ".tif": "image/tiff", ".tiff": "image/tiff", ".webp": "image/webp",
};

/**
 * 이미지 파일 내용(Uint8Array)을 PDF 파일 내용(Uint8Array)으로 바꿉니다. name은 확장자로 형식을 짐작하는 데 씁니다.
 * 읽을 수 없으면 ImageError를 던집니다.
 */
export async function imageToPdf(bytes, name = "", pageWidth = IMAGE_PAGE_WIDTH) {
  const ext = (name.toLowerCase().match(/\.[^.]+$/) || [""])[0];
  const info = jpegInfo(bytes);
  let page;
  if (info && (info.components === 1 || info.components === 3) && info.bits === 8 && info.orientation in JPEG_ROTATE) {
    page = {
      width: info.width, height: info.height, rotate: JPEG_ROTATE[info.orientation],
      color: info.components === 3 ? "DeviceRGB" : "DeviceGray", filter: "DCTDecode", data: bytes,
    };
  } else {
    const r = await rasterize(bytes, info ? "image/jpeg" : MIME[ext] || "");
    page = { width: r.width, height: r.height, rotate: 0, color: r.color, filter: "FlateDecode", data: await deflate(r.data) };
  }
  if (!page.width || !page.height) throw new ImageError("이미지 크기를 읽을 수 없습니다.");
  const shownW = page.rotate === 0 || page.rotate === 180 ? page.width : page.height; // 회전한 뒤 보이는 가로 화소 수
  const scale = pageWidth / shownW;
  return buildImagePdf([{ ...page, pw: page.width * scale, ph: page.height * scale }]);
}

/** 쪽마다 이미지 하나를 쪽 전체에 그리는 PDF를 만듭니다(데스크톱판 _build_image_pdf와 같은 구조). */
export function buildImagePdf(pages) {
  const num = (x) => x.toFixed(4).replace(/0+$/, "").replace(/\.$/, "");
  const enc = new TextEncoder();
  const objs = [];
  const kids = pages.map((_, i) => `${3 + 3 * i} 0 R`).join(" ");
  objs.push(enc.encode("<< /Type /Catalog /Pages 2 0 R >>"));
  objs.push(enc.encode(`<< /Type /Pages /Kids [${kids}] /Count ${pages.length} >>`));
  pages.forEach((p, i) => {
    const contentRef = 4 + 3 * i;
    const imageRef = 5 + 3 * i;
    const content = enc.encode(`q ${num(p.pw)} 0 0 ${num(p.ph)} 0 0 cm /Im0 Do Q`);
    objs.push(enc.encode(
      `<< /Type /Page /Parent 2 0 R /MediaBox [0 0 ${num(p.pw)} ${num(p.ph)}] /Rotate ${p.rotate} ` +
      `/Resources << /XObject << /Im0 ${imageRef} 0 R >> >> /Contents ${contentRef} 0 R >>`));
    objs.push(concat([enc.encode(`<< /Length ${content.length} >>\nstream\n`), content, enc.encode("\nendstream")]));
    objs.push(concat([
      enc.encode(`<< /Type /XObject /Subtype /Image /Width ${p.width} /Height ${p.height} /ColorSpace /${p.color} ` +
        `/BitsPerComponent 8 /Filter /${p.filter} /Length ${p.data.length} >>\nstream\n`),
      p.data, enc.encode("\nendstream")]));
  });
  const parts = [new Uint8Array([...enc.encode("%PDF-1.4\n%"), 0xe2, 0xe3, 0xcf, 0xd3, 0x0a])];
  let size = parts[0].length;
  const offsets = [];
  objs.forEach((body, i) => {
    offsets.push(size);
    const chunk = concat([enc.encode(`${i + 1} 0 obj\n`), body, enc.encode("\nendobj\n")]);
    parts.push(chunk);
    size += chunk.length;
  });
  let tail = `xref\n0 ${objs.length + 1}\n0000000000 65535 f \n`;
  for (const off of offsets) tail += `${String(off).padStart(10, "0")} 00000 n \n`;
  tail += `trailer\n<< /Size ${objs.length + 1} /Root 1 0 R >>\nstartxref\n${size}\n%%EOF\n`;
  parts.push(enc.encode(tail));
  return concat(parts);
}

function concat(parts) {
  const out = new Uint8Array(parts.reduce((n, p) => n + p.length, 0));
  let pos = 0;
  for (const p of parts) { out.set(p, pos); pos += p.length; }
  return out;
}
