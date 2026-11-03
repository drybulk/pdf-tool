"""메뉴 막대와 우클릭 메뉴 테스트: 메뉴 구성, 항목 사용 가능 여부, 우클릭 선택 규칙, "이 파일의 쪽 모두 선택",
메뉴로 이동/삭제/실행 취소/저장, Ctrl+O/Ctrl+S 단축키, 도움말, 종료, 메뉴 막대를 붙인 창의 화면 배치.
렌더링판 항목(이미지로 저장)은 pypdfium2가 설치되어 있을 때만 검사합니다.
실행: xvfb-run -a python tests/test_menu.py [창 크기, 예: 1100x600]
"""
import importlib.util
import os
import sys
import tempfile
import time

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(HERE))  # 저장소 루트
sys.path.insert(0, HERE)                   # tests/helpers.py

from helpers import make_test_pdfs

TMP = tempfile.mkdtemp(prefix="pdf_tool_test_")
BIG, SMALL = make_test_pdfs(TMP)
import tkinter as tk
from tkinter import filedialog, messagebox
import pdf_common
import pdf_tool as T
from pypdf import PdfReader

SIZE = sys.argv[1] if len(sys.argv) > 1 else "780x560"
HAS_RENDER = importlib.util.find_spec("pypdfium2") is not None

msgs = []
messagebox.showinfo = lambda *a, **k: msgs.append(("info", a))
messagebox.showwarning = lambda *a, **k: msgs.append(("warn", a))
messagebox.showerror = lambda *a, **k: msgs.append(("error", a))

root = tk.Tk()
page = T.build_window(root)
root.geometry(SIZE)
root.update()
tree = page.tree
popups = []
page.popup_menu = lambda menu, x, y: popups.append(menu)

def pump(sec=0.0):
    end = time.time() + sec
    root.update()
    while time.time() < end:
        root.update(); time.sleep(0.01)
def labels(menu):
    out = []
    for i in range(menu.index("end") + 1):
        out.append("-" if menu.type(i) == "separator" else menu.entrycget(i, "label"))
    return out
def state(menu, label):
    return str(menu.entrycget(page.menu_entry(menu, label), "state"))
def invoke(menu, label):
    page.update_menu(menu)
    assert state(menu, label) == "normal", (label, state(menu, label))
    menu.invoke(page.menu_entry(menu, label))
    pump()
def order():
    return [f"{os.path.basename(page.pages[i][0])[0]}{page.pages[i][1] + 1}" for i in tree.get_children()]
def picked():
    return [order()[tree.index(i)] for i in tree.selection()]
def rowy(iid):
    # 행 전체가 보일 때까지 스크롤한 뒤 행 가운데 좌표를 구함 (일부만 보이는 행은 see()가 스크롤하지 않음)
    tree.see(iid); root.update()
    for _ in range(len(tree.get_children())):
        box = tree.bbox(iid)
        if box and box[1] + box[3] <= tree.winfo_height():
            break
        tree.yview_scroll(1, "units"); root.update()
    x, y, w, h = tree.bbox(iid)
    return y + h // 2
def right_click(y, x=60):
    popups.clear()
    tree.event_generate("<Button-3>", x=x, y=y, rootx=tree.winfo_rootx() + x, rooty=tree.winfo_rooty() + y)
    pump()
FILE, EDIT, HELP = page.menus["파일"], page.menus["편집"], page.menus["도움말"]
CTX = page.context_menu
SELECT_FILE = "이 파일의 쪽 모두 선택"

# ---------- 1. 메뉴 구성 ----------
menubar = page.menubar
assert str(root.cget("menu")) == str(menubar)
assert [menubar.entrycget(i, "label") for i in range(menubar.index("end") + 1)] == ["파일", "편집", "도움말"]
assert labels(FILE) == ["PDF/이미지 불러오기...", "새 PDF로 저장...", "-", "종료"], labels(FILE)
assert labels(EDIT) == [
    "실행 취소", "다시 실행", "-", "전체 선택", "선택 삭제", "-",
    "위로", "아래로", "맨 위로", "맨 아래로", "위치 지정 이동...", "-", "목록 비우기",
], labels(EDIT)
assert labels(HELP) == ["단축키와 마우스 사용법", "프로그램 정보"]
assert labels(CTX) == [SELECT_FILE, "-", "위로", "아래로", "맨 위로", "맨 아래로", "위치 지정 이동...", "-", "선택 삭제"]
mod = "Cmd" if T.IS_MAC else "Ctrl"
assert FILE.entrycget(0, "accelerator") == f"{mod}+O" and FILE.entrycget(1, "accelerator") == f"{mod}+S"
assert EDIT.entrycget(0, "accelerator") == f"{mod}+Z" and EDIT.entrycget(1, "accelerator") == f"{mod}+Y"
assert str(FILE.cget("postcommand")) and str(EDIT.cget("postcommand"))  # 메뉴를 열 때 상태를 갱신함
print("1. 메뉴 구성 OK")

