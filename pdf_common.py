"""
PDF 도구 공통 모듈: 경량판(pdf_tool.py)과 렌더링판이 함께 사용하는 코드입니다.

- PDF 처리 로직: open_pdf, parse_page_ranges, merge_pdfs, save_pages
- 백그라운드 실행: run_background
- 마우스 드래그로 행 순서를 바꿀 수 있는 목록 위젯: DragTree

필요한 외부 라이브러리: pypdf
"""

import os
import queue
import re
import sys
import threading
import tkinter as tk
from tkinter import ttk

from pypdf import PdfReader, PdfWriter


IS_MAC = sys.platform == "darwin"


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
# 마우스 드래그로 행 순서를 바꿀 수 있는 목록 위젯
# ---------------------------------------------------------------------------
class DragTree(ttk.Treeview):
    """
    - 행을 마우스로 끌어서 순서를 바꿀 수 있습니다. 끄는 동안 놓을 위치에 가로 표시선이 나타나고,
      마우스를 놓으면 선택한 행들이 상대 순서를 유지한 채 그 위치에 모입니다.
    - 표시선은 마우스가 행의 위쪽 절반에 있으면 그 행 앞, 아래쪽 절반에 있으면 그 행 뒤에 나타납니다.
    - 끄는 중 목록 위/아래 바깥으로 마우스를 가져가면 자동으로 스크롤됩니다.
    - Ctrl+클릭: 개별 선택 추가/해제, Shift+클릭: 범위 선택
    - 행을 옮기면 옮긴 행이 화면에 보이도록 스크롤하고, 잠깐 다른 색으로 강조합니다.
    - columns에는 현재 순서를 표시하는 "pos" 열이 반드시 포함되어야 합니다.
    """

    SELECT_BG, SELECT_FG = "#2a6fdb", "#ffffff"  # 선택한 행 (목록에 포커스가 없어도 같은 색)
    FLASH_BG, FLASH_FG = "#ffb300", "#000000"    # 옮긴 직후 잠깐 표시하는 강조색
    FLASH_MS = 400
    INDICATOR_COLOR = "#d32f2f"                  # 놓을 위치 표시선
    _count = 0

    def __init__(self, master, on_reorder=None, **kw):
        # 위젯마다 별도의 스타일을 사용해서 강조색 변경이 다른 목록에 영향을 주지 않게 함
        DragTree._count += 1
        self.style_name = f"Drag{DragTree._count}.Treeview"
        self._style = ttk.Style(master)
        kw.setdefault("style", self.style_name)
        super().__init__(master, **kw)
        self._set_select_colors(self.SELECT_BG, self.SELECT_FG)
        # on_reorder(이전_행_순서): 드래그로 순서가 실제로 바뀐 뒤 호출됩니다.
        self.on_reorder = on_reorder
        self._order_before = ()
        self._dragging = False
        self._moved = False
        self._last_y = 0
        self._press_item = None
        self._anchor = None
        self._tick_id = None
        self._flash_id = None
        self._indicator = tk.Frame(self, height=3, bg=self.INDICATOR_COLOR, bd=0, highlightthickness=0)
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

    # ---- 옮긴 행 표시 ----
    def _set_select_colors(self, bg, fg):
        self._style.map(self.style_name, background=[("selected", bg)], foreground=[("selected", fg)])

    def flash_selection(self):
        """선택한 행을 잠깐 강조색으로 표시했다가 원래 선택 색으로 되돌립니다."""
        if self._flash_id is not None:
            self.after_cancel(self._flash_id)
        self._set_select_colors(self.FLASH_BG, self.FLASH_FG)
        self._flash_id = self.after(self.FLASH_MS, self._end_flash)

    def _end_flash(self):
        self._flash_id = None
        self._set_select_colors(self.SELECT_BG, self.SELECT_FG)

    def reveal_selection(self):
        """선택한 행이 화면에 보이도록 스크롤합니다. 한 화면에 다 들어가지 않으면 첫 행을 우선합니다."""
        sel = sorted(self.selection(), key=self.index)
        if sel:
            self.see(sel[-1])
            self.see(sel[0])

    def _after_move(self):
        self.reveal_selection()
        self.flash_selection()

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
        self._after_move()
        return True

    def move_selection_to(self, position):
        """선택한 행들(현재 상대 순서 유지)을 position번째(1부터) 위치로 옮깁니다. 순서가 바뀌면 True."""
        selected = set(self.selection())
        others = [c for c in self.get_children() if c not in selected]
        return self._gather_selection(min(max(position - 1, 0), len(others)))

    def _gather_selection(self, pos):
        """선택한 행들을 선택하지 않은 행 목록의 pos번째(0부터) 자리에 모읍니다. 순서가 바뀌면 True."""
        children = list(self.get_children())
        selected = set(self.selection())
        moving = [c for c in children if c in selected]
        if not moving:
            return False
        others = [c for c in children if c not in selected]
        new_order = others[:pos] + moving + others[pos:]
        if new_order == children:
            return False
        for i, iid in enumerate(new_order):
            self.move(iid, "", i)
        self.renumber()
        self._after_move()
        return True

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
        self._last_y = event.y
        self._moved = False
        self._dragging = True
        self._tick()
        return "break"

    def _on_motion(self, event):
        if not self._dragging:
            return None
        self._last_y = event.y
        # 누른 행을 벗어나야 드래그로 간주함 (같은 행 안에서 조금 움직인 것은 클릭으로 처리)
        if not self._moved and self.identify_row(event.y) != self._press_item:
            self._moved = True
        self._update_indicator()
        return "break"

    def _on_release(self, event):
        if not self._dragging:
            return None
        self._dragging = False
        if self._tick_id is not None:
            self.after_cancel(self._tick_id)
            self._tick_id = None
        self._indicator.place_forget()
        # 끌지 않고 클릭만 했다면 해당 행 하나만 선택
        if not self._moved:
            if self._press_item and self.exists(self._press_item):
                self.selection_set(self._press_item)
            return "break"
        slot = self._drop_slot(event.y)
        before = list(self.get_children())[:slot]
        selected = set(self.selection())
        if self._gather_selection(sum(1 for c in before if c not in selected)) and self.on_reorder:
            self.on_reorder(self._order_before)
        return "break"

    # ---- 드래그 동작 ----
    def _tick(self):
        """마우스 버튼을 누르고 있는 동안 주기적으로 자동 스크롤과 표시선 갱신을 수행합니다."""
        if not self._dragging:
            return
        self._auto_scroll()
        self._update_indicator()
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

    def _drop_slot(self, y):
        """
        마우스 y 좌표에 놓으면 들어갈 자리(0부터, 행 사이의 경계 번호)를 반환합니다.
        행의 위쪽 절반이면 그 행 앞, 아래쪽 절반이면 그 행 뒤입니다.
        목록 위쪽 바깥이면 보이는 첫 행 앞, 아래쪽 바깥이면 보이는 마지막 행 뒤입니다.
        """
        children = self.get_children()
        if not children:
            return 0
        if y < self._first_row_top():
            return self._first_visible()
        # 목록 아래 바깥 좌표에서는 identify_row가 화면에 보이지 않는 행을 돌려줄 수 있음.
        # 그런 행은 bbox가 비어 있으므로, 화면 안의 좌표이고 bbox가 있을 때만 그 행을 기준으로 삼음.
        row = self.identify_row(y) if y < self.winfo_height() else ""
        box = self.bbox(row) if row else ""
        if box:
            _, top, _, height = box
            index = self.index(row)
            return index if y < top + height / 2 else index + 1
        last = self.identify_row(self.winfo_height() - 1)
        return self.index(last) + 1 if last else len(children)

    def _slot_y(self, slot):
        """slot 경계의 화면 y 좌표. 경계 주변의 행이 화면에 없으면 None."""
        children = self.get_children()
        if slot < len(children):
            box = self.bbox(children[slot])
            if box:
                return box[1]
        if slot > 0:
            box = self.bbox(children[slot - 1])
            if box:
                return box[1] + box[3]
        return None

    def _update_indicator(self):
        if not self._dragging or not self._moved:
            return
        y = self._slot_y(self._drop_slot(self._last_y))
        if y is None:
            self._indicator.place_forget()
            return
        thickness = int(self._indicator.cget("height"))
        y = min(max(y - thickness // 2, self._first_row_top()), self.winfo_height() - thickness)
        self._indicator.place(x=0, y=y, relwidth=1)
        self._indicator.lift()
