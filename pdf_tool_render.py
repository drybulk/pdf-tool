"""
PDF 도구 렌더링판: 경량판의 기능에 쪽 썸네일과 큰 미리보기를 더한 GUI입니다.

필요한 외부 라이브러리: pypdf, pypdfium2
    pip install -r requirements-render.txt
실행에는 같은 폴더의 pdf_common.py와 pdf_render.py가 필요합니다.

탭 1. PDF 병합         : 경량판과 같습니다.
탭 2. 페이지 추출/편집 : 경량판의 기능에 더해, 쪽 목록의 각 행에 썸네일을 표시하고
                         마지막으로 클릭한 쪽을 오른쪽에 크게 보여 줍니다.
"""

import math
import os
import time
import tkinter as tk
from tkinter import ttk

from pdf_common import MergeTab, PageTab
from pdf_render import THUMB_BOX, LRUCache, PdfiumDocs, fit_scale, thumb_scale


WINDOW_SIZE = (1200, 750)  # 기본 창 크기. 화면이 작으면 화면 안에 들어오도록 줄임
THUMB_CACHE_SIZE = 300     # 보관할 썸네일 수 (넘치면 오래된 것부터 버림)
THUMB_MARGIN = 2           # 화면에 보이는 행의 위아래로 미리 그려 둘 행 수
THUMB_BUDGET = 0.03        # 한 번에 썸네일을 그리는 최대 시간(초). 넘으면 이벤트 처리 후 이어서 그림
PREVIEW_DELAY_MS = 150     # 미리보기 영역 크기가 바뀐 뒤 다시 그리기까지 기다리는 시간
PREVIEW_PAD = 8            # 미리보기 그림과 영역 가장자리 사이의 여백(픽셀)
THUMB_BORDER = "#8a8a8a"   # 썸네일 테두리 색


def fit_window_size(want_w, want_h, screen_w, screen_h, margin_w=40, margin_h=80):
    """원하는 창 크기를 화면 안에 들어오도록 줄입니다. 작업 표시줄과 창 테두리를 위해 여백을 둡니다."""
    return min(want_w, screen_w - margin_w), min(want_h, screen_h - margin_h)