# ---------- 2. 빈 목록일 때 항목 상태 ----------
for m in (FILE, EDIT, HELP):
    page.update_menu(m)
assert state(FILE, "PDF/이미지 불러오기...") == "normal" and state(FILE, "새 PDF로 저장...") == "disabled"
assert state(FILE, "종료") == "normal"
for label in ("실행 취소", "다시 실행", "전체 선택", "선택 삭제", "위로", "위치 지정 이동...", "목록 비우기"):
    assert state(EDIT, label) == "disabled", label
assert state(HELP, "프로그램 정보") == "normal"
right_click(30)                               # 빈 목록에서 우클릭해도 오류 없이 메뉴만 뜸
assert popups == [CTX] and page._context_path is None and state(CTX, SELECT_FILE) == "disabled"
print("2. 빈 목록일 때 비활성화 OK")

# ---------- 3. 메뉴로 불러오기: big 1-3, small 전체, big 4-5 ----------
for rng, path in (("1-3", BIG), ("", SMALL), ("4-5", BIG)):
    page.range_var.set(rng)
    filedialog.askopenfilenames = lambda p=path, **k: (p,)
    invoke(FILE, "PDF/이미지 불러오기...")
assert order() == ["b1", "b2", "b3", "s1", "s2", "s3", "s4", "s5", "b4", "b5"], order()
page.update_menu(EDIT)
assert state(EDIT, "실행 취소") == "normal" and state(EDIT, "선택 삭제") == "disabled"  # 아직 선택 없음
assert state(EDIT, "전체 선택") == "normal"
print("3. 메뉴로 불러오기, 항목 상태 OK")

# ---------- 4. 우클릭 선택 규칙과 "이 파일의 쪽 모두 선택" ----------
rows = tree.get_children()
right_click(rowy(rows[1]))                    # 선택되지 않은 b2 우클릭 -> b2만 선택
assert popups == [CTX], popups
assert picked() == ["b2"] and tree.focus() == rows[1]
assert CTX.entrycget(page.menu_entry(CTX, SELECT_FILE), "label") == f"{SELECT_FILE} (big.pdf)"
assert state(CTX, SELECT_FILE) == "normal" and state(CTX, "선택 삭제") == "normal"
invoke(CTX, SELECT_FILE)
assert sorted(picked()) == ["b1", "b2", "b3", "b4", "b5"], picked()  # 떨어져 있는 쪽도 모두 선택
right_click(rowy(rows[9]))                    # 이미 선택된 b5 우클릭 -> 선택 유지
assert sorted(picked()) == ["b1", "b2", "b3", "b4", "b5"] and tree.focus() == rows[9]
invoke(CTX, "맨 아래로")                      # 파일 단위로 순서 바꾸기: big을 small 뒤로 모음
assert order() == ["s1", "s2", "s3", "s4", "s5", "b1", "b2", "b3", "b4", "b5"], order()
right_click(rowy(tree.get_children()[2]))     # small의 s3 우클릭 -> s3만 선택, 이름 표시가 small.pdf로 바뀜
assert picked() == ["s3"]
assert CTX.entrycget(page.menu_entry(CTX, SELECT_FILE), "label") == f"{SELECT_FILE} (small.pdf)"
invoke(CTX, SELECT_FILE)
assert sorted(picked()) == ["s1", "s2", "s3", "s4", "s5"]
invoke(EDIT, "맨 아래로")
assert order() == ["b1", "b2", "b3", "b4", "b5", "s1", "s2", "s3", "s4", "s5"], order()
print("4. 우클릭 선택 규칙, 이 파일의 쪽 모두 선택, 파일 단위 이동 OK")

