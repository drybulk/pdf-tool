"""
PDF 도구 렌더링 모듈: 렌더링판(pdf_tool_render.py)에서만 사용합니다.

pypdfium2로 쪽을 그림으로 그리고, Tk가 Pillow 없이 표시할 수 있는 PPM(P6) 데이터로 바꿉니다.
PDFium은 스레드 안전하지 않으므로 이 모듈의 함수는 모두 메인 스레드에서만 호출합니다.

필요한 외부 라이브러리: pypdfium2
"""

import math
from collections import OrderedDict

import pypdfium2 as pdfium


THUMB_SCALE = 0.12  # 썸네일 배율 (72 DPI 기준 크기에 곱함)
# 썸네일이 들어갈 칸의 크기(픽셀). A4 세로 쪽(595x842pt)을 THUMB_SCALE로 그린 크기이며,
# 이보다 큰 쪽은 칸에 들어가도록 더 작게 그립니다.
THUMB_BOX = (math.ceil(595 * THUMB_SCALE), math.ceil(842 * THUMB_SCALE))


def bitmap_to_ppm(width, height, stride, data):
    """
    RGB 순서의 비트맵 데이터를 PPM(P6) 바이트로 바꿉니다.
    PDFium 비트맵은 행 간격(stride)이 너비x3보다 클 수 있으므로 행 단위로 잘라서 복사합니다.
    """
    header = b"P6 %d %d 255\n" % (width, height)
    buf = memoryview(data).cast("B")  # ctypes 배열을 그대로 자르면 정수 리스트가 되므로 memoryview로 다룸
    row = width * 3
    if stride == row:
        return header + bytes(buf[: row * height])
    return header + b"".join(bytes(buf[y * stride : y * stride + row]) for y in range(height))


def thumb_scale(page_w, page_h, scale=THUMB_SCALE, box=THUMB_BOX):
    """쪽 크기(pt)에 대해 썸네일 칸을 넘지 않는 배율을 반환합니다."""
    return min(scale, box[0] / page_w, box[1] / page_h)


def fit_scale(page_w, page_h, box_w, box_h):
    """쪽 전체가 box_w x box_h 픽셀 안에 들어가는 배율을 반환합니다."""
    return min(box_w / page_w, box_h / page_h)


class PdfiumDocs:
    """경로별 PdfDocument를 열어 두고 쪽 크기 조회와 렌더링을 제공합니다."""

    def __init__(self):
        self._docs = {}   # PDF 경로 -> PdfDocument
        self._sizes = {}  # (경로, 쪽 인덱스) -> (너비, 높이) pt, 쪽의 회전이 반영된 값

    def _doc(self, path):
        doc = self._docs.get(path)
        if doc is None:
            try:
                doc = pdfium.PdfDocument(path)
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
        page = self._doc(path)[index]
        try:
            bitmap = page.render(scale=scale, rev_byteorder=True)
            try:
                if bitmap.n_channels != 3:
                    raise ValueError(f"예상하지 못한 비트맵 형식입니다: {bitmap.mode}")
                ppm = bitmap_to_ppm(bitmap.width, bitmap.height, bitmap.stride, bitmap.buffer)
                return bitmap.width, bitmap.height, ppm
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