class RenderPageTab(PageTab):
    """
    PageTab에 썸네일과 미리보기를 더한 탭입니다.
    - 화면 배치: [쪽 목록 | 미리보기] [버튼]. 목록과 미리보기 사이의 경계를 끌어서 폭을 조절할 수 있습니다.
    - 썸네일은 화면에 보이는 행(위아래 THUMB_MARGIN행 포함)만 그리고, 최근 THUMB_CACHE_SIZE장을 보관합니다.
    - 미리보기는 마지막으로 클릭한 행(Treeview의 포커스 행)을 미리보기 영역에 맞게 그립니다.
    - 렌더링은 PDFium의 스레드 제한 때문에 메인 스레드에서 짧게 나누어 처리합니다.
    """

    def __init__(self, master):
        self.docs = PdfiumDocs()
        self.thumbs = LRUCache(THUMB_CACHE_SIZE, on_evict=self._on_thumb_evicted)
        self._row_key = {}       # 행 ID -> 그 행에 붙인 썸네일의 키 (경로, 쪽 인덱스)
        self._key_rows = {}      # 썸네일 키 -> 그 썸네일을 붙인 행 ID 집합
        self._failed = set()     # 그리지 못한 쪽의 키
        self._thumb_job = None
        self._preview_job = None
        self._preview_shown = None  # 지금 미리보기에 그려진 (경로, 쪽 인덱스, 너비, 높이)
        self._preview_img = None
        self.thumb_renders = 0      # 썸네일을 실제로 그린 횟수 (테스트와 확인용)
        super().__init__(master)
        self._setup_thumbnails()
        self.bind("<Destroy>", self._on_destroy, add="+")

    # ---- 화면 배치 ----
    def _make_list_frame(self, body):
        self.paned = ttk.PanedWindow(body, orient="horizontal")
        self.paned.pack(side="left", fill="both", expand=True)
        list_frame = ttk.Frame(self.paned)
        self.preview_frame = ttk.Frame(self.paned)
        self.paned.add(list_frame, weight=1)
        self.paned.add(self.preview_frame, weight=1)

        self.preview = tk.Canvas(self.preview_frame, background="#9e9e9e", highlightthickness=0)
        self.preview.pack(fill="both", expand=True)
        self.preview_caption = tk.StringVar(value="")
        ttk.Label(self.preview_frame, textvariable=self.preview_caption, anchor="center").pack(fill="x")
        self.preview.bind("<Configure>", lambda e: self._schedule_preview(PREVIEW_DELAY_MS))
        return list_frame

    def _setup_thumbnails(self):
        tree = self.tree
        tree.configure(show="tree headings")
        tree.heading("#0", text="썸네일")
        tree.column("#0", width=THUMB_BOX[0] + 16, minwidth=THUMB_BOX[0] + 16, stretch=False, anchor="center")
        tree.column("file", width=200)
        ttk.Style(self).configure(tree.style_name, rowheight=THUMB_BOX[1] + 6)
        self._placeholder = tk.PhotoImage(width=THUMB_BOX[0], height=THUMB_BOX[1])
        self._placeholder.put("#d0d0d0", to=(0, 0, THUMB_BOX[0], THUMB_BOX[1]))

        scroll = self.tree_scroll

        def on_scroll(first, last):
            scroll.set(first, last)
            self._schedule_thumbs()

        tree.configure(yscrollcommand=on_scroll)
        tree.bind("<Configure>", lambda e: self._schedule_thumbs(), add="+")
        tree.bind("<<TreeviewSelect>>", lambda e: self._schedule_preview(), add="+")
        tree.bind("<<RowFocus>>", lambda e: self._schedule_preview(), add="+")

    def update_status(self):
        # update_status는 행 목록이 바뀌는 모든 경우(불러오기, 실행 취소 복원, 삭제, 비우기)에 호출됨
        super().update_status()
        alive = set(self.tree.get_children())
        self._row_key = {iid: key for iid, key in self._row_key.items() if iid in alive}
        self._key_rows = {}
        for iid, key in self._row_key.items():
            self._key_rows.setdefault(key, set()).add(iid)
        self._schedule_thumbs()
        self._schedule_preview()

    # ---- 썸네일 ----
    def _schedule_thumbs(self):
        if self._thumb_job is None:
            self._thumb_job = self.after_idle(self._render_thumbs)

    def visible_rows(self):
        """화면에 보이는 행과 위아래 THUMB_MARGIN행"""
        children = self.tree.get_children()
        n = len(children)
        if not n:
            return ()
        first, last = self.tree.yview()
        a = max(int(first * n) - THUMB_MARGIN, 0)
        b = min(math.ceil(last * n) + THUMB_MARGIN, n)
        return children[a:b]

    def _render_thumbs(self):
        self._thumb_job = None
        start = time.perf_counter()
        for iid in self.visible_rows():
            key = self.pages.get(iid)
            if key is None:
                continue
            if self._row_key.get(iid) == key:
                self.thumbs.get(key)  # 보이는 썸네일이 먼저 버려지지 않도록 최근 사용으로 표시
                continue
            img = self.thumbs.get(key)
            if img is None and key not in self._failed:
                if time.perf_counter() - start > THUMB_BUDGET:
                    self._thumb_job = self.after(1, self._render_thumbs)  # 이벤트를 처리한 뒤 이어서 그림
                    return
                img = self._make_thumb(*key)
            self._attach(iid, key, img or self._placeholder)

    def _make_thumb(self, path, index):
        try:
            w, h = self.docs.page_size(path, index)
            pw, ph, ppm = self.docs.render_ppm(path, index, thumb_scale(w, h))
        except Exception:
            self._failed.add((path, index))
            return None
        self.thumb_renders += 1
        img = tk.PhotoImage(data=ppm, format="PPM")
        # 흰 쪽이 흰 목록 배경과 구분되도록 1픽셀 테두리를 그림
        for box in ((0, 0, pw, 1), (0, ph - 1, pw, ph), (0, 0, 1, ph), (pw - 1, 0, pw, ph)):
            img.put(THUMB_BORDER, to=box)
        self.thumbs.put((path, index), img)
        return img

    def _attach(self, iid, key, img):
        old = self._row_key.get(iid)
        if old is not None:
            self._key_rows.get(old, set()).discard(iid)
        self.tree.item(iid, image=img)
        self._row_key[iid] = key
        self._key_rows.setdefault(key, set()).add(iid)

    def _on_thumb_evicted(self, key, img):
        # 버리는 그림을 아직 붙이고 있는 행에서 떼어 냄. 다시 보이면 새로 그림
        for iid in self._key_rows.pop(key, ()):
            if self.tree.exists(iid) and self._row_key.get(iid) == key:
                self.tree.item(iid, image="")
                del self._row_key[iid]

    # ---- 미리보기 ----
    def preview_target(self):
        """미리보기할 행: 마지막으로 클릭한 행(포커스 행). 없으면 선택한 행 중 첫 행."""
        iid = self.tree.focus()
        if iid and self.tree.exists(iid) and iid in self.pages:
            return iid
        sel = [i for i in self.tree.selection() if i in self.pages]
        return min(sel, key=self.tree.index) if sel else None

    def _schedule_preview(self, delay=0):
        if self._preview_job is not None:
            self.after_cancel(self._preview_job)
        self._preview_job = self.after(delay, self._render_preview) if delay else self.after_idle(self._render_preview)

    def _render_preview(self):
        self._preview_job = None
        canvas = self.preview
        cw, ch = canvas.winfo_width(), canvas.winfo_height()
        iid = self.preview_target()
        if iid is None:
            self._show_preview_message("쪽을 클릭하면 여기에 크게 표시됩니다.")
            return
        path, index = self.pages[iid]
        shown = (path, index, cw, ch)
        if shown == self._preview_shown:
            return
        bw, bh = cw - 2 * PREVIEW_PAD, ch - 2 * PREVIEW_PAD
        if bw < 20 or bh < 20:
            return
        try:
            w, h = self.docs.page_size(path, index)
            pw, ph, ppm = self.docs.render_ppm(path, index, fit_scale(w, h, bw, bh))
        except Exception as e:
            self._show_preview_message(f"이 쪽을 그릴 수 없습니다.\n{e}")
            return
        self._preview_img = tk.PhotoImage(data=ppm, format="PPM")
        canvas.delete("all")
        canvas.create_image(cw // 2, ch // 2, image=self._preview_img, anchor="center")
        self._preview_shown = shown
        self.preview_caption.set(f"{os.path.basename(path)}  ·  {index + 1}쪽")

    def _show_preview_message(self, text):
        canvas = self.preview
        canvas.delete("all")
        canvas.create_text(
            canvas.winfo_width() // 2, canvas.winfo_height() // 2, text=text, fill="#ffffff", justify="center"
        )
        self._preview_img = None
        self._preview_shown = None
        self.preview_caption.set("")

    def _on_destroy(self, event):
        if event.widget is self:
            self.docs.close_all()


# ---------------------------------------------------------------------------
def main():
    root = tk.Tk()
    root.title("PDF 도구 (렌더링판): 병합 / 페이지 추출")
    w, h = fit_window_size(*WINDOW_SIZE, root.winfo_screenwidth(), root.winfo_screenheight())
    root.geometry(f"{w}x{h}")
    root.minsize(min(900, w), min(560, h))

    notebook = ttk.Notebook(root)
    notebook.pack(fill="both", expand=True)
    notebook.add(MergeTab(notebook), text="  PDF 병합  ")
    notebook.add(RenderPageTab(notebook), text="  페이지 추출 / 편집  ")

    root.mainloop()


if __name__ == "__main__":
    main()