# ---------- 5. 실행 취소/다시 실행, 위로/아래로, 삭제 ----------
invoke(EDIT, "실행 취소")
assert order() == ["s1", "s2", "s3", "s4", "s5", "b1", "b2", "b3", "b4", "b5"], order()
page.update_menu(EDIT)
assert state(EDIT, "다시 실행") == "normal"
invoke(EDIT, "다시 실행")
assert order() == ["b1", "b2", "b3", "b4", "b5", "s1", "s2", "s3", "s4", "s5"], order()
page.update_menu(EDIT)
assert state(EDIT, "다시 실행") == "disabled"
right_click(rowy(tree.get_children()[5]))     # s1
invoke(CTX, "위로")
assert order()[4:6] == ["s1", "b5"], order()
invoke(EDIT, "아래로")
assert order()[4:6] == ["b5", "s1"], order()
invoke(EDIT, "전체 선택")
assert len(tree.selection()) == 10
right_click(rowy(tree.get_children()[0]))     # 선택된 b1 우클릭 -> 전체 선택 유지
assert len(tree.selection()) == 10
tree.selection_set(tree.get_children()[0])
invoke(CTX, "선택 삭제")
assert order()[0] == "b2" and len(order()) == 9 and page.status.get() == "총 9쪽"
invoke(EDIT, "실행 취소")
assert order()[0] == "b1" and len(order()) == 10 and page.status.get() == "총 10쪽"
print("5. 메뉴로 실행 취소, 다시 실행, 위로, 아래로, 전체 선택, 삭제 OK")

# ---------- 6. 빈 곳 우클릭, 끄는 중 우클릭 ----------
before = tree.selection()
last = tree.get_children()[-1]
rowy(last)
box = tree.bbox(last)
blank_y = box[1] + box[3] + 3
if blank_y < tree.winfo_height() - 2 and not tree.identify_row(blank_y):
    right_click(blank_y)
    assert popups == [CTX] and page._context_path is None
    assert state(CTX, SELECT_FILE) == "disabled" and CTX.entrycget(0, "label") == SELECT_FILE
    assert tree.selection() == before         # 빈 곳을 우클릭해도 선택은 그대로
    print("6a. 빈 곳 우클릭 OK")
else:
    print("6a. 빈 곳 우클릭: 이 창 크기에서는 마지막 행 아래에 빈 곳이 없어 건너뜀")
tree._dragging = True
right_click(rowy(tree.get_children()[1]))
assert popups == []                           # 끄는 중에는 메뉴를 띄우지 않음
tree._dragging = False
print("6b. 끄는 중 우클릭 무시 OK")

# ---------- 7. 단축키 Ctrl+O, Ctrl+S ----------
calls = []
filedialog.askopenfilenames = lambda **k: (calls.append("open"), ())[1]
filedialog.asksaveasfilename = lambda **k: (calls.append("save"), "")[1]
tree.focus_force(); pump()
tree.event_generate("<Control-o>"); pump()
tree.event_generate("<Control-s>"); pump()
assert calls == ["open", "save"], calls
dlg = tk.Toplevel(root); entry = tk.Entry(dlg); entry.pack()
pump(); entry.focus_force(); pump()
entry.event_generate("<Control-s>"); entry.event_generate("<Control-o>"); pump()
assert calls == ["open", "save"], calls       # 다른 창(대화 상자)에서는 처리하지 않음
dlg.destroy(); pump()
print("7. 단축키 Ctrl+O, Ctrl+S, 대화 상자에서는 무시 OK")

# ---------- 8. 메뉴로 저장, 작업 중 항목 비활성화 ----------
out = os.path.join(TMP, "menu_out.pdf")
filedialog.asksaveasfilename = lambda **k: out
invoke(FILE, "새 PDF로 저장...")
assert page.busy
for m in (FILE, EDIT, CTX):
    page.update_menu(m)
assert state(FILE, "PDF/이미지 불러오기...") == "disabled" and state(FILE, "새 PDF로 저장...") == "disabled"
assert state(FILE, "종료") == "normal" and state(EDIT, "실행 취소") == "disabled" and state(CTX, "선택 삭제") == "disabled"
end = time.time() + 20
while page.busy and time.time() < end:
    pump(0.05)
assert not page.busy
texts = [p.extract_text().strip() for p in PdfReader(out).pages]
assert texts == ["P1", "P2", "P3", "P4", "P5", "S1", "S2", "S3", "S4", "S5"], texts
assert msgs[-1][0] == "info"
print("8. 메뉴로 저장, 저장 중 비활성화 OK")

# ---------- 9. 도움말 ----------
msgs.clear()
invoke(HELP, "단축키와 마우스 사용법")
assert msgs[-1][0] == "info" and f"{mod}+O" in msgs[-1][1][1] and "우클릭" in msgs[-1][1][1]
invoke(HELP, "프로그램 정보")
text = msgs[-1][1][1]
assert f"PDF 도구 {pdf_common.APP_VERSION} (경량판)" in text, text
assert "경량판" in text and "pypdf " in text and "Python" in text and "pypdfium2" not in text, text
print("9. 도움말 OK")

