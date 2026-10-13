"""
PDF 도구: 병합 / 페이지 추출 및 순서 편집 (GUI)

필요한 외부 라이브러리: pypdf 1개
    pip install pypdf
GUI는 파이썬에 기본 포함된 tkinter를 사용합니다.
실행에는 이 파일과 같은 폴더의 공통 모듈 pdf_common.py가 필요합니다.

탭 1. PDF 병합         : 여러 PDF를 파일 단위로 정렬하여 하나로 합칩니다.
탭 2. 페이지 추출/편집 : 쪽 범위를 지정해 불러오고, 쪽 단위로 마우스로 순서를 바꾸거나
                         삭제한 뒤 새 PDF로 저장합니다.
                         Ctrl+Z: 실행 취소, Ctrl+Y (또는 Ctrl+Shift+Z): 다시 실행
"""

import os
import tkinter as tk
from tkinter import filedialog, messagebox, simpledialog, ttk

from pdf_common import (
    IS_MAC,
    DragTree,
    merge_pdfs,
    open_pdf,
    parse_page_ranges,
    run_background,
    save_pages,
)


UNDO_LIMIT = 100  # 실행 취소로 되돌릴 수 있는 최대 단계 수


# ---------------------------------------------------------------------------
# 탭 1: PDF 병합 (파일 단위)
# ---------------------------------------------------------------------------
class MergeTab(ttk.Frame):
    def __init__(self, master):
        super().__init__(master)
        self.files = {}  # 행 ID -> (PDF 경로, 쪽수)
        self.working = False
        self._build_widgets()

    def _build_widgets(self):
        pad = {"padx": 10, "pady": 5}

        ttk.Label(
            self,
            text="합칠 PDF를 추가하고, 행을 마우스로 끌거나 위/아래 버튼으로 순서를 조정한 뒤 '병합하기'를 누르세요.",
        ).pack(anchor="w", **pad)

        body = ttk.Frame(self)
        body.pack(fill="both", expand=True, **pad)

        list_frame = ttk.Frame(body)
        list_frame.pack(side="left", fill="both", expand=True)
        self.tree = DragTree(
            list_frame, columns=("pos", "name", "pages", "folder"), show="headings", selectmode="extended",
        )
        self.tree.heading("pos", text="순서")
        self.tree.heading("name", text="파일 이름")
        self.tree.heading("pages", text="쪽수")
        self.tree.heading("folder", text="폴더")
        self.tree.column("pos", width=50, anchor="center", stretch=False)
        self.tree.column("name", width=220, anchor="w")
        self.tree.column("pages", width=60, anchor="center", stretch=False)
        self.tree.column("folder", width=250, anchor="w")
        scroll = ttk.Scrollbar(list_frame, orient="vertical", command=self.tree.yview)
        self.tree.configure(yscrollcommand=scroll.set)
        self.tree.pack(side="left", fill="both", expand=True)
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

    def ordered_paths(self):
        """현재 화면 순서의 PDF 경로 목록"""
        return [self.files[iid][0] for iid in self.tree.get_children()]

    def update_status(self):
        total = sum(pages for _, pages in self.files.values())
        self.status.set(f"파일 {len(self.files)}개, 총 {total}쪽")

    def add_files(self):
        paths = filedialog.askopenfilenames(
            title="PDF 파일 선택", filetypes=[("PDF 파일", "*.pdf"), ("모든 파일", "*.*")]
        )
        errors = []
        for path in paths:
            try:
                pages = len(open_pdf(path).pages)
            except ValueError as e:
                errors.append(f"{os.path.basename(path)}: {e}")
                continue
            iid = self.tree.insert(
                "", "end", values=(0, os.path.basename(path), pages, os.path.dirname(path))
            )
            self.files[iid] = (path, pages)
        self.tree.renumber()
        self.update_status()
        if errors:
            messagebox.showwarning("일부 파일을 추가하지 못했습니다", "\n".join(errors))

    def remove_selected(self):
        sel = self.tree.selection()
        for iid in sel:
            self.files.pop(iid, None)
        if sel:
            self.tree.delete(*sel)
            self.tree.renumber()
        self.update_status()

    def clear_all(self):
        self.tree.delete(*self.tree.get_children())
        self.files.clear()
        self.update_status()

    def move_selected(self, delta):
        self.tree.shift_selection(delta)

    def start_merge(self):
        if self.working:
            return
        if len(self.files) < 2:
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
        paths = self.ordered_paths()
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

    def move_to(self, position):
        before = self.snapshot()
        if self.tree.move_selection_to(position):
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
