"""
PDF 도구: 병합 / 페이지 추출 및 순서 편집 (GUI)

필요한 외부 라이브러리: pypdf 1개
    pip install pypdf
GUI는 파이썬에 기본 포함된 tkinter를 사용합니다.

탭 1. PDF 병합         : 여러 PDF를 파일 단위로 정렬하여 하나로 합칩니다.
탭 2. 페이지 추출/편집 : 쪽 범위를 지정해 불러오고, 쪽 단위로 마우스로 순서를 바꾸거나
                         삭제한 뒤 새 PDF로 저장합니다.
                         Ctrl+Z: 실행 취소, Ctrl+Y (또는 Ctrl+Shift+Z): 다시 실행
"""

import os
import queue
import re
import sys
import threading
import tkinter as tk
from tkinter import filedialog, messagebox, simpledialog, ttk

from pypdf import PdfReader, PdfWriter


IS_MAC = sys.platform == "darwin"
UNDO_LIMIT = 100  # 실행 취소로 되돌릴 수 있는 최대 단계 수


# ---------------------------------------------------------------------------
# PDF 처리 로직 (GUI와 분리되어 있어 단독으로도 호출할 수 있음)
# ---------------------------------------------------------------------------
def open_pdf(path):
    """PDF를 열어 PdfReader를 반환합니다. 열 수 없으면 ValueError를 발생시킵니다."""
    try:
        reader = PdfReader(path)
        if reader.is_encrypted:
            # 열람 비밀번호가 없는 암호화 PDF는 빈 비밀번호로 해제할 수 있음
            if reader.decrypt("") == 0:
                raise ValueError("비밀번호가 설정된 PDF입니다.")
        len(reader.pages)  # 손상된 파일이면 이 시점에 예외가 발생함
        return reader
    except ValueError:
        raise
    except Exception as e:
        raise ValueError(f"PDF를 읽을 수 없습니다: {e}")


def parse_page_ranges(text, total):
    """
    쪽 범위 문자열을 0부터 시작하는 쪽 인덱스 목록으로 변환합니다.
    - 쪽 번호는 1부터 시작하며, 입력한 순서를 그대로 유지합니다.
    - 예: "721-732", "1-3, 7, 10-12", "5-" (5쪽부터 끝까지), "-3" (처음부터 3쪽까지)
    - 빈 문자열이면 전체 쪽을 의미합니다.
    """
    text = text.strip()
    if not text:
        return list(range(total))

    result = []
    for part in re.split(r"[,;]", text.replace("~", "-")):
        part = part.strip()
        if not part:
            continue
        m = re.fullmatch(r"(\d+)?\s*-\s*(\d+)?", part)
        if m:
            if m.group(1) is None and m.group(2) is None:
                raise ValueError("'-' 만으로는 범위를 지정할 수 없습니다.")
            start = int(m.group(1)) if m.group(1) else 1
            end = int(m.group(2)) if m.group(2) else total
        elif part.isdigit():
            start = end = int(part)
        else:
            raise ValueError(f"해석할 수 없는 범위입니다: '{part}'")

        if start < 1 or end > total:
            raise ValueError(f"'{part}'은(는) 문서의 쪽수(1~{total}쪽)를 벗어납니다.")
        if start > end:
            raise ValueError(f"'{part}'은(는) 시작 쪽이 끝 쪽보다 큽니다.")
        result.extend(range(start - 1, end))

    if not result:
        raise ValueError("유효한 범위가 없습니다.")
    return result


def merge_pdfs(paths, output_path, add_bookmarks=True, progress=None):
    """paths 순서대로 PDF를 합쳐 output_path에 저장합니다. 총 쪽수를 반환합니다."""
    writer = PdfWriter()
    for i, path in enumerate(paths, start=1):
        reader = open_pdf(path)
        title = os.path.splitext(os.path.basename(path))[0]
        writer.append(reader, outline_item=title if add_bookmarks else None)
        if progress:
            progress(i, len(paths))
    with open(output_path, "wb") as f:
        writer.write(f)
    return len(writer.pages)


