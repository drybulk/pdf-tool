"""실행 취소/다시 실행 테스트: 드래그, 버튼 이동, 삭제, 비우기, 불러오기, 단축키, 단계 제한.
실행: xvfb-run -a python tests/test_undo.py
"""
import os
import sys
import tempfile
import time

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(HERE))  # 저장소 루트 (pdf_tool.py)
sys.path.insert(0, HERE)                   # tests/helpers.py

from helpers import make_test_pdfs

TMP = tempfile.mkdtemp(prefix="pdf_tool_test_")
BIG, SMALL = make_test_pdfs(TMP)
import tkinter as tk
from tkinter import filedialog, messagebox
import pdf_tool as T

messagebox.showinfo = messagebox.showwarning = messagebox.showerror = lambda *a, **k: None
root = tk.Tk(); root.geometry("780x560")
nb = T.ttk.Notebook(root); nb.pack(fill="both", expand=True)
# 다른 탭이 보일 때 단축키를 무시하는지 검사하려고 빈 탭을 하나 둠 (10번)
other = T.ttk.Frame(nb); page = T.PageTab(nb)
nb.add(other, text="다른 탭"); nb.add(page, text="추출"); nb.select(page)
root.update(); root.focus_force(); root.update()
tree = page.tree

def order(): return [tree.set(i, "page") for i in tree.get_children()]
def posok(): return [str(tree.set(i, "pos")) for i in tree.get_children()] == [str(n) for n in range(1, len(tree.get_children())+1)]
def pump(sec=0.0):
    end = time.time()+sec; root.update()
    while time.time() < end: root.update(); time.sleep(0.01)
