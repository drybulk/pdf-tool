"""
PDF 도구 렌더링 모듈: 렌더링판(pdf_tool_render.py)에서만 사용합니다.

pypdfium2로 쪽을 그림으로 그리고, Tk가 Pillow 없이 표시할 수 있는 PPM(P6) 데이터로 바꿉니다.
쪽을 이미지 파일로 저장할 때 쓰는 PNG, JPG 변환 함수도 들어 있습니다.
PDFium은 스레드 안전하지 않으므로 PdfiumDocs는 메인 스레드에서만 사용합니다.
PNG, JPG 변환 함수(encode_png, encode_jpg)는 PDFium을 쓰지 않으므로 다른 스레드에서 호출해도 됩니다.

필요한 외부 라이브러리: pypdfium2 (JPG 저장에는 Pillow도 필요)
"""

import io
import math
import os
import struct
import zlib
from collections import OrderedDict

import pypdfium2 as pdfium

try:
    from PIL import Image  # JPG 저장에만 사용. 없으면 PNG만 저장할 수 있음
except ImportError:
    Image = None

HAS_PILLOW = Image is not None


THUMB_SCALE = 0.12  # 썸네일 배율 (72 DPI 기준 크기에 곱함)
# 썸네일이 들어갈 칸의 크기(픽셀). A4 세로 쪽(595x842pt)을 THUMB_SCALE로 그린 크기이며,
# 이보다 큰 쪽은 칸에 들어가도록 더 작게 그립니다.
THUMB_BOX = (math.ceil(595 * THUMB_SCALE), math.ceil(842 * THUMB_SCALE))

DPI_CHOICES = (72, 150, 200, 300)  # 이미지 저장 해상도 선택지. 배율 = DPI / 72
PNG_LEVEL = 6                      # PNG 압축 수준 (zlib 0~9)


def bitmap_to_rgb(width, height, stride, data):
    """
    RGB 순서의 비트맵 데이터를 행 사이에 빈 바이트가 없는 RGB 바이트(너비x높이x3)로 바꿉니다.
    PDFium 비트맵은 행 간격(stride)이 너비x3보다 클 수 있으므로 행 단위로 잘라서 복사합니다.
    """
    buf = memoryview(data).cast("B")  # ctypes 배열을 그대로 자르면 정수 리스트가 되므로 memoryview로 다룸
    row = width * 3
    if stride == row:
        return bytes(buf[: row * height])
    return b"".join(bytes(buf[y * stride : y * stride + row]) for y in range(height))


def bitmap_to_ppm(width, height, stride, data):
    """RGB 순서의 비트맵 데이터를 PPM(P6) 바이트로 바꿉니다."""
    return b"P6 %d %d 255\n" % (width, height) + bitmap_to_rgb(width, height, stride, data)


def _png_chunk(kind, data):
    return struct.pack(">I", len(data)) + kind + data + struct.pack(">I", zlib.crc32(kind + data))


def encode_png(width, height, rgb, dpi=None, level=PNG_LEVEL):
    """RGB 바이트를 PNG 파일 내용으로 바꿉니다. 표준 라이브러리 zlib만 사용합니다. dpi를 주면 해상도 정보(pHYs)를 기록합니다."""
    row = width * 3
    # 각 행 앞에 필터 종류 0(필터 없음)을 붙임
    raw = b"".join(b"\x00" + rgb[y * row : (y + 1) * row] for y in range(height))
    out = b"\x89PNG\r\n\x1a\n"
    out += _png_chunk(b"IHDR", struct.pack(">IIBBBBB", width, height, 8, 2, 0, 0, 0))  # 8비트 RGB
    if dpi:
        ppm = round(dpi / 0.0254)  # 1미터당 픽셀 수
        out += _png_chunk(b"pHYs", struct.pack(">IIB", ppm, ppm, 1))
    out += _png_chunk(b"IDAT", zlib.compress(raw, level))
    out += _png_chunk(b"IEND", b"")
    return out


def encode_jpg(width, height, rgb, dpi=None, quality=90):
    """RGB 바이트를 JPG 파일 내용으로 바꿉니다. Pillow가 필요합니다."""
    if Image is None:
        raise ValueError("JPG로 저장하려면 Pillow가 필요합니다: pip install -r requirements-render.txt")
    img = Image.frombytes("RGB", (width, height), rgb)
    buf = io.BytesIO()
    options = {"quality": quality}
    if dpi:
        options["dpi"] = (dpi, dpi)
    img.save(buf, "JPEG", **options)
    return buf.getvalue()