def save_pages(pages, output_path, progress=None, readers=None):
    """
    pages: [(PDF 경로, 0부터 시작하는 쪽 인덱스), ...] 순서대로 새 PDF를 만듭니다.
    readers: {경로: PdfReader} 캐시 (없으면 새로 읽음). 저장한 총 쪽수를 반환합니다.
    """
    readers = readers if readers is not None else {}
    writer = PdfWriter()
    total = len(pages)
    for n, (path, idx) in enumerate(pages, start=1):
        if path not in readers:
            readers[path] = open_pdf(path)
        writer.add_page(readers[path].pages[idx])
        if progress and (n % 10 == 0 or n == total):
            progress(n, total)
    with open(output_path, "wb") as f:
        writer.write(f)
    return total


def run_background(widget, work, on_progress, on_done, on_error):
    """
    work(report)를 별도 스레드에서 실행합니다. report(현재, 전체)로 진행률을 보고하면
    메인 스레드에서 on_progress(퍼센트)가 호출됩니다. tkinter는 메인 스레드에서만
    안전하게 사용할 수 있으므로, 결과는 큐를 통해 전달합니다.
    """
    q = queue.Queue()

    def target():
        try:
            result = work(lambda cur, total: q.put(("progress", cur / total * 100)))
            q.put(("done", result))
        except Exception as e:
            q.put(("error", str(e)))

    def poll():
        finished = False
        try:
            while True:
                kind, value = q.get_nowait()
                if kind == "progress":
                    on_progress(value)
                elif kind == "done":
                    finished = True
                    on_done(value)
                else:
                    finished = True
                    on_error(value)
        except queue.Empty:
            pass
        if not finished:
            widget.after(100, poll)

    threading.Thread(target=target, daemon=True).start()
    widget.after(100, poll)


