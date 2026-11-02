"""
PDF 도구 공통 모듈: 경량판(pdf_tool.py)과 렌더링판이 함께 사용하는 코드입니다.

- PDF 처리 로직: open_pdf, parse_page_ranges, merge_pdfs, save_pages, outline_entries
- 백그라운드 실행: run_background
- 마우스 드래그로 행 순서를 바꿀 수 있는 목록 위젯: DragTree
- 화면: PageTab (페이지 추출 / 편집 / 병합, 메뉴 막대와 우클릭 메뉴)

필요한 외부 라이브러리: pypdf
"""

import importlib.metadata
import os
import platform
import queue
import re
import sys
import threading
import tkinter as tk
from tkinter import filedialog, messagebox, simpledialog, ttk

from pypdf import PdfReader, PdfWriter
from pypdf.generic import ArrayObject, ByteStringObject, Fit, NameObject, TextStringObject


IS_MAC = sys.platform == "darwin"
UNDO_LIMIT = 100  # 실행 취소로 되돌릴 수 있는 최대 단계 수
MOD = "Cmd" if IS_MAC else "Ctrl"  # 메뉴에 표시하는 단축키 수정자 키 이름


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


def dest_fit(dest):
    """
    pypdf의 Destination에서 쪽 안의 위치(예: /XYZ 왼쪽 위쪽 배율)를 Fit으로 꺼냅니다.
    읽을 수 없으면 쪽 전체 보기(/Fit)를 반환합니다.
    """
    try:
        return Fit(dest["/Type"], list(dest.dest_array)[2:])
    except Exception:
        return Fit.fit()


def outline_entries(reader):
    """
    원본 PDF의 북마크(목차)를 [(제목, 0부터 시작하는 쪽 인덱스 또는 None, 깊이, 쪽 안의 위치), ...]로 펼칩니다.
    쪽 안의 위치는 dest_fit의 결과입니다. 순서는 목차에 보이는 순서(깊이 우선)입니다.
    목차를 읽을 수 없으면 빈 목록을 반환합니다.
    """
    entries = []

    def walk(items, depth):
        for item in items:
            if isinstance(item, list):  # 바로 앞 항목의 하위 항목들
                walk(item, depth + 1)
                continue
            try:
                index = reader.get_destination_page_number(item)
            except Exception:
                index = None
            entries.append((item.title, index, depth, dest_fit(item)))

    try:
        walk(reader.outline, 0)
    except Exception:
        return []
    return entries


