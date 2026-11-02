"""렌더링판 테스트: PPM 변환, 썸네일 크기, 지연 로딩과 캐시, 미리보기, 화면 배치, 경량판 기능 유지.
실행: xvfb-run -a python tests/test_render.py   (pypdfium2 필요: pip install -r requirements-render.txt)
"""
import os
import sys
import tempfile
import time

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(HERE))  # 저장소 루트
sys.path.insert(0, HERE)                   # tests/helpers.py

import importlib.util
if importlib.util.find_spec("pypdfium2") is None:
    raise SystemExit("pypdfium2가 설치되어 있지 않습니다: pip install -r requirements-render.txt")

from helpers import make_pdf
from pypdf import PdfReader, PdfWriter
from reportlab.pdfgen import canvas

import pdf_render as PR

TMP = tempfile.mkdtemp(prefix="pdf_tool_test_")

# ---------- 1. PPM 변환: 행 간격(stride)이 너비x3보다 큰 경우 행 단위로 잘라 냄 ----------
data = bytes([1, 2, 3, 4, 5, 6, 99, 99,  7, 8, 9, 10, 11, 12, 99, 99])  # 너비 2, 높이 2, stride 8
assert PR.bitmap_to_ppm(2, 2, 8, data) == b"P6 2 2 255\n" + bytes(range(1, 13))
assert PR.bitmap_to_ppm(2, 1, 6, bytes(range(6))) == b"P6 2 1 255\n" + bytes(range(6))
print("1. PPM 변환 OK")

# ---------- 2. 실제 렌더링: 색 순서(RGB), 썸네일 크기, 회전한 쪽 ----------
colors_pdf = os.path.join(TMP, "colors.pdf")
c = canvas.Canvas(colors_pdf, pagesize=(595, 842))
c.setFillColorRGB(1, 0, 0); c.rect(0, 0, 595, 842, fill=1, stroke=0); c.showPage()       # A4 세로, 빨강
c.setPageSize((842, 595)); c.setFillColorRGB(0, 0, 1); c.rect(0, 0, 842, 595, fill=1, stroke=0); c.showPage()  # 가로, 파랑
c.setPageSize((1190, 1684)); c.setFillColorRGB(0, 1, 0); c.rect(0, 0, 1190, 1684, fill=1, stroke=0); c.showPage()  # A2, 초록
c.save()
w = PdfWriter()
for p in PdfReader(colors_pdf).pages:
    w.add_page(p)
w.pages[0].rotate(90)
rotated_pdf = os.path.join(TMP, "rotated.pdf")
w.write(rotated_pdf)

