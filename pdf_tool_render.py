"""
PDF 도구 렌더링판: 경량판의 기능에 쪽 썸네일과 큰 미리보기를 더한 GUI입니다.

필요한 외부 라이브러리: pypdf, pypdfium2, Pillow (Pillow는 JPG 저장에만 사용)
    pip install -r requirements-render.txt
실행에는 같은 폴더의 pdf_common.py와 pdf_render.py가 필요합니다.

탭 1. PDF 병합         : 경량판과 같습니다.
탭 2. 페이지 추출/편집 : 경량판의 기능에 더해, 쪽 목록의 각 행에 썸네일을 표시하고
                         마지막으로 클릭한 쪽을 오른쪽에 크게 보여 줍니다.
                         쪽을 PNG, JPG 이미지 파일로 저장할 수 있습니다.
"""

import math
import os
import queue
import threading
import time
import tkinter as tk
from tkinter import filedialog, messagebox, ttk

from pdf_common import MergeTab, PageTab
from pdf_render import (
    DPI_CHOICES, HAS_PILLOW, THUMB_BOX, LRUCache, PdfiumDocs,
    encode_jpg, encode_png, fit_scale, image_file_names, thumb_scale,
)


WINDOW_SIZE = (1200, 750)  # 기본 창 크기. 화면이 작으면 화면 안에 들어오도록 줄임
THUMB_CACHE_SIZE = 300     # 보관할 썸네일 수 (넘치면 오래된 것부터 버림)
THUMB_MARGIN = 2           # 화면에 보이는 행의 위아래로 미리 그려 둘 행 수
THUMB_BUDGET = 0.03        # 한 번에 썸네일을 그리는 최대 시간(초). 넘으면 이벤트 처리 후 이어서 그림
PREVIEW_DELAY_MS = 150     # 미리보기 영역 크기가 바뀐 뒤 다시 그리기까지 기다리는 시간
PREVIEW_PAD = 8            # 미리보기 그림과 영역 가장자리 사이의 여백(픽셀)
THUMB_BORDER = "#8a8a8a"   # 썸네일 테두리 색
DEFAULT_DPI = 150          # 이미지 저장 대화 상자의 기본 해상도
DEFAULT_JPG_QUALITY = 90   # 이미지 저장 대화 상자의 기본 JPG 품질 (1~95)
EXPORT_QUEUE = 2           # 이미지 저장 중 파일 변환을 기다리는 쪽 그림의 최대 수 (300 DPI 그림 1장이 약 26MB)


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
        # "새 PDF로 저장" 버튼의 왼쪽에 둠
        self.image_btn = ttk.Button(self.save_btn.master, text="이미지로 저장", command=self.save_images)
        self.image_btn.pack(side="right", padx=(0, 5))
        self._image_dialog = None
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
        # 행이 높아서 기본 높이(10행)로는 목록이 요구하는 높이가 창보다 커지고, 그러면 아래쪽의 저장 버튼과
        # 진행 막대가 밀려나 보이지 않음. 요구 높이를 작게 두고 남는 공간만큼 늘어나게 함
        tree.configure(show="tree headings", height=3)
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

    # ---- 이미지로 저장 ----
    def save_images(self):
        if self.busy:
            return
        children = self.tree.get_children()
        if not children:
            messagebox.showinfo("안내", "저장할 쪽이 없습니다. 먼저 PDF를 불러와 주세요.")
            return
        selection = set(self.tree.selection())
        # 대화 상자가 열린 동안에도 단축키(실행 취소 등)로 행 ID가 바뀔 수 있으므로 쪽 목록을 먼저 복사해 둠
        all_pages = [self.pages[iid] for iid in children]
        selected = [self.pages[iid] for iid in children if iid in selection]  # 화면 순서대로
        options = self.ask_image_options(len(selected), len(all_pages))
        if not options:
            return
        folder = filedialog.askdirectory(title="이미지를 저장할 폴더 선택", mustexist=True)
        if not folder:
            return

        pages = selected if options["scope"] == "selected" else all_pages
        ext = "jpg" if options["format"] == "JPG" else "png"
        targets = [os.path.join(folder, name) for name in image_file_names(pages, ext)]
        existing = [t for t in targets if os.path.exists(t)]
        if existing and not messagebox.askyesno(
            "덮어쓰기 확인",
            f"같은 이름의 파일이 {len(existing)}개 있습니다.\n예: {os.path.basename(existing[0])}\n\n덮어쓸까요?",
        ):
            return
        self.export_images(pages, targets, options["format"], options["dpi"], options["quality"])

    def ask_image_options(self, n_selected, n_all):
        """저장 옵션 대화 상자를 띄우고, 확인을 누르면 옵션 딕셔너리를, 취소하면 None을 반환합니다."""
        dialog = ImageSaveDialog(self, n_selected, n_all)
        self._image_dialog = dialog
        self.wait_window(dialog)
        self._image_dialog = None
        return dialog.result

    def export_images(self, pages, targets, fmt, dpi, quality=DEFAULT_JPG_QUALITY):
        """
        pages[i]를 dpi 해상도로 그려서 targets[i] 파일에 저장합니다.
        렌더링은 PDFium의 스레드 제한 때문에 메인 스레드에서 한 쪽씩 나누어 하고,
        시간이 오래 걸리는 PNG/JPG 변환과 파일 쓰기는 별도 스레드에서 합니다.
        """
        total = len(pages)
        scale = dpi / 72
        if fmt == "JPG":
            encode = lambda w, h, rgb: encode_jpg(w, h, rgb, dpi=dpi, quality=quality)
        else:
            encode = lambda w, h, rgb: encode_png(w, h, rgb, dpi=dpi)
        jobs = queue.Queue(maxsize=EXPORT_QUEUE)  # 그린 쪽 (파일 경로, 너비, 높이, RGB 바이트)
        results = queue.Queue()                   # 변환 스레드의 결과 ("saved", None) 또는 ("error", 문구)
        stop = threading.Event()

        def worker():
            while True:
                item = jobs.get()
                if item is None or stop.is_set():
                    return
                target, w, h, rgb = item
                try:
                    data = encode(w, h, rgb)
                    with open(target, "wb") as f:
                        f.write(data)
                except Exception as e:
                    results.put(("error", f"{os.path.basename(target)}: {e}"))
                    return
                results.put(("saved", None))

        state = {"next": 0, "saved": 0}

        def finish(error=None):
            stop.set()
            try:
                jobs.put_nowait(None)  # 기다리고 있는 변환 스레드를 깨워서 끝냄
            except queue.Full:
                pass  # 큐가 차 있으면 변환 스레드가 다음 항목을 꺼낼 때 stop을 보고 끝냄
            # 변환 스레드가 쓰고 있던 파일까지 끝난 뒤에 결과를 알리고 다시 저장할 수 있게 함
            wait_worker(error)

        def wait_worker(error):
            if thread.is_alive():
                self.after(20, wait_worker, error)
                return
            while not results.empty():
                kind, msg = results.get_nowait()
                if kind == "saved":
                    state["saved"] += 1
            self.busy = False
            self.save_btn.state(["!disabled"])
            self.image_btn.state(["!disabled"])
            folder = os.path.dirname(targets[0])
            if error:
                messagebox.showerror("이미지 저장 실패", f"{error}\n\n저장한 이미지: {state['saved']}개 / {total}개\n{folder}")
            else:
                self.progress["value"] = 100
                messagebox.showinfo("완료", f"이미지 {total}개를 저장했습니다.\n\n{folder}")

        def step():
            try:
                while True:
                    kind, msg = results.get_nowait()
                    if kind == "error":
                        finish(msg)
                        return
                    state["saved"] += 1
            except queue.Empty:
                pass
            self.progress["value"] = state["saved"] / total * 100
            if state["saved"] == total:
                finish()
                return
            i = state["next"]
            if i < total and not jobs.full():
                path, index = pages[i]
                try:
                    w, h, rgb = self.docs.render_rgb(path, index, scale)
                except Exception as e:
                    finish(f"{os.path.basename(path)}의 {index + 1}쪽을 그릴 수 없습니다.\n{e}")
                    return
                jobs.put_nowait((targets[i], w, h, rgb))
                state["next"] = i + 1
                self.after(1, step)  # 이벤트를 처리한 뒤 다음 쪽을 그림
            else:
                self.after(20, step)  # 변환을 기다림

        self.busy = True
        self.save_btn.state(["disabled"])
        self.image_btn.state(["disabled"])
        self.progress["value"] = 0
        thread = threading.Thread(target=worker, daemon=True)
        thread.start()
        self.after(1, step)

    def _on_destroy(self, event):
        if event.widget is self:
            self.docs.close_all()