# ---------------------------------------------------------------------------
# 탭 1: PDF 병합 (파일 단위)
# ---------------------------------------------------------------------------
class MergeTab(ttk.Frame):
    def __init__(self, master):
        super().__init__(master)
        self.items = []  # [(경로, 쪽수), ...]
        self.working = False
        self._build_widgets()

    def _build_widgets(self):
        pad = {"padx": 10, "pady": 5}

        ttk.Label(
            self,
            text="합칠 PDF를 추가하고, 위/아래 버튼으로 순서를 조정한 뒤 '병합하기'를 누르세요.",
        ).pack(anchor="w", **pad)

        body = ttk.Frame(self)
        body.pack(fill="both", expand=True, **pad)

        list_frame = ttk.Frame(body)
        list_frame.pack(side="left", fill="both", expand=True)
        self.listbox = tk.Listbox(list_frame, selectmode="extended", activestyle="none")
        scroll = ttk.Scrollbar(list_frame, orient="vertical", command=self.listbox.yview)
        self.listbox.configure(yscrollcommand=scroll.set)
        self.listbox.pack(side="left", fill="both", expand=True)
        scroll.pack(side="right", fill="y")

        btns = ttk.Frame(body)
        btns.pack(side="right", fill="y", padx=(10, 0))
        for text, cmd in [
            ("파일 추가", self.add_files),
            ("선택 삭제", self.remove_selected),
            ("▲ 위로", lambda: self.move_selected(-1)),
            ("▼ 아래로", lambda: self.move_selected(1)),
            ("목록 비우기", self.clear_all),
        ]:
            ttk.Button(btns, text=text, command=cmd, width=12).pack(pady=3)

        self.bookmark_var = tk.BooleanVar(value=True)
        ttk.Checkbutton(
            self, text="파일 이름으로 북마크(목차) 추가", variable=self.bookmark_var
        ).pack(anchor="w", **pad)

        bottom = ttk.Frame(self)
        bottom.pack(fill="x", **pad)
        self.status = tk.StringVar(value="파일 0개, 총 0쪽")
        ttk.Label(bottom, textvariable=self.status).pack(side="left")
        self.merge_btn = ttk.Button(bottom, text="병합하기", command=self.start_merge)
        self.merge_btn.pack(side="right")

        self.progress = ttk.Progressbar(self, mode="determinate")
        self.progress.pack(fill="x", padx=10, pady=(0, 10))

    def refresh(self, keep_selection=()):
        self.listbox.delete(0, tk.END)
        for i, (path, pages) in enumerate(self.items, start=1):
            self.listbox.insert(
                tk.END, f"{i}. {os.path.basename(path)}  ({pages}쪽)  -  {os.path.dirname(path)}"
            )
        for idx in keep_selection:
            self.listbox.selection_set(idx)
        total = sum(p for _, p in self.items)
        self.status.set(f"파일 {len(self.items)}개, 총 {total}쪽")

    def add_files(self):
        paths = filedialog.askopenfilenames(
            title="PDF 파일 선택", filetypes=[("PDF 파일", "*.pdf"), ("모든 파일", "*.*")]
        )
        errors = []
        for path in paths:
            try:
                pages = len(open_pdf(path).pages)
                self.items.append((path, pages))
            except ValueError as e:
                errors.append(f"{os.path.basename(path)}: {e}")
        self.refresh()
        if errors:
            messagebox.showwarning("일부 파일을 추가하지 못했습니다", "\n".join(errors))

    def remove_selected(self):
        for i in reversed(self.listbox.curselection()):
            del self.items[i]
        self.refresh()

    def clear_all(self):
        self.items.clear()
        self.refresh()

    def move_selected(self, delta):
        sel = list(self.listbox.curselection())
        if not sel:
            return
        if delta < 0 and sel[0] == 0:
            return
        if delta > 0 and sel[-1] == len(self.items) - 1:
            return
        for i in sel if delta < 0 else reversed(sel):
            self.items[i], self.items[i + delta] = self.items[i + delta], self.items[i]
        self.refresh(keep_selection=[i + delta for i in sel])

    def start_merge(self):
        if self.working:
            return
        if len(self.items) < 2:
            messagebox.showinfo("안내", "PDF를 2개 이상 추가해 주세요.")
            return

        output = filedialog.asksaveasfilename(
            title="저장할 위치 선택",
            defaultextension=".pdf",
            initialfile="merged.pdf",
            filetypes=[("PDF 파일", "*.pdf")],
        )
        if not output:
            return
        paths = [p for p, _ in self.items]
        if os.path.abspath(output) in [os.path.abspath(p) for p in paths]:
            messagebox.showerror("오류", "저장 경로가 입력 파일과 같습니다. 다른 이름으로 저장해 주세요.")
            return

        self.working = True
        self.merge_btn.state(["disabled"])
        self.progress["value"] = 0
        add_bookmarks = self.bookmark_var.get()

        def finish():
            self.working = False
            self.merge_btn.state(["!disabled"])

        def on_done(total):
            self.progress["value"] = 100
            finish()
            messagebox.showinfo("완료", f"병합이 완료되었습니다.\n총 {total}쪽\n\n{output}")

        def on_error(msg):
            finish()
            messagebox.showerror("병합 실패", msg)

        run_background(
            self,
            lambda report: merge_pdfs(paths, output, add_bookmarks, report),
            on_progress=lambda v: self.progress.configure(value=v),
            on_done=on_done,
            on_error=on_error,
        )