def center_rgb(ppm):
    header_end = ppm.index(b"\n") + 1
    wd, ht = map(int, ppm[3:header_end].split()[:2])
    off = header_end + ((ht // 2) * wd + wd // 2) * 3
    return tuple(ppm[off:off + 3])

docs = PR.PdfiumDocs()
assert PR.THUMB_BOX == (72, 102), PR.THUMB_BOX
for idx, color in [(0, (255, 0, 0)), (1, (0, 0, 255)), (2, (0, 255, 0))]:
    pw, ph = docs.page_size(colors_pdf, idx)
    tw, th, ppm = docs.render_ppm(colors_pdf, idx, PR.thumb_scale(pw, ph))
    assert center_rgb(ppm) == color, (idx, center_rgb(ppm))
    assert tw <= PR.THUMB_BOX[0] and th <= PR.THUMB_BOX[1], (idx, tw, th)   # 썸네일 칸을 넘지 않음
tw, th, _ = docs.render_ppm(colors_pdf, 0, PR.thumb_scale(*docs.page_size(colors_pdf, 0)))
assert (tw, th) == (72, 102), (tw, th)                                       # A4 세로는 배율 0.12 그대로
assert docs.page_size(rotated_pdf, 0) == (842, 595)                          # 회전이 반영된 크기
tw, th, ppm = docs.render_ppm(rotated_pdf, 0, 0.12)
assert tw > th and center_rgb(ppm) == (255, 0, 0)
try:
    bad = os.path.join(TMP, "bad.pdf")
    with open(bad, "w") as f:
        f.write("not a pdf")
    docs.page_size(bad, 0)
    raise SystemExit("오류가 발생해야 합니다")
except ValueError:
    pass
docs.close_all()
print("2. 렌더링 색, 썸네일 크기, 회전, 손상 파일 OK")

# ---------- 3. LRU 캐시 ----------
evicted = []
cache = PR.LRUCache(3, on_evict=lambda k, v: evicted.append(k))
for k in "abc":
    cache.put(k, k.upper())
cache.get("a")              # a를 최근 사용으로
cache.put("d", "D")         # 가장 오래된 b가 버려짐
assert evicted == ["b"] and "a" in cache and "b" not in cache and len(cache) == 3
print("3. LRU 캐시 OK")

# ---------- 4. 창 크기 맞춤 ----------
import pdf_tool_render as R
assert R.fit_window_size(1200, 750, 1920, 1080) == (1200, 750)
assert R.fit_window_size(1200, 750, 1366, 768) == (1200, 688)
assert R.fit_window_size(1200, 750, 1024, 600) == (984, 520)
print("4. 창 크기 맞춤 OK")

# ---------- GUI 준비 ----------
import tkinter as tk
from tkinter import filedialog, messagebox, ttk

msgs = []
messagebox.showinfo = lambda *a, **k: msgs.append(("info", a))
messagebox.showwarning = lambda *a, **k: msgs.append(("warn", a))
messagebox.showerror = lambda *a, **k: msgs.append(("error", a))

BIG = make_pdf(os.path.join(TMP, "big.pdf"), "P", 800)
root = tk.Tk(); root.geometry("1200x750")
nb = ttk.Notebook(root); nb.pack(fill="both", expand=True)
page = R.RenderPageTab(nb)
nb.add(page, text="추출"); nb.select(page)
tree = page.tree

def pump(sec=0.0):
    end = time.time() + sec
    root.update()
    while time.time() < end:
        root.update(); time.sleep(0.01)
def order():
    return [tree.set(i, "page") for i in tree.get_children()]
def has_image(iid):
    return bool(tree.item(iid, "image"))
def rowy(idx):
    x, y, w, h = tree.bbox(tree.get_children()[idx]); return y + h // 2
def click(idx, state=0):
    y = rowy(idx)
    tree.event_generate("<ButtonPress-1>", x=150, y=y, state=state); root.update()
    tree.event_generate("<ButtonRelease-1>", x=150, y=y); root.update()
def load(rng, path=BIG):
    filedialog.askopenfilenames = lambda **k: (path,)
    page.range_var.set(rng); page.load_pdfs(); pump(0.3)
pump(0.2)

# ---------- 5. 화면 배치: [목록 | 미리보기] [버튼] ----------
list_right = tree.winfo_rootx() + tree.winfo_width()
preview_left = page.preview.winfo_rootx()
preview_right = preview_left + page.preview.winfo_width()
buttons = [w for w in page.paned.master.winfo_children() if w is not page.paned]
assert len(buttons) == 1
assert list_right <= preview_left and preview_right <= buttons[0].winfo_rootx(), (list_right, preview_left, preview_right)
assert str(tree).startswith(str(page.paned))                                   # 목록은 나눔 창 안에 있음
assert "tree" in str(tree.cget("show"))                                        # 썸네일 열(#0) 표시
assert page.save_btn.winfo_ismapped() and page.progress.winfo_ismapped()      # 아래쪽 저장 버튼과 진행 막대가 보임
print("5. 화면 배치 OK")

# ---------- 6. 지연 로딩: 보이는 행(위아래 여유 포함)만 그림 ----------
load("")
assert len(tree.get_children()) == 800
visible = page.visible_rows()
assert 0 < len(visible) <= 20, len(visible)
assert all(has_image(i) for i in visible)
assert page.thumb_renders == len(visible), (page.thumb_renders, len(visible))
far = tree.get_children()[400]
assert not has_image(far)
tree.yview_moveto(0.5); pump(0.3)
assert far in page.visible_rows() and all(has_image(i) for i in page.visible_rows())
print("6. 지연 로딩 OK: 처음 그린 썸네일 %d장" % len(visible))

# ---------- 7. 캐시 상한과 버려진 썸네일 정리 ----------
for f in [i / 60 for i in range(61)]:
    tree.yview_moveto(f); pump(0.02)
pump(0.2)
assert len(page.thumbs) <= R.THUMB_CACHE_SIZE, len(page.thumbs)
assert page.thumb_renders > R.THUMB_CACHE_SIZE, page.thumb_renders            # 실제로 넘쳐서 버린 경우를 확인
images_in_rows = {tree.item(i, "image")[0] for i in tree.get_children() if has_image(i)}
cached_names = {str(img) for img in page.thumbs._items.values()}
assert images_in_rows <= cached_names | {str(page._placeholder)}, images_in_rows - cached_names
assert all(has_image(i) for i in page.visible_rows())
# 다시 위로 가면 버려진 썸네일을 새로 그림
before = page.thumb_renders
tree.yview_moveto(0); pump(0.3)
assert all(has_image(i) for i in page.visible_rows()) and page.thumb_renders > before
print("7. 캐시 상한 OK: 그린 횟수 %d, 보관 %d장" % (page.thumb_renders, len(page.thumbs)))

# ---------- 8. 미리보기: 마지막으로 클릭한 행을 따라감 ----------
def preview_key():
    return page._preview_shown[:2] if page._preview_shown else None
page.clear_all(); load("1-10")
pump(0.3)
click(2); pump(0.3)
assert preview_key() == (BIG, 2) and page.preview_caption.get().endswith("3쪽"), (preview_key(), page.preview_caption.get())
click(4, state=0x4); pump(0.3)                                                # Ctrl+클릭으로 추가 선택
assert preview_key() == (BIG, 4) and len(tree.selection()) == 2
click(2); pump(0.3)                                                            # 이미 선택된 행 클릭: 선택은 그대로, 미리보기만 바뀜
assert preview_key() == (BIG, 2)
# 미리보기 그림이 영역 안에 들어가고 쪽 비율을 유지함
img_w, img_h = page._preview_img.width(), page._preview_img.height()
cw, ch = page.preview.winfo_width(), page.preview.winfo_height()
assert img_w <= cw - 2 * R.PREVIEW_PAD + 1 and img_h <= ch - 2 * R.PREVIEW_PAD + 1, (img_w, img_h, cw, ch)
assert abs(img_w / img_h - 595 / 842) < 0.02, (img_w, img_h)                   # reportlab 기본 쪽 크기(A4)
# 키보드 아래 화살표로 이동하면 따라감
tree.focus_force(); root.update()
tree.event_generate("<Down>"); pump(0.3)
assert preview_key() == (BIG, 3), preview_key()
# 나눔 경계를 옮겨 미리보기 영역 크기가 바뀌면 다시 그림
# 미리보기 그림은 높이에 맞춰질 수도 있으므로(Windows처럼 위젯이 높으면), 영역 폭을 지금 그림 폭보다 좁게 만듦
old_w = page._preview_img.width()
page.paned.sashpos(0, page.paned.winfo_width() - int(old_w * 0.7)); pump(0.5)
assert page._preview_img.width() < old_w, (page._preview_img.width(), old_w)
print("8. 미리보기 OK")

# ---------- 9. 경량판 기능 유지: 드래그, 실행 취소, 저장 ----------
page.clear_all(); load("1-6")
kids = tree.get_children()
x, y, w, h = tree.bbox(kids[0])
tree.event_generate("<ButtonPress-1>", x=150, y=y + h // 2); root.update()
tree.event_generate("<B1-Motion>", x=150, y=rowy(2), state=0x100); root.update()
tree.event_generate("<B1-Motion>", x=150, y=rowy(3), state=0x100); root.update()
tree.event_generate("<ButtonRelease-1>", x=150, y=rowy(3)); pump(0.3)
assert order() == ["2", "3", "4", "1", "5", "6"], order()
assert all(has_image(i) for i in tree.get_children())                         # 옮긴 행도 썸네일 유지
page.undo(); pump(0.3)
assert order() == list("123456") and all(has_image(i) for i in tree.get_children())  # 복원한 행에도 다시 붙음
filedialog.asksaveasfilename = lambda **k: os.path.join(TMP, "render_out.pdf")
msgs.clear(); page.save()
t0 = time.time()
while not msgs and time.time() - t0 < 10:
    pump(0.05)
texts = [p.extract_text().strip() for p in PdfReader(os.path.join(TMP, "render_out.pdf")).pages]
assert texts == ["P1", "P2", "P3", "P4", "P5", "P6"], texts
print("9. 드래그, 실행 취소, 저장 OK")

# ---------- 10. 그릴 수 없는 쪽은 회색 칸으로 표시하고 다시 시도하지 않음 ----------
OTHER = make_pdf(os.path.join(TMP, "other.pdf"), "Q", 3)
real_render = page.docs.render_ppm
calls = []
def flaky_render(path, index, scale):
    calls.append(index)
    if path == OTHER and index == 1:
        raise ValueError("시험용 렌더링 실패")
    return real_render(path, index, scale)
page.docs.render_ppm = flaky_render
page.clear_all(); load("", OTHER)
kids = tree.get_children()
assert tree.item(kids[1], "image")[0] == str(page._placeholder)
assert tree.item(kids[0], "image")[0] != str(page._placeholder) and has_image(kids[2])
calls.clear(); page.update_status(); pump(0.2)
assert 1 not in calls                                                          # 실패한 쪽은 다시 그리지 않음
click(1); pump(0.3)
assert page._preview_shown is None and page.preview.find_all()                # 미리보기에는 안내 문구를 표시
page.docs.render_ppm = real_render
print("10. 실패한 쪽 표시 OK")

print("ALL RENDER TESTS PASSED")
root.destroy()