class ImageSaveDialog(tk.Toplevel):
    """이미지 저장 옵션(저장할 쪽, 형식, 해상도, JPG 품질)을 고르는 대화 상자입니다. 결과는 self.result에 담깁니다."""

    def __init__(self, master, n_selected, n_all):
        super().__init__(master)
        self.title("이미지로 저장")
        self.resizable(False, False)
        self.transient(master.winfo_toplevel())
        self.result = None
        pad = {"padx": 12, "pady": (10, 2)}

        ttk.Label(self, text="저장할 쪽").pack(anchor="w", **pad)
        self.scope_var = tk.StringVar(value="selected" if n_selected else "all")
        sel = ttk.Radiobutton(self, text=f"선택한 쪽 ({n_selected}쪽)", variable=self.scope_var, value="selected")
        sel.pack(anchor="w", padx=24)
        if not n_selected:
            sel.state(["disabled"])
        ttk.Radiobutton(self, text=f"목록 전체 ({n_all}쪽)", variable=self.scope_var, value="all").pack(anchor="w", padx=24)

        ttk.Label(self, text="형식").pack(anchor="w", **pad)
        self.format_var = tk.StringVar(value="PNG")
        fmt = ttk.Frame(self)
        fmt.pack(anchor="w", padx=24)
        ttk.Radiobutton(fmt, text="PNG", variable=self.format_var, value="PNG", command=self._update_quality).pack(side="left")
        self.jpg_button = ttk.Radiobutton(fmt, text="JPG", variable=self.format_var, value="JPG", command=self._update_quality)
        self.jpg_button.pack(side="left", padx=(10, 0))
        if not HAS_PILLOW:
            self.jpg_button.state(["disabled"])
            ttk.Label(self, text="JPG로 저장하려면 Pillow를 설치해야 합니다.", foreground="#555555").pack(anchor="w", padx=24)

        row = ttk.Frame(self)
        row.pack(anchor="w", **pad)
        ttk.Label(row, text="해상도(DPI)").pack(side="left")
        self.dpi_var = tk.StringVar(value=str(DEFAULT_DPI))
        ttk.Combobox(row, textvariable=self.dpi_var, values=[str(d) for d in DPI_CHOICES], state="readonly", width=6).pack(
            side="left", padx=(8, 0)
        )

        row = ttk.Frame(self)
        row.pack(anchor="w", **pad)
        ttk.Label(row, text="JPG 품질(1~95)").pack(side="left")
        self.quality_var = tk.StringVar(value=str(DEFAULT_JPG_QUALITY))
        self.quality_box = ttk.Spinbox(row, from_=1, to=95, textvariable=self.quality_var, width=5)
        self.quality_box.pack(side="left", padx=(8, 0))
        self._update_quality()

        btns = ttk.Frame(self)
        btns.pack(fill="x", padx=12, pady=12)
        ttk.Button(btns, text="취소", command=self.cancel).pack(side="right")
        ttk.Button(btns, text="저장할 폴더 선택", command=self.ok).pack(side="right", padx=(0, 5))
        self.bind("<Return>", lambda e: self.ok())
        self.bind("<Escape>", lambda e: self.cancel())
        self.protocol("WM_DELETE_WINDOW", self.cancel)
        self.wait_visibility()  # 창이 화면에 나타나기 전에 grab_set을 부르면 실패할 수 있음
        self.grab_set()

    def _update_quality(self):
        self.quality_box.state(["!disabled"] if self.format_var.get() == "JPG" else ["disabled"])

    def ok(self):
        try:
            quality = int(self.quality_var.get())
        except ValueError:
            quality = 0
        if self.format_var.get() == "JPG" and not 1 <= quality <= 95:
            messagebox.showwarning("입력 오류", "JPG 품질은 1부터 95 사이의 숫자로 입력해 주세요.", parent=self)
            return
        self.result = {
            "scope": self.scope_var.get(),
            "format": self.format_var.get(),
            "dpi": int(self.dpi_var.get()),
            "quality": quality if self.format_var.get() == "JPG" else DEFAULT_JPG_QUALITY,
        }
        self.destroy()

    def cancel(self):
        self.result = None
        self.destroy()


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