# ---------------------------------------------------------------------------
# 마우스 드래그로 행 순서를 바꿀 수 있는 목록 위젯
# ---------------------------------------------------------------------------
class DragTree(ttk.Treeview):
    """
    - 행을 마우스로 끌어서 순서를 바꿀 수 있습니다. (여러 행을 선택한 채 끌면 함께 이동)
    - 끄는 중 목록 위/아래 바깥으로 마우스를 가져가면 자동으로 스크롤됩니다.
    - Ctrl+클릭: 개별 선택 추가/해제, Shift+클릭: 범위 선택
    - columns에는 현재 순서를 표시하는 "pos" 열이 반드시 포함되어야 합니다.
    """

    def __init__(self, master, on_reorder=None, **kw):
        super().__init__(master, **kw)
        # on_reorder(이전_행_순서): 드래그로 순서가 실제로 바뀐 뒤 호출됩니다.
        self.on_reorder = on_reorder
        self._order_before = ()
        self._dragging = False
        self._moved = False
        self._grab = 0  # 마우스로 잡은 행의 현재 위치
        self._last_y = 0
        self._press_item = None
        self._anchor = None
        self._tick_id = None
        # macOS에서는 Command 키(0x8)도 개별 선택에 사용
        self._multi_mask = 0x4 | (0x8 if sys.platform == "darwin" else 0)

        self.bind("<ButtonPress-1>", self._on_press)
        self.bind("<B1-Motion>", self._on_motion)
        self.bind("<ButtonRelease-1>", self._on_release)

    # ---- 순서 표시 ----
    def renumber(self, lo=0, hi=None):
        children = self.get_children()
        hi = len(children) - 1 if hi is None else min(hi, len(children) - 1)
        for i in range(max(lo, 0), hi + 1):
            self.set(children[i], "pos", i + 1)

    # ---- 버튼으로도 사용할 수 있는 이동 기능 ----
    def shift_selection(self, step):
        """선택한 행들을 step(-1 또는 +1)칸 이동합니다. 끝에 닿아 이동하지 못하면 False."""
        children = self.get_children()
        idx = sorted(self.index(i) for i in self.selection())
        if not idx:
            return False
        if (step < 0 and idx[0] == 0) or (step > 0 and idx[-1] == len(children) - 1):
            return False
        for i in idx if step < 0 else reversed(idx):
            self.move(children[i], "", i + step)
        self.renumber(idx[0] - 1, idx[-1] + 1)
        return True

    def move_selection_to(self, position):
        """선택한 행들(현재 상대 순서 유지)을 position번째(1부터) 위치로 옮깁니다."""
        children = list(self.get_children())
        selected = set(self.selection())
        moving = [c for c in children if c in selected]
        if not moving:
            return
        others = [c for c in children if c not in selected]
        pos = min(max(position - 1, 0), len(others))
        for i, iid in enumerate(others[:pos] + moving + others[pos:]):
            self.move(iid, "", i)
        self.renumber()
        self.see(moving[0])

    # ---- 마우스 처리 ----
    def _on_press(self, event):
        if self.identify_region(event.x, event.y) not in ("tree", "cell"):
            return None  # 열 머리글 등은 기본 동작에 맡김
        self.focus_set()
        item = self.identify_row(event.y)
        self._dragging = False

        if not item:
            self.selection_set(())
            return "break"
        if event.state & self._multi_mask:
            self.selection_toggle(item)
            self._anchor = item
            return "break"
        if event.state & 0x1 and self._anchor and self.exists(self._anchor):
            children = self.get_children()
            a, b = sorted((self.index(self._anchor), self.index(item)))
            self.selection_set(children[a : b + 1])
            return "break"

        # 이미 선택된 행을 누르면 선택을 유지한 채 끌 수 있게 함 (여러 행 동시 이동)
        if item not in self.selection():
            self.selection_set(item)
        self._anchor = item
        self._press_item = item
        self._order_before = self.get_children()
        self._grab = self.index(item)
        self._last_y = event.y
        self._moved = False
        self._dragging = True
        self._tick()
        return "break"

    def _on_motion(self, event):
        if not self._dragging:
            return None
        self._last_y = event.y
        self._follow()
        return "break"

    def _on_release(self, event):
        if not self._dragging:
            return None
        self._dragging = False
        if self._tick_id is not None:
            self.after_cancel(self._tick_id)
            self._tick_id = None
        # 끌지 않고 클릭만 했다면 해당 행 하나만 선택
        if not self._moved and self._press_item and self.exists(self._press_item):
            self.selection_set(self._press_item)
        if self._moved and self.on_reorder and self.get_children() != self._order_before:
            self.on_reorder(self._order_before)
        return "break"

    # ---- 드래그 동작 ----
    def _tick(self):
        """마우스 버튼을 누르고 있는 동안 주기적으로 자동 스크롤과 위치 추적을 수행합니다."""
        if not self._dragging:
            return
        self._auto_scroll()
        self._follow()
        self._tick_id = self.after(30, self._tick)

    def _first_visible(self):
        n = len(self.get_children())
        return min(max(int(round(self.yview()[0] * n)), 0), max(n - 1, 0))

    def _first_row_top(self):
        children = self.get_children()
        box = self.bbox(children[self._first_visible()]) if children else ""
        return box[1] if box else 0

    def _auto_scroll(self):
        if not self.get_children():
            return
        y, h, top = self._last_y, self.winfo_height(), self._first_row_top()
        if y < top:
            self.yview_scroll(-(1 + (top - y) // 10), "units")
        elif y > h:
            self.yview_scroll(1 + (y - h) // 10, "units")

    def _target_index(self, y):
        """마우스 y 좌표가 가리키는 행의 위치. 목록 밖이면 보이는 첫/마지막 행."""
        row = self.identify_row(y)
        if row:
            return self.index(row)
        if y < self._first_row_top():
            return self._first_visible()
        last = self.identify_row(self.winfo_height() - 1)
        return self.index(last) if last else len(self.get_children()) - 1

    def _follow(self):
        """잡고 있는 행(들)이 마우스 위치를 따라가도록 이동합니다."""
        if not self._dragging or not self.get_children():
            return
        target = self._target_index(self._last_y)
        if target == self._grab:
            return
        sel = self.selection()
        if len(sel) == 1:
            cur = self.index(sel[0])
            self.move(sel[0], "", target)
            self.renumber(min(cur, target), max(cur, target))
            self._grab = target
            self._moved = True
            return
        while self._grab != target:
            step = 1 if target > self._grab else -1
            if not self.shift_selection(step):
                break
            self._grab += step
            self._moved = True


# ---------------------------------------------------------------------------
# 탭 2: 페이지 추출 / 순서 편집 (쪽 단위)
# ---------------------------------------------------------------------------
class PageTab(ttk.Frame):
    def __init__(self, master):
        super().__init__(master)
        self.pages = {}    # 행 ID -> (PDF 경로, 0부터 시작하는 쪽 인덱스)
        self.readers = {}  # PDF 경로 -> PdfReader (다시 읽지 않도록 보관)
        self.busy = False
        self._undo = []    # 작업 직전의 쪽 목록 기록 [[(경로, 인덱스), ...], ...]
        self._redo = []
        self._build_widgets()
        self._bind_shortcuts()

    def _build_widgets(self):
        pad = {"padx": 10, "pady": 5}

        # 상단: 범위 입력과 불러오기
        top = ttk.Frame(self)
        top.pack(fill="x", **pad)
        ttk.Label(top, text="불러올 쪽 범위:").pack(side="left")
        self.range_var = tk.StringVar()
        entry = ttk.Entry(top, textvariable=self.range_var, width=22)
        entry.pack(side="left", padx=5)
        entry.bind("<Return>", lambda e: self.load_pdfs())
        ttk.Button(top, text="PDF 불러오기", command=self.load_pdfs).pack(side="left", padx=5)
        ttk.Label(
            self,
            text="범위 예: 721-732  /  1-3, 10, 15-20  /  5-  (비워 두면 전체).  쪽 번호는 PDF 뷰어의 쪽 번호 기준입니다.",
            foreground="#555555",
        ).pack(anchor="w", padx=10)

        # 본문: 쪽 목록과 오른쪽 버튼
        body = ttk.Frame(self)
        body.pack(fill="both", expand=True, **pad)

        list_frame = ttk.Frame(body)
        list_frame.pack(side="left", fill="both", expand=True)
        self.tree = DragTree(
            list_frame, on_reorder=self._on_reorder,
            columns=("pos", "file", "page"), show="headings", selectmode="extended",
        )
        self.tree.heading("pos", text="새 순서")
        self.tree.heading("file", text="원본 파일")
        self.tree.heading("page", text="원본 쪽")
        self.tree.column("pos", width=70, anchor="center", stretch=False)
        self.tree.column("file", width=300, anchor="w")
        self.tree.column("page", width=80, anchor="center", stretch=False)
        scroll = ttk.Scrollbar(list_frame, orient="vertical", command=self.tree.yview)
        self.tree.configure(yscrollcommand=scroll.set)
        self.tree.pack(side="left", fill="both", expand=True)
        scroll.pack(side="right", fill="y")
        self.tree.bind("<Delete>", lambda e: self.delete_selected())
        self.tree.bind("<Control-a>", self.select_all)
        if IS_MAC:
            self.tree.bind("<Command-a>", self.select_all)

        btns = ttk.Frame(body)
        btns.pack(side="right", fill="y", padx=(10, 0))
        for text, cmd in [
            ("선택 삭제", self.delete_selected),
            ("▲ 위로", lambda: self.shift(-1)),
            ("▼ 아래로", lambda: self.shift(1)),
            ("맨 위로", lambda: self.move_to(1)),
            ("맨 아래로", lambda: self.move_to(10**9)),
            ("위치 지정 이동", self.move_to_dialog),
            ("전체 선택", self.select_all),
            ("목록 비우기", self.clear_all),
        ]:
            ttk.Button(btns, text=text, command=cmd, width=14).pack(pady=3)

        ttk.Label(
            self,
            text="행을 마우스로 끌어 순서를 바꿀 수 있습니다. Ctrl/Shift+클릭으로 여러 쪽을 선택해 함께 옮길 수 있습니다.",
            foreground="#555555",
        ).pack(anchor="w", padx=10)

        # 하단
        bottom = ttk.Frame(self)
        bottom.pack(fill="x", **pad)
        self.status = tk.StringVar(value="총 0쪽")
        ttk.Label(bottom, textvariable=self.status).pack(side="left")
        self.save_btn = ttk.Button(bottom, text="새 PDF로 저장", command=self.save)
        self.save_btn.pack(side="right")

        self.progress = ttk.Progressbar(self, mode="determinate")
        self.progress.pack(fill="x", padx=10, pady=(0, 10))

    # ---- 불러오기 ----
    def load_pdfs(self):
        if self.busy:
            return
        range_text = self.range_var.get()
        paths = filedialog.askopenfilenames(
            title="PDF 파일 선택", filetypes=[("PDF 파일", "*.pdf"), ("모든 파일", "*.*")]
        )
        if not paths:
            return

        before = self.snapshot()
        errors, first_new, added = [], None, 0
        for path in paths:
            try:
                reader = self.readers.get(path) or open_pdf(path)
                indices = parse_page_ranges(range_text, len(reader.pages))
            except ValueError as e:
                errors.append(f"{os.path.basename(path)}: {e}")
                continue
            self.readers[path] = reader
            for idx in indices:
                iid = self.tree.insert("", "end", values=(0, os.path.basename(path), idx + 1))
                self.pages[iid] = (path, idx)
                first_new = first_new or iid
            added += len(indices)
        if added:
            self._push_undo(before)
        self.tree.renumber()
        self.update_status()
        if first_new:
            self.tree.see(first_new)
        if errors:
            messagebox.showwarning("일부 파일을 추가하지 못했습니다", "\n".join(errors))

    # ---- 실행 취소 / 다시 실행 ----
    def snapshot(self):
        """현재 화면 순서의 쪽 목록 [(PDF 경로, 쪽 인덱스), ...]"""
        return [self.pages[iid] for iid in self.tree.get_children()]

    def _push_undo(self, snap):
        self._undo.append(snap)
        del self._undo[:-UNDO_LIMIT]
        self._redo.clear()

    def _on_reorder(self, iids_before):
        """드래그로 순서가 바뀐 경우, 바뀌기 전 순서를 기록합니다."""
        self._push_undo([self.pages[iid] for iid in iids_before])

    def _restore(self, snap):
        top = self.tree.yview()[0]  # 스크롤 위치 유지
        self.tree.delete(*self.tree.get_children())
        self.pages.clear()
        for path, idx in snap:
            iid = self.tree.insert("", "end", values=(0, os.path.basename(path), idx + 1))
            self.pages[iid] = (path, idx)
        self.tree.renumber()
        self.update_status()
        self.tree.update_idletasks()
        self.tree.yview_moveto(top)

    def undo(self):
        if self.busy or not self._undo:
            return
        self._redo.append(self.snapshot())
        self._restore(self._undo.pop())

    def redo(self):
        if self.busy or not self._redo:
            return
        self._undo.append(self.snapshot())
        self._restore(self._redo.pop())

    def _bind_shortcuts(self):
        """버튼에 포커스가 있어도 동작하도록 창 전체에 등록하고, 이 탭이 보일 때만 처리합니다."""
        mods = ["Control"] + (["Command"] if IS_MAC else [])
        for mod in mods:
            for key in ("z", "Z", "y", "Y"):
                self.bind_all(f"<{mod}-{key}>", self._on_undo_key, add="+")

    def _on_undo_key(self, event):
        if not self.winfo_ismapped():
            return None
        if isinstance(event.widget, (tk.Entry, ttk.Entry)):
            return None  # 입력 칸에서는 기본 동작 유지
        key = event.keysym.lower()
        if key == "y" or (key == "z" and event.state & 0x1):  # Ctrl+Y, Ctrl+Shift+Z
            self.redo()
        else:
            self.undo()
        return "break"

    # ---- 편집 ----
    def update_status(self):
        self.status.set(f"총 {len(self.tree.get_children())}쪽")

    def delete_selected(self):
        if self.busy:
            return "break"
        sel = self.tree.selection()
        if sel:
            self._push_undo(self.snapshot())
        for iid in sel:
            self.pages.pop(iid, None)
        if sel:
            self.tree.delete(*sel)
            self.tree.renumber()
            self.update_status()
        return "break"

    def clear_all(self):
        if self.busy or not self.pages:
            return
        self._push_undo(self.snapshot())
        self.tree.delete(*self.tree.get_children())
        self.pages.clear()
        self.update_status()

    def select_all(self, event=None):
        self.tree.selection_set(self.tree.get_children())
        return "break"

    def shift(self, step):
        before = self.snapshot()
        if self.tree.shift_selection(step):
            self._push_undo(before)
            sel = self.tree.selection()
            if sel:
                self.tree.see(sel[0])

    def move_to(self, position):
        before = self.snapshot()
        self.tree.move_selection_to(position)
        if self.snapshot() != before:
            self._push_undo(before)

    def move_to_dialog(self):
        if not self.tree.selection():
            messagebox.showinfo("안내", "이동할 쪽을 먼저 선택해 주세요.")
            return
        total = len(self.tree.get_children())
        pos = simpledialog.askinteger(
            "위치 지정 이동",
            f"선택한 쪽을 몇 번째 위치로 옮길까요? (1~{total})",
            parent=self, minvalue=1, maxvalue=total,
        )
        if pos:
            self.move_to(pos)

    # ---- 저장 ----
    def save(self):
        if self.busy:
            return
        children = self.tree.get_children()
        if not children:
            messagebox.showinfo("안내", "저장할 쪽이 없습니다. 먼저 PDF를 불러와 주세요.")
            return
        output = filedialog.asksaveasfilename(
            title="저장할 위치 선택",
            defaultextension=".pdf",
            initialfile="extracted.pdf",
            filetypes=[("PDF 파일", "*.pdf")],
        )
        if not output:
            return

        pages = [self.pages[iid] for iid in children]  # 현재 화면 순서 그대로
        self.busy = True
        self.save_btn.state(["disabled"])
        self.progress["value"] = 0

        def finish():
            self.busy = False
            self.save_btn.state(["!disabled"])

        def on_done(total):
            self.progress["value"] = 100
            finish()
            messagebox.showinfo("완료", f"저장이 완료되었습니다.\n총 {total}쪽\n\n{output}")

        def on_error(msg):
            finish()
            messagebox.showerror("저장 실패", msg)

        run_background(
            self,
            lambda report: save_pages(pages, output, report, self.readers),
            on_progress=lambda v: self.progress.configure(value=v),
            on_done=on_done,
            on_error=on_error,
        )


# ---------------------------------------------------------------------------
def main():
    root = tk.Tk()
    root.title("PDF 도구: 병합 / 페이지 추출")
    root.geometry("780x560")
    root.minsize(640, 460)

    notebook = ttk.Notebook(root)
    notebook.pack(fill="both", expand=True)
    notebook.add(MergeTab(notebook), text="  PDF 병합  ")
    notebook.add(PageTab(notebook), text="  페이지 추출 / 편집  ")

    root.mainloop()


if __name__ == "__main__":
    main()