def image_file_names(pages, ext):
    """
    [(PDF 경로, 0부터 시작하는 쪽 인덱스), ...]에 대해 저장할 파일 이름 목록을 같은 순서로 반환합니다.
    이름은 "원본이름_p0721.png"처럼 원본 쪽 번호(1부터)를 4자리 이상으로 씁니다.
    같은 이름이 다시 나오면(같은 쪽이 두 번 있거나, 다른 폴더의 같은 이름 파일) 뒤에 _2, _3을 붙입니다.
    """
    names = []
    used = set()
    for path, index in pages:
        stem = os.path.splitext(os.path.basename(path))[0]
        base = f"{stem}_p{index + 1:04d}"
        name, n = f"{base}.{ext}", 1
        while name.lower() in used:  # Windows는 파일 이름의 대소문자를 구분하지 않음
            n += 1
            name = f"{base}_{n}.{ext}"
        used.add(name.lower())
        names.append(name)
    return names


def thumb_scale(page_w, page_h, scale=THUMB_SCALE, box=THUMB_BOX):
    """쪽 크기(pt)에 대해 썸네일 칸을 넘지 않는 배율을 반환합니다."""
    return min(scale, box[0] / page_w, box[1] / page_h)


def fit_scale(page_w, page_h, box_w, box_h):
    """쪽 전체가 box_w x box_h 픽셀 안에 들어가는 배율을 반환합니다."""
    return min(box_w / page_w, box_h / page_h)


class PdfiumDocs:
    """
    경로별 PdfDocument를 열어 두고 쪽 크기 조회와 렌더링을 제공합니다.
    source(경로)를 주면 그 결과(파일 경로 또는 PDF 바이트)를 엽니다. 이미지 파일로 만든 쪽은
    파일이 PDF가 아니므로, 화면이 보관한 PDF 바이트를 이 함수로 넘겨받습니다.
    """

    def __init__(self, source=None):
        self._source = source
        self._docs = {}   # PDF 경로 -> PdfDocument
        self._sizes = {}  # (경로, 쪽 인덱스) -> (너비, 높이) pt, 쪽의 회전이 반영된 값

    def _doc(self, path):
        doc = self._docs.get(path)
        if doc is None:
            try:
                doc = pdfium.PdfDocument(self._source(path) if self._source else path)
            except pdfium.PdfiumError as e:
                raise ValueError(f"쪽 그림을 만들 수 없습니다: {e}")
            self._docs[path] = doc
        return doc

    def page_size(self, path, index):
        key = (path, index)
        if key not in self._sizes:
            page = self._doc(path)[index]
            try:
                self._sizes[key] = page.get_size()
            finally:
                page.close()
        return self._sizes[key]

    def render_ppm(self, path, index, scale):
        """쪽을 scale 배율로 그려서 (너비, 높이, PPM 바이트)를 반환합니다."""
        return self._render(path, index, scale, bitmap_to_ppm)

    def render_rgb(self, path, index, scale):
        """쪽을 scale 배율로 그려서 (너비, 높이, RGB 바이트)를 반환합니다. 이미지 파일 저장에 사용합니다."""
        return self._render(path, index, scale, bitmap_to_rgb)

    def _render(self, path, index, scale, convert):
        page = self._doc(path)[index]
        try:
            bitmap = page.render(scale=scale, rev_byteorder=True)
            try:
                if bitmap.n_channels != 3:
                    raise ValueError(f"예상하지 못한 비트맵 형식입니다: {bitmap.mode}")
                data = convert(bitmap.width, bitmap.height, bitmap.stride, bitmap.buffer)
                return bitmap.width, bitmap.height, data
            finally:
                bitmap.close()
        finally:
            page.close()

    def close_all(self):
        for doc in self._docs.values():
            doc.close()
        self._docs.clear()
        self._sizes.clear()


class LRUCache:
    """최근에 사용한 항목을 max_size개까지 보관합니다. 넘치면 가장 오래된 항목을 on_evict(키, 값)과 함께 버립니다."""

    def __init__(self, max_size, on_evict=None):
        self.max_size = max_size
        self.on_evict = on_evict
        self._items = OrderedDict()

    def __len__(self):
        return len(self._items)

    def __contains__(self, key):
        return key in self._items

    def get(self, key):
        if key not in self._items:
            return None
        self._items.move_to_end(key)
        return self._items[key]

    def put(self, key, value):
        self._items[key] = value
        self._items.move_to_end(key)
        while len(self._items) > self.max_size:
            old_key, old_value = self._items.popitem(last=False)
            if self.on_evict:
                self.on_evict(old_key, old_value)

    def clear(self):
        while self._items:
            old_key, old_value = self._items.popitem(last=False)
            if self.on_evict:
                self.on_evict(old_key, old_value)