def save_pages(pages, output_path, progress=None, readers=None, file_bookmarks=False, keep_outlines=False):
    """
    pages: [(PDF 경로, 0부터 시작하는 쪽 인덱스), ...] 순서대로 새 PDF를 만듭니다.
    readers: {경로: PdfReader} 캐시 (없으면 새로 읽음). 저장한 총 쪽수를 반환합니다.
    file_bookmarks: 같은 파일의 쪽이 이어지는 구간마다 그 첫 쪽에 파일 이름 북마크를 추가합니다.
    keep_outlines: 원본 PDF의 북마크 중 가리키는 쪽이 결과에 들어 있는 것을 유지합니다.
        같은 쪽이 여러 번 들어 있으면 처음 나오는 위치를 가리킵니다. 상위 항목이 빠지면
        남아 있는 가장 가까운 상위 항목(없으면 그 쪽이 속한 구간의 파일 이름 북마크) 아래에 둡니다.
        파일 이름 북마크를 만들 때는 같은 구간에 있는 상위 항목만 사용합니다.
    본문의 링크(인용 번호, 그림 번호 등)가 가리키는 이름 붙은 대상(named destination)은
    옵션과 관계없이 원본의 쪽 안 위치를 유지합니다(copy_named_destinations).
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

    # 쪽 위치 -> 그 위치가 속한 구간의 번호와 파일 이름 북마크 (만들지 않으면 None)
    run_of = [0] * total
    run_item = [None] * total
    run, item = -1, None
    for pos, (path, _) in enumerate(pages):
        if pos == 0 or path != pages[pos - 1][0]:
            run += 1
            title = os.path.splitext(os.path.basename(path))[0]
            item = writer.add_outline_item(title, pos) if file_bookmarks else None
        run_of[pos], run_item[pos] = run, item

    first_pos = {}  # (경로, 쪽 인덱스) -> 결과에서 처음 나오는 위치
    for pos, key in enumerate(pages):
        first_pos.setdefault(key, pos)
    copy_named_destinations(writer, pages, readers, first_pos)

    if keep_outlines:
        for path in dict.fromkeys(p for p, _ in pages):  # 파일이 처음 나오는 순서
            stack = []  # [(깊이, 추가한 북마크, 구간 번호), ...] 현재 항목의 상위 항목들
            for title, index, depth, fit in outline_entries(readers[path]):
                while stack and stack[-1][0] >= depth:
                    stack.pop()
                pos = first_pos.get((path, index))
                if pos is None:
                    continue
                parent = run_item[pos]
                for _, ancestor, ancestor_run in reversed(stack):
                    if not file_bookmarks or ancestor_run == run_of[pos]:
                        parent = ancestor
                        break
                item = writer.add_outline_item(title, pos, parent=parent, fit=fit)
                stack.append((depth, item, run_of[pos]))

    with open(output_path, "wb") as f:
        writer.write(f)
    return total


def copy_named_destinations(writer, pages, readers, first_pos):
    """
    원본 PDF의 이름 붙은 대상(named destination)을 쪽 안의 위치(좌표)까지 그대로 결과에 옮깁니다.
    LaTeX(hyperref)로 만든 논문의 인용 번호, 그림 번호, 절 번호 링크는 이 이름을 가리킵니다.
    pypdf의 add_page는 이 이름을 저장할 때 쪽 맨 위(/FitH)로 다시 만들기 때문에, 그보다 먼저
    원본 좌표로 등록해 둡니다(pypdf는 이미 있는 이름은 다시 만들지 않음).
    - 가리키는 쪽이 결과에 없는 이름은 옮기지 않습니다. 같은 쪽이 여러 번 들어 있으면 처음 나오는 위치를 가리킵니다.
    - 여러 PDF를 합칠 때 앞 파일과 이름이 겹치면(예: 두 논문 모두 "figure.1") 뒤 파일의 이름을 "이름~2"처럼
      바꾸고, 그 파일에서 온 쪽의 링크도 바꾼 이름을 가리키게 합니다. 그대로 두면 뒤 논문의 링크가
      앞 논문의 위치로 이동합니다.
    """
    used = set()     # 앞 파일들이 가진 이름
    entries = {}     # 결과에 넣을 이름 -> 대상 배열
    renames = {}     # 경로 -> {원래 이름: 바꾼 이름} (바뀐 것만)
    for path in dict.fromkeys(p for p, _ in pages):  # 파일이 처음 나오는 순서
        reader = readers[path]
        try:
            named = reader.named_destinations
        except Exception:
            continue
        # 겹치지 않는 이름은 그대로 두고 먼저 예약함. 겹치는 이름에는 앞 파일, 이 파일의 다른 이름,
        # 이미 새로 붙인 이름과 모두 다른 이름을 붙임 (이 파일에 "figure.1~2"가 원래 있을 수도 있음)
        mapping = {name: name for name in named if name not in used}
        taken = used | set(named)
        for name in named:
            if name in mapping:
                continue
            new, k = f"{name}~2", 3
            while new in taken:
                new, k = f"{name}~{k}", k + 1
            mapping[name] = new
            taken.add(new)
        used.update(mapping.values())
        renames[path] = {old: new for old, new in mapping.items() if old != new}
        for name, dest in named.items():
            try:
                pos = first_pos.get((path, reader.get_destination_page_number(dest)))
            except Exception:
                continue
            if pos is None:
                continue
            fit = dest_fit(dest)
            entries[mapping[name]] = ArrayObject([writer.pages[pos].indirect_reference, fit.fit_type] + fit.fit_args)

    for pos, (path, _) in enumerate(pages):
        if renames.get(path):
            _rename_link_targets(writer.pages[pos], renames[path])

    if entries:
        root = writer.get_named_dest_root()  # [이름, 대상, 이름, 대상, ...] 이름 순서로 정렬된 배열
        existing = {str(root[i]): root[i + 1] for i in range(0, len(root) - 1, 2)}
        existing.update(entries)
        root.clear()
        for name in sorted(existing):
            root.extend([TextStringObject(name), existing[name]])


def _rename_link_targets(page, mapping):
    """쪽의 링크 주석이 가리키는 이름(/Dest 또는 /A의 /D)을 mapping에 따라 바꿉니다."""
    for ref in page.get("/Annots") or []:
        annot = ref.get_object()
        if annot.get("/Subtype") != "/Link":
            continue
        dest = annot.get("/Dest")
        if isinstance(dest, (TextStringObject, ByteStringObject)) and str(dest) in mapping:
            annot[NameObject("/Dest")] = TextStringObject(mapping[str(dest)])
        action = annot.get("/A")
        if action is not None:
            action = action.get_object()
            target = action.get("/D")
            if action.get("/S") == "/GoTo" and isinstance(target, (TextStringObject, ByteStringObject)) \
                    and str(target) in mapping:
                # 같은 동작 객체를 다른 쪽이 함께 쓰고 있을 수 있으므로 고치지 않고 새로 만들어 바꿔 끼움
                new_action = action.__class__(action)
                new_action[NameObject("/D")] = TextStringObject(mapping[str(target)])
                annot[NameObject("/A")] = new_action


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

    def select_for_context(self, item):
        """
        우클릭한 행의 선택 규칙: 이미 선택된 행이면 선택을 유지하고(여러 쪽에 한꺼번에 적용),
        선택되지 않은 행이면 그 행 하나만 선택합니다. 그 행을 포커스 행으로도 기록합니다.
        """
        if item not in self.selection():
            self.selection_set(item)
            self._anchor = item
        if self.focus() != item:
            self.focus(item)
            self.event_generate("<<RowFocus>>")

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
        # 마지막으로 클릭한 행을 Treeview의 포커스 행으로 기록함. 선택이 바뀌지 않는 클릭도 있으므로
        # (이미 선택된 행 클릭) 별도의 가상 이벤트로 알림. 렌더링판의 미리보기가 이 행을 따라감.
        if self.focus() != item:
            self.focus(item)
            self.event_generate("<<RowFocus>>")
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


# ---------------------------------------------------------------------------
# 페이지 추출 / 순서 편집 / 병합 화면 (쪽 단위)
# ---------------------------------------------------------------------------
class PageTab(ttk.Frame):
    def __init__(self, master):
        super().__init__(master)
        self.pages = {}    # 행 ID -> (PDF 경로, 0부터 시작하는 쪽 인덱스)
        self.readers = {}  # PDF 경로 -> PdfReader (다시 읽지 않도록 보관)
        self.busy = False
        self._undo = []    # 작업 직전의 쪽 목록 기록 [[(경로, 인덱스), ...], ...]
        self._redo = []
        self.menubar = None       # make_menubar로 만든 메뉴 막대 (창에 붙인 경우)
        self.menus = {}           # 메뉴 이름 -> Menu ("파일", "편집", "도움말")
        self._menu_conds = {}     # Menu 경로 -> [(항목 위치, 조건), ...]
        self._menu_index = {}     # (Menu 경로, 항목 이름) -> 항목 위치
        self._context_path = None  # 우클릭한 행의 PDF 경로 (행이 아닌 곳을 우클릭하면 None)
        self._build_widgets()
        self._build_context_menu()
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

        list_frame = self._make_list_frame(body)
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
        self.tree_scroll = scroll
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

        hint = ttk.Label(
            self,
            text="행을 마우스로 끌어 순서를 바꿀 수 있습니다. Ctrl/Shift+클릭으로 여러 쪽을 선택해 함께 옮길 수 있습니다.\n"
                 "여러 PDF를 불러오면 목록 순서대로 이어 붙여 하나의 PDF로 저장합니다.",
            foreground="#555555",
        )
        hint.pack(anchor="w", padx=10)

        # 저장 옵션
        opts = ttk.Frame(self)
        opts.pack(fill="x", padx=10, pady=(5, 0))
        self.keep_outline_var = tk.BooleanVar(value=True)
        self.keep_outline_check = ttk.Checkbutton(
            opts, text="원본 북마크(목차) 유지", variable=self.keep_outline_var
        )
        self.keep_outline_check.pack(side="left")
        self.file_bookmark_var = tk.BooleanVar(value=False)
        ttk.Checkbutton(
            opts, text="파일 이름으로 북마크 추가", variable=self.file_bookmark_var
        ).pack(side="left", padx=(15, 0))

        # 하단
        bottom = ttk.Frame(self)
        bottom.pack(fill="x", **pad)
        self.status = tk.StringVar(value="총 0쪽")
        ttk.Label(bottom, textvariable=self.status).pack(side="left")
        self.save_btn = ttk.Button(bottom, text="새 PDF로 저장", command=self.save)
        self.save_btn.pack(side="right")

        self.progress = ttk.Progressbar(self, mode="determinate")
        self.progress.pack(fill="x", padx=10, pady=(0, 10))

        # 창이 낮을 때 저장 버튼과 진행 막대가 밀려나지 않고 쪽 목록이 줄어들도록, 목록 아래의 위젯들을
        # 아래쪽부터 먼저 배치함 (pack은 먼저 배치한 위젯에 공간을 먼저 줌). 화면에 보이는 순서는 그대로임
        for w in (self.progress, bottom, opts, hint):
            w.pack_configure(side="bottom", before=body)

    def _make_list_frame(self, body):
        """쪽 목록을 담을 프레임을 만들어 배치합니다. 렌더링판은 이 메서드를 바꿔서 미리보기 영역을 함께 둡니다."""
        list_frame = ttk.Frame(body)
        list_frame.pack(side="left", fill="both", expand=True)
        return list_frame

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
            # 불러오기(O)와 저장(S). 대문자는 Caps Lock이 켜진 경우
            for key, action in (("o", self.load_pdfs), ("s", self.save)):
                for k in (key, key.upper()):
                    self.bind_all(f"<{mod}-{k}>", lambda e, a=action: self._on_file_key(e, a), add="+")

    def _on_file_key(self, event, action):
        if not self.winfo_ismapped():
            return None
        # 대화 상자(이미지 저장 옵션 등)가 열린 동안에는 처리하지 않음
        try:
            if event.widget.winfo_toplevel() is not self.winfo_toplevel():
                return None
        except (AttributeError, KeyError, tk.TclError):
            return None
        action()
        return "break"

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

    # ---- 메뉴 막대와 우클릭 메뉴 ----
    # 메뉴 항목은 (이름, 동작, 단축키 표시, 조건) 또는 None(구분선)입니다. 조건은 항목을 켤 때를 정합니다.
    #   None: 작업 중(저장 등)이 아닐 때, "always": 항상, "rows": 목록에 쪽이 있을 때,
    #   "selection": 선택한 쪽이 있을 때, "undo"/"redo": 되돌릴 기록이 있을 때, "row": 행을 우클릭했을 때
    APP_NAME = "PDF 도구"
    EDITION = "경량판"
    LIBRARIES = ("pypdf",)  # 프로그램 정보에 버전을 표시할 라이브러리 (배포 이름)

    def _file_menu_items(self):
        return [
            ("PDF 불러오기...", self.load_pdfs, f"{MOD}+O", None),
            ("새 PDF로 저장...", self.save, f"{MOD}+S", "rows"),
        ]

    def _move_menu_items(self):
        return [
            ("위로", lambda: self.shift(-1), None, "selection"),
            ("아래로", lambda: self.shift(1), None, "selection"),
            ("맨 위로", lambda: self.move_to(1), None, "selection"),
            ("맨 아래로", lambda: self.move_to(10**9), None, "selection"),
            ("위치 지정 이동...", self.move_to_dialog, None, "selection"),
        ]

    def menu_items(self):
        """메뉴 막대의 구성 [(메뉴 이름, [항목, ...]), ...]"""
        return [
            ("파일", self._file_menu_items() + [None, ("종료", self.quit_app, None, "always")]),
            ("편집", [
                ("실행 취소", self.undo, f"{MOD}+Z", "undo"),
                ("다시 실행", self.redo, f"{MOD}+Y", "redo"),
                None,
                ("전체 선택", self.select_all, f"{MOD}+A", "rows"),
                ("선택 삭제", self.delete_selected, "Delete", "selection"),
                None,
                *self._move_menu_items(),
                None,
                ("목록 비우기", self.clear_all, None, "rows"),
            ]),
            ("도움말", [
                ("단축키와 마우스 사용법", self.show_shortcuts, None, "always"),
                ("프로그램 정보", self.show_about, None, "always"),
            ]),
        ]

    def context_menu_items(self):
        """쪽 목록의 우클릭 메뉴 구성"""
        return [
            ("이 파일의 쪽 모두 선택", self.select_file_pages, None, "row"),
            None,
            *self._move_menu_items(),
            None,
            ("선택 삭제", self.delete_selected, "Delete", "selection"),
        ]

    def make_menubar(self, root):
        """창(root)에 메뉴 막대를 만들어 붙입니다. 각 메뉴를 열 때마다 항목의 사용 가능 여부를 갱신합니다."""
        menubar = tk.Menu(root, tearoff=0)
        self.menus = {}
        for name, items in self.menu_items():
            menu = tk.Menu(menubar, tearoff=0)
            self._fill_menu(menu, items)
            menu.configure(postcommand=lambda m=menu: self.update_menu(m))
            menubar.add_cascade(label=name, menu=menu)
            self.menus[name] = menu
        root.configure(menu=menubar)
        self.menubar = menubar
        return menubar

    def _fill_menu(self, menu, items):
        conds = []
        for item in items:
            if item is None:
                menu.add_separator()
                continue
            label, command, accel, cond = item
            menu.add_command(label=label, command=command, accelerator=accel or "")
            index = menu.index("end")
            conds.append((index, cond))
            self._menu_index[(str(menu), label)] = index
        self._menu_conds[str(menu)] = conds

    def menu_entry(self, menu, label):
        """메뉴 항목의 위치. 항목 이름은 메뉴를 만들 때의 이름입니다(우클릭 메뉴의 파일 이름 표시는 제외)."""
        return self._menu_index[(str(menu), label)]

    def _menu_condition(self, cond):
        if cond == "always":
            return True
        if self.busy:
            return False
        if cond == "rows":
            return bool(self.tree.get_children())
        if cond == "selection":
            return bool(self.tree.selection())
        if cond == "undo":
            return bool(self._undo)
        if cond == "redo":
            return bool(self._redo)
        if cond == "row":
            return self._context_path is not None
        return True

    def update_menu(self, menu):
        for index, cond in self._menu_conds.get(str(menu), ()):
            menu.entryconfigure(index, state="normal" if self._menu_condition(cond) else "disabled")

    def _build_context_menu(self):
        self.context_menu = tk.Menu(self, tearoff=0)
        self._fill_menu(self.context_menu, self.context_menu_items())
        self.tree.bind("<Button-3>", self._on_context)
        if IS_MAC:  # macOS에서는 오른쪽 버튼이 Button-2로 오는 경우가 있고, Control+클릭도 우클릭으로 씀
            self.tree.bind("<Button-2>", self._on_context)
            self.tree.bind("<Control-Button-1>", self._on_context)

    def _on_context(self, event):
        tree = self.tree
        if tree._dragging or tree.identify_region(event.x, event.y) not in ("tree", "cell", "nothing"):
            return None  # 끄는 중이거나 열 머리글에서는 메뉴를 띄우지 않음
        tree.focus_set()
        item = tree.identify_row(event.y)
        if item and not tree.bbox(item):
            item = ""  # 목록 아래 바깥 좌표에서는 보이지 않는 행이 나올 수 있음
        self._context_path = self.pages[item][0] if item else None
        if item:
            tree.select_for_context(item)
        index = self.menu_entry(self.context_menu, "이 파일의 쪽 모두 선택")
        label = "이 파일의 쪽 모두 선택"
        if self._context_path:
            label += f" ({os.path.basename(self._context_path)})"
        self.context_menu.entryconfigure(index, label=label)
        self.update_menu(self.context_menu)
        self.popup_menu(self.context_menu, event.x_root, event.y_root)
        return "break"

    def popup_menu(self, menu, x, y):
        """메뉴를 화면 좌표 (x, y)에 띄웁니다. 테스트에서는 이 메서드를 바꿔치기합니다."""
        try:
            menu.tk_popup(x, y)
        finally:
            menu.grab_release()

    def select_file_pages(self, path=None):
        """path(기본값은 우클릭한 행의 파일)에서 불러온 쪽을 목록에서 모두 선택하고, 선택한 쪽 수를 반환합니다."""
        path = path or self._context_path
        if path is None:
            return 0
        rows = [iid for iid in self.tree.get_children() if self.pages[iid][0] == path]
        self.tree.selection_set(rows)
        return len(rows)

    def quit_app(self):
        self.winfo_toplevel().destroy()

    def shortcut_lines(self):
        return [
            f"{MOD}+O\tPDF 불러오기",
            f"{MOD}+S\t새 PDF로 저장",
            f"{MOD}+Z\t실행 취소 (최대 {UNDO_LIMIT}단계)",
            f"{MOD}+Y, {MOD}+Shift+Z\t다시 실행",
            f"{MOD}+A\t전체 선택 (쪽 목록에서)",
            "Delete\t선택 삭제 (쪽 목록에서)",
            "",
            "마우스로 행을 끌기\t순서 바꾸기 (선택한 쪽들이 놓은 위치에 모임)",
            f"{MOD}+클릭\t쪽을 하나씩 선택에 더하거나 빼기",
            "Shift+클릭\t범위 선택",
            "우클릭\t쪽 메뉴 (이 파일의 쪽 모두 선택, 이동, 삭제)",
        ]

    def show_shortcuts(self):
        messagebox.showinfo("단축키와 마우스 사용법", "\n".join(self.shortcut_lines()), parent=self)

    def about_text(self):
        lines = [f"{self.APP_NAME} ({self.EDITION})", ""]
        for name in self.LIBRARIES:
            try:
                version = importlib.metadata.version(name)
            except importlib.metadata.PackageNotFoundError:
                version = "버전 확인 불가"
            lines.append(f"{name} {version}")
        lines.append(f"Python {platform.python_version()}, Tk {self.tk.call('info', 'patchlevel')}")
        return "\n".join(lines)

    def show_about(self):
        messagebox.showinfo("프로그램 정보", self.about_text(), parent=self)

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
        same = lambda p: os.path.normcase(os.path.abspath(p))
        if same(output) in {same(path) for path, _ in pages}:
            messagebox.showerror("오류", "저장 경로가 불러온 원본 파일과 같습니다. 다른 이름으로 저장해 주세요.")
            return
        file_bookmarks = self.file_bookmark_var.get()
        keep_outlines = self.keep_outline_var.get()
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
            lambda report: save_pages(pages, output, report, self.readers, file_bookmarks, keep_outlines),
            on_progress=lambda v: self.progress.configure(value=v),
            on_done=on_done,
            on_error=on_error,
        )