# ---------- 10. 메뉴 막대를 붙인 창의 화면 배치 ----------
def check_layout(top, pg, sizes):
    for size in sizes:
        top.geometry(size)
        pump(0.1)
        bottom = top.winfo_rooty() + top.winfo_height()
        for w in (pg.save_btn, pg.progress, pg.tree):
            assert w.winfo_ismapped(), (size, w)
            assert w.winfo_rooty() + w.winfo_height() <= bottom + 1, (size, str(w), w.winfo_rooty(), w.winfo_height(), bottom)
        assert pg.tree.winfo_height() > 40, (size, pg.tree.winfo_height())
        # 화면에 보이는 순서: 쪽 목록 -> 저장 옵션 -> 저장 버튼 -> 진행 막대
        ys = [pg.tree.winfo_rooty() + pg.tree.winfo_height(), pg.keep_outline_check.winfo_rooty(),
              pg.save_btn.winfo_rooty(), pg.progress.winfo_rooty()]
        assert ys == sorted(ys), (size, ys)
check_layout(root, page, ["640x460", "780x560", "1100x600", SIZE])
print("10. 경량판 화면 배치 OK (640x460, 780x560, 1100x600, " + SIZE + ")")

# ---------- 11. 종료 ----------
top = tk.Toplevel(root)
other = T.PageTab(top)
other.make_menubar(top)
other.pack(fill="both", expand=True)
pump()
other.menus["파일"].invoke(other.menu_entry(other.menus["파일"], "종료"))
pump()
assert not top.winfo_exists() and root.winfo_exists()
print("11. 종료 OK")

# ---------- 12. 렌더링판 ----------
if HAS_RENDER:
    import pdf_tool_render as R
    rtop = tk.Toplevel(root)
    rpage = R.build_window(rtop)
    rtop.geometry(SIZE if SIZE != "780x560" else "1200x750")
    rpage.popup_menu = lambda menu, x, y: popups.append(menu)
    pump(0.2)
    rfile = rpage.menus["파일"]
    assert labels(rfile) == ["PDF/이미지 불러오기...", "새 PDF로 저장...", "이미지로 저장...", "-", "종료"], labels(rfile)
    assert labels(rpage.context_menu)[-2:] == ["-", "이미지로 저장..."], labels(rpage.context_menu)
    rpage.update_menu(rfile)
    assert str(rfile.entrycget(rpage.menu_entry(rfile, "이미지로 저장..."), "state")) == "disabled"
    filedialog.askopenfilenames = lambda **k: (SMALL,)
    rpage.range_var.set("")
    rpage.load_pdfs(); pump(0.3)
    rtree = rpage.tree
    iid = rtree.get_children()[3]
    rtree.see(iid); pump()
    x, y, w, h = rtree.bbox(iid)
    popups.clear()
    rtree.event_generate("<Button-3>", x=60, y=y + h // 2, rootx=rtree.winfo_rootx() + 60, rooty=rtree.winfo_rooty() + y + h // 2)
    pump(0.3)
    assert popups == [rpage.context_menu] and rtree.selection() == (iid,)
    assert rpage.preview_target() == iid      # 우클릭한 쪽이 미리보기에 나옴
    asked = []
    rpage.ask_image_options = lambda n_sel, n_all: (asked.append((n_sel, n_all)), None)[1]
    ctx = rpage.context_menu
    rpage.update_menu(ctx)
    ctx.invoke(rpage.menu_entry(ctx, "이미지로 저장..."))
    rpage.update_menu(rfile)
    rfile.invoke(rpage.menu_entry(rfile, "이미지로 저장..."))
    assert asked == [(1, 5), (1, 5)], asked
    msgs.clear()
    rpage.show_about()
    text = msgs[-1][1][1]
    assert "렌더링판" in text and "pypdfium2 " in text and "Pillow" in text, text
    check_layout(rtop, rpage, ["900x560", "1100x600", "1200x750", "1400x750"])
    for w in (rpage.image_btn,):
        assert w.winfo_ismapped()
    print("12. 렌더링판 메뉴(이미지로 저장), 미리보기, 화면 배치 OK (900x560, 1100x600, 1200x750, 1400x750)")
else:
    print("12. 렌더링판: pypdfium2가 없어 건너뜀")

root.destroy()
print("ALL MENU TESTS PASSED")