def press(item, state=0):
    x, y, w, h = tree.bbox(item); tree.event_generate("<ButtonPress-1>", x=x+10, y=y+h//2, state=state); root.update()
def motion(y): tree.event_generate("<B1-Motion>", x=20, y=y, state=0x100); root.update()
def release(y): tree.event_generate("<ButtonRelease-1>", x=20, y=y); root.update()
def rowy(i):
    x, y, w, h = tree.bbox(tree.get_children()[i]); return y+h//2
def load(rng, path=BIG):
    filedialog.askopenfilenames = lambda **k: (path,)
    page.range_var.set(rng); page.load_pdfs(); pump()
def key(seq):
    tree.focus_force(); root.update()
    tree.event_generate(seq); root.update()

# 0. 빈 상태에서 실행 취소/다시 실행은 오류 없이 무시
page.undo(); page.redo(); assert order() == []

# 1. 불러오기 -> 실행 취소 -> 다시 실행 (빈 목록으로 복원되는 경우 포함)
load("1-6"); assert order() == list("123456"), order()
page.undo(); assert order() == [] and posok() and page.status.get() == "총 0쪽"
page.redo(); assert order() == list("123456") and posok()
print("1. 불러오기 undo/redo OK")

# 2. 드래그 이동 -> undo
kids = tree.get_children()
press(kids[0]); motion(rowy(2)); motion(rowy(4)); release(rowy(4)); pump(0.05)
assert order() == ["2","3","4","5","1","6"], order()
page.undo(); assert order() == list("123456") and posok(), order()
page.redo(); assert order() == ["2","3","4","5","1","6"] and posok()
page.undo()
print("2. 드래그 undo/redo OK")

# 3. 클릭만 한 경우와 원위치로 되돌린 드래그는 기록되지 않음
n_before = len(page._undo)
kids = tree.get_children()
press(kids[2]); release(rowy(2)); pump(0.05)
press(tree.get_children()[1]); motion(rowy(3)); motion(rowy(1)); release(rowy(1)); pump(0.05)
assert order() == list("123456") and len(page._undo) == n_before, (order(), len(page._undo), n_before)
print("3. 무변화 작업은 기록 안 됨 OK")

# 4. 삭제 -> undo (원래 위치로 복원)
tree.selection_set(tree.get_children()[1], tree.get_children()[4]); page.delete_selected(); pump()
assert order() == ["1","3","4","6"], order()
page.undo(); assert order() == list("123456") and posok() and len(page.pages) == 6
print("4. 삭제 undo OK")

# 5. 버튼 이동(위로/맨 아래로/위치 지정) -> undo
tree.selection_set(tree.get_children()[3]); page.shift(-1); assert order() == ["1","2","4","3","5","6"]
page.undo(); assert order() == list("123456")
page.move_to(1); assert order() == list("123456")   # 이미 맨 위: 무변화
n = len(page._undo)
tree.selection_set(tree.get_children()[0]); page.move_to(10**9); assert order()[-1] == "1"
assert len(page._undo) == n + 1
page.undo(); assert order() == list("123456") and posok()
# 맨 위 행을 위로 이동 시도(불가): 기록되지 않아야 함
tree.selection_set(tree.get_children()[0]); n = len(page._undo); page.shift(-1); assert len(page._undo) == n
print("5. 버튼 이동 undo, 무변화 미기록 OK")

# 6. 목록 비우기 -> undo
page.clear_all(); assert order() == []
page.undo(); assert order() == list("123456")
page.clear_all(); n = len(page._undo); page.clear_all(); assert len(page._undo) == n  # 빈 목록에서 재실행 시 미기록
page.undo(); assert order() == list("123456")
print("6. 비우기 undo OK")

# 7. 새 작업을 하면 다시 실행 기록이 지워짐
tree.selection_set(tree.get_children()[0]); page.shift(1); page.undo()
assert page._redo                       # 되돌린 작업이 다시 실행 목록에 있음
tree.selection_set(tree.get_children()[0]); page.shift(1)   # 새 작업
assert page._redo == []                 # 다시 실행 목록이 지워짐
page.undo()
print("7. 새 작업 시 redo 초기화 OK")

# 8. 단계 제한
page.clear_all(); load("1-3")
for _ in range(T.UNDO_LIMIT + 20):
    tree.selection_set(tree.get_children()[0]); page.shift(1)
    tree.selection_set(tree.get_children()[1]); page.shift(-1)
assert len(page._undo) == T.UNDO_LIMIT, len(page._undo)
print("8. 단계 제한 OK (%d)" % len(page._undo))

# 9. 키보드 단축키 (버튼에 포커스가 있어도 동작해야 함)
page.clear_all(); load("1-5")
tree.selection_set(tree.get_children()[0]); page.shift(1); assert order() == ["2","1","3","4","5"]
key("<Control-z>"); assert order() == list("12345"), order()
key("<Control-y>"); assert order() == ["2","1","3","4","5"], order()
key("<Control-z>"); assert order() == list("12345")
tree.focus_force(); root.update()
tree.event_generate("<Control-Z>", state=0x1|0x4); root.update()   # Ctrl+Shift+Z
assert order() == ["2","1","3","4","5"], order()
# 다른 위젯(버튼)에 포커스가 있을 때
page.save_btn.focus_force(); root.update()
page.save_btn.event_generate("<Control-z>"); root.update()
assert order() == list("12345"), order()
print("9. 단축키 OK (Ctrl+Z, Ctrl+Y, Ctrl+Shift+Z, 버튼 포커스)")

# 10. 다른 탭이 보일 때는 동작하지 않음
tree.selection_set(tree.get_children()[0]); page.shift(1)
nb.select(other); root.update()
other.focus_force(); root.update()
other.event_generate("<Control-z>"); root.update()
assert order() == ["2","1","3","4","5"], order()
nb.select(page); root.update()
print("10. 다른 탭에서는 무시 OK")

# 11. 스크롤 위치 유지 (800쪽)
page.clear_all(); load("")
assert len(order()) == 800
tree.selection_set(tree.get_children()[0]); page.shift(1)
tree.yview_moveto(0.5); pump(0.1)
top_before = tree.yview()[0]
page.undo(); pump(0.1)
print("   undo 전 스크롤: %.3f, 후: %.3f" % (top_before, tree.yview()[0]))
assert abs(tree.yview()[0] - top_before) < 0.01
print("11. 스크롤 위치 유지 OK")

# 12. 저장 결과가 undo 이후 화면 순서와 일치
page.clear_all(); load("10-13")
tree.selection_set(tree.get_children()[3]); page.move_to(1)     # 13,10,11,12
tree.selection_set(tree.get_children()[0]); page.delete_selected()  # 10,11,12
page.undo()                                                     # 13,10,11,12
filedialog.asksaveasfilename = lambda **k: os.path.join(TMP, "result_undo.pdf")
done = []
messagebox.showinfo = lambda *a, **k: done.append(a)
page.save(); t0 = time.time()
while not done and time.time()-t0 < 10: pump(0.05)
from pypdf import PdfReader
texts = [p.extract_text().strip() for p in PdfReader(os.path.join(TMP, "result_undo.pdf")).pages]
assert texts == ["P13","P10","P11","P12"], texts
print("12. undo 후 저장 결과 OK:", texts)
print("ALL UNDO TESTS PASSED")
root.destroy()
