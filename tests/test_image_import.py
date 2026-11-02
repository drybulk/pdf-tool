"""이미지 파일 불러오기 테스트: 이미지를 PDF 쪽으로 바꾸기(JPG 그대로 넣기, 방향 정보, 투명, 16비트, 여러 쪽 TIFF,
움직이는 GIF, CMYK, 손상 파일, Pillow가 없을 때), PDF와 이미지를 섞어 불러오기, 순서 바꾸기, 실행 취소, 저장,
파일 이름 북마크, 화면 배치. pypdfium2가 있으면 렌더링판의 썸네일, 미리보기, 이미지로 저장도 검사합니다.
실행: xvfb-run -a python tests/test_image_import.py   (Pillow 필요)
"""
import importlib.util
import io
import os
import sys
import tempfile
import time

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(HERE))  # 저장소 루트
sys.path.insert(0, HERE)                   # tests/helpers.py

if importlib.util.find_spec("PIL") is None:
    raise SystemExit("Pillow가 설치되어 있지 않습니다: pip install pillow")

from helpers import make_pdf
from PIL import Image
from pypdf import PdfReader

import pdf_common as C

TMP = tempfile.mkdtemp(prefix="pdf_tool_test_")
HAS_RENDER = importlib.util.find_spec("pypdfium2") is not None
A4W = C.IMAGE_PAGE_WIDTH


def tmp(name):
    return os.path.join(TMP, name)


def two_color(size=(400, 300), left=(255, 0, 0), right=(0, 0, 255)):
    """왼쪽 절반과 오른쪽 절반의 색이 다른 RGB 이미지"""
    im = Image.new("RGB", size, right)
    im.paste(left, (0, 0, size[0] // 2, size[1]))
    return im


def page_image(page):
    """쪽에 들어 있는 이미지 하나를 Pillow 이미지로 꺼냄 (pypdf가 Pillow로 디코딩)"""
    images = page.images
    assert len(images) == 1, len(images)
    return images[0].image


def xobject(page):
    xobjs = page["/Resources"]["/XObject"]
    return xobjs[list(xobjs.keys())[0]].get_object()


def close(a, b, tol=0.01):
    return abs(float(a) - float(b)) <= tol


# ---------- 1. JPG는 다시 압축하지 않고 그대로 넣음, 쪽 너비는 A4 너비 ----------
JPG = tmp("photo.jpg")
two_color().save(JPG, quality=90)
reader = PdfReader(io.BytesIO(C.image_to_pdf(JPG)))
assert len(reader.pages) == 1
p = reader.pages[0]
assert close(p.mediabox.width, A4W) and close(p.mediabox.height, A4W * 300 / 400), p.mediabox
assert p.rotation == 0
x = xobject(p)
assert x["/Filter"] == "/DCTDecode" and x["/ColorSpace"] == "/DeviceRGB"
with open(JPG, "rb") as f:
    assert x._data == f.read()                             # 파일 내용 그대로 (화질 변화 없음)
assert (x["/Width"], x["/Height"]) == (400, 300)
gray_jpg = tmp("gray.jpg")
Image.new("L", (100, 200), 128).save(gray_jpg)
x = xobject(PdfReader(io.BytesIO(C.image_to_pdf(gray_jpg))).pages[0])
assert x["/Filter"] == "/DCTDecode" and x["/ColorSpace"] == "/DeviceGray"
print("1. JPG 그대로 넣기, A4 너비 OK")

# ---------- 2. Exif 방향 정보: 회전은 쪽 회전으로, 거울상은 그림을 다시 만듦 ----------
def with_orientation(name, value):
    exif = Image.Exif(); exif[0x0112] = value
    path = tmp(name)
    two_color().save(path, quality=95, exif=exif)
    return PdfReader(io.BytesIO(C.image_to_pdf(path))).pages[0]

p = with_orientation("rot6.jpg", 6)                        # 휴대폰을 세워서 찍은 사진
assert p.rotation == 90 and xobject(p)["/Filter"] == "/DCTDecode"
# 화면에 보이는 가로(회전 전 높이)가 A4 너비이고, 세로로 긴 쪽
assert close(p.mediabox.height, A4W) and close(p.mediabox.width, A4W * 400 / 300), p.mediabox
p = with_orientation("rot3.jpg", 3)
assert p.rotation == 180 and close(p.mediabox.width, A4W)
p = with_orientation("mirror.jpg", 2)                      # 좌우 거울상: 화소를 뒤집어 무손실로 넣음
assert p.rotation == 0 and xobject(p)["/Filter"] == "/FlateDecode"
im = page_image(p)
assert im.size == (400, 300)
assert im.getpixel((50, 150))[2] > 200 and im.getpixel((350, 150))[0] > 200, (im.getpixel((50, 150)), im.getpixel((350, 150)))
print("2. 방향 정보(회전, 거울상) OK")

# ---------- 3. PNG 등은 화소를 그대로 무손실 압축, 투명한 부분은 흰색 ----------
png = tmp("note.png")
two_color((300, 600), (10, 200, 30), (250, 250, 0)).save(png)
p = PdfReader(io.BytesIO(C.image_to_pdf(png))).pages[0]
assert close(p.mediabox.width, A4W) and close(p.mediabox.height, A4W * 2)
assert xobject(p)["/Filter"] == "/FlateDecode"
im = page_image(p)
assert im.getpixel((10, 10)) == (10, 200, 30) and im.getpixel((290, 590)) == (250, 250, 0)   # 무손실

rgba = Image.new("RGBA", (100, 100), (0, 0, 255, 0))       # 완전히 투명
rgba.paste((255, 0, 0, 255), (0, 0, 50, 100))              # 왼쪽 절반만 불투명한 빨강
rgba.save(tmp("alpha.png"))
im = page_image(PdfReader(io.BytesIO(C.image_to_pdf(tmp("alpha.png")))).pages[0])
assert im.getpixel((10, 50)) == (255, 0, 0) and im.getpixel((90, 50)) == (255, 255, 255), (im.getpixel((10, 50)), im.getpixel((90, 50)))

pal = Image.new("P", (40, 40), 0)
pal.putpalette([0, 0, 0, 0, 200, 0] + [0] * 762)
pal.paste(1, (0, 0, 20, 40))
pal.save(tmp("pal.png"), transparency=0)                   # 0번 색이 투명
im = page_image(PdfReader(io.BytesIO(C.image_to_pdf(tmp("pal.png")))).pages[0])
assert im.getpixel((5, 5)) == (0, 200, 0) and im.getpixel((35, 5)) == (255, 255, 255), (im.getpixel((5, 5)), im.getpixel((35, 5)))

g16 = Image.new("I;16", (60, 40), 40000)                   # 16비트 회색조: 255를 넘는 값이 잘리지 않아야 함
g16.save(tmp("g16.png"))
x = xobject(PdfReader(io.BytesIO(C.image_to_pdf(tmp("g16.png")))).pages[0])
assert x["/ColorSpace"] == "/DeviceGray"
assert abs(page_image(PdfReader(io.BytesIO(C.image_to_pdf(tmp("g16.png")))).pages[0]).getpixel((5, 5)) - 40000 // 256) <= 1

Image.new("CMYK", (50, 50), (0, 255, 255, 0)).save(tmp("cmyk.jpg"))   # CMYK JPG는 RGB로 바꿔서 넣음
x = xobject(PdfReader(io.BytesIO(C.image_to_pdf(tmp("cmyk.jpg")))).pages[0])
assert x["/ColorSpace"] == "/DeviceRGB" and x["/Filter"] == "/FlateDecode"
two_color((80, 60)).save(tmp("pic.bmp"))
two_color((80, 60)).save(tmp("pic.webp"), lossless=True)
for name in ("pic.bmp", "pic.webp"):
    im = page_image(PdfReader(io.BytesIO(C.image_to_pdf(tmp(name)))).pages[0])
    assert im.getpixel((5, 5)) == (255, 0, 0) and im.getpixel((75, 5)) == (0, 0, 255), name
print("3. PNG 무손실, 투명, 팔레트, 16비트, CMYK, BMP, WebP OK")

# ---------- 4. 여러 쪽 TIFF는 쪽마다 1쪽, 움직이는 GIF는 첫 장면만 ----------
frames = [Image.new("L", (80, 100), v) for v in (0, 128, 255)]
TIF = tmp("scan.tif")
frames[0].save(TIF, save_all=True, append_images=frames[1:])
reader = PdfReader(io.BytesIO(C.image_to_pdf(TIF)))
assert len(reader.pages) == 3
assert [page_image(pg).getpixel((5, 5)) for pg in reader.pages] == [0, 128, 255]
gif = [Image.new("RGB", (20, 20), c) for c in ((255, 0, 0), (0, 255, 0))]
gif[0].save(tmp("anim.gif"), save_all=True, append_images=gif[1:], duration=100)
reader = PdfReader(io.BytesIO(C.image_to_pdf(tmp("anim.gif"))))
assert len(reader.pages) == 1
print("4. 여러 쪽 TIFF, 움직이는 GIF OK")

# ---------- 5. 손상 파일, Pillow가 없을 때, 확장자 판단 ----------
BROKEN = tmp("broken.png")
with open(BROKEN, "wb") as f:
    f.write(b"not an image")
try:
    C.image_to_pdf(BROKEN); raise SystemExit("오류가 발생해야 합니다")
except ValueError as e:
    assert "이미지를 읽을 수 없습니다" in str(e)
saved_image, C.Image = C.Image, None
try:
    C.image_to_pdf(JPG); raise SystemExit("오류가 발생해야 합니다")
except ValueError as e:
    assert "Pillow" in str(e)
finally:
    C.Image = saved_image
assert C.is_image_file("A.JPG") and C.is_image_file("b.Tiff") and not C.is_image_file("c.pdf")
assert len(C.open_source(TIF).pages) == 3
print("5. 손상 파일, Pillow 없음, 확장자 판단 OK")

# ---------- GUI 준비 (경량판) ----------
import tkinter as tk
from tkinter import filedialog, messagebox

import pdf_tool as T

msgs = []
messagebox.showinfo = lambda *a, **k: msgs.append(("info", a))
messagebox.showwarning = lambda *a, **k: msgs.append(("warn", a))
messagebox.showerror = lambda *a, **k: msgs.append(("error", a))

SMALL = make_pdf(tmp("small.pdf"), "S", 5)
root = tk.Tk()
page = T.build_window(root)
root.geometry("780x560")
root.update()
tree = page.tree


def pump(sec=0.0):
    end = time.time() + sec
    root.update()
    while time.time() < end:
        root.update(); time.sleep(0.01)


def order(pg=None):
    pg = pg or page
    return [f"{os.path.splitext(os.path.basename(pg.pages[i][0]))[0]}{pg.pages[i][1] + 1}" for i in pg.tree.get_children()]


asked = {}
def fake_open(**k):
    asked.update(k)
    return (SMALL, JPG, BROKEN, TIF, png)
filedialog.askopenfilenames = fake_open

# ---------- 6. PDF와 이미지를 섞어 불러오기: 쪽 범위는 PDF에만 적용 ----------
page.range_var.set("2-3")
msgs.clear()
page.load_pdfs(); pump()
assert order() == ["small2", "small3", "photo1", "scan1", "scan2", "scan3", "note1"], order()
assert page.status.get() == "총 7쪽"
assert msgs and msgs[0][0] == "warn" and "broken.png" in msgs[0][1][1], msgs     # 손상 파일만 빠지고 경고
types = dict(asked["filetypes"])
assert "*.pdf" in types["PDF와 이미지"] and "*.png" in types["PDF와 이미지"] and "*.jpg" in types["이미지 파일"]
assert set(page.image_pdfs) == {JPG, TIF, png}
assert tree.set(tree.get_children()[2], "file") == "photo.jpg"
assert str(root.cget("cursor")) == ""                     # 기다림 표시를 되돌림
print("6. PDF와 이미지 섞어 불러오기 OK")

# ---------- 7. 순서 바꾸기, 이 파일의 쪽 모두 선택, 실행 취소 ----------
kids = tree.get_children()
tree.selection_set((kids[6], kids[2]))                     # note, photo
page.move_to(1)
assert order() == ["photo1", "note1", "small2", "small3", "scan1", "scan2", "scan3"], order()
assert page.select_file_pages(TIF) == 3
page.move_to(2)
assert order() == ["photo1", "scan1", "scan2", "scan3", "note1", "small2", "small3"], order()
page.undo()
assert order() == ["photo1", "note1", "small2", "small3", "scan1", "scan2", "scan3"], order()
page.redo()
print("7. 순서 바꾸기, 파일 단위 선택, 실행 취소 OK")

# ---------- 8. 저장: 이미지 쪽의 크기와 내용, 파일 이름 북마크, 원본과 같은 경로 거부 ----------
OUT = tmp("out.pdf")
filedialog.asksaveasfilename = lambda **k: OUT
page.file_bookmark_var.set(True)
msgs.clear()
page.save()
t0 = time.time()
while not msgs and time.time() - t0 < 20:
    pump(0.05)
assert msgs and msgs[-1][0] == "info", msgs
out = PdfReader(OUT)
assert len(out.pages) == 7
assert [o.title for o in out.outline] == ["photo", "scan", "note", "small"], [o.title for o in out.outline]
for i in (0, 1, 4):                                        # 이미지 쪽은 A4 너비
    assert close(out.pages[i].mediabox.width, A4W), (i, out.pages[i].mediabox)
assert close(out.pages[5].mediabox.width, 595.276, 1)      # PDF 쪽(reportlab A4)은 그대로
assert xobject(out.pages[0])["/Filter"] == "/DCTDecode"
with open(JPG, "rb") as f:
    assert xobject(out.pages[0])._data == f.read()         # 저장한 PDF에도 JPG가 그대로 들어 있음
assert [page_image(out.pages[i]).getpixel((5, 5)) for i in (1, 2, 3)] == [0, 128, 255]
assert "S2" in out.pages[5].extract_text()
page.file_bookmark_var.set(False)
filedialog.asksaveasfilename = lambda **k: png
msgs.clear(); page.save(); pump()
assert msgs and msgs[-1][0] == "error"                     # 불러온 이미지 파일 위에 저장하지 않음
print("8. 저장(크기, 내용, 북마크), 같은 경로 거부 OK")

# ---------- 9. 화면 배치: 안내 문구가 두 줄이 되어도 저장 버튼과 진행 막대가 보임 ----------
def check_layout(top, pg, sizes):
    for size in sizes:
        top.geometry(size)
        pump(0.1)
        bottom = top.winfo_rooty() + top.winfo_height()
        for w in (pg.save_btn, pg.progress, pg.tree):
            assert w.winfo_ismapped(), (size, w)
            assert w.winfo_rooty() + w.winfo_height() <= bottom + 1, (size, str(w))
        assert pg.tree.winfo_height() > 40, (size, pg.tree.winfo_height())
check_layout(root, page, ["640x460", "780x560", "1100x600"])
print("9. 경량판 화면 배치 OK (640x460, 780x560, 1100x600)")

# ---------- 10. 렌더링판: 썸네일, 미리보기, 이미지로 저장 ----------
if HAS_RENDER:
    import pdf_tool_render as R

    rtop = tk.Toplevel(root)
    rpage = R.build_window(rtop)
    rtop.geometry("1200x750")
    pump(0.3)
    rtree = rpage.tree
    filedialog.askopenfilenames = lambda **k: (SMALL, JPG, TIF, tmp("rot6.jpg"))
    rpage.range_var.set("1")
    rpage.load_pdfs(); pump(0.5)
    assert order(rpage) == ["small1", "photo1", "scan1", "scan2", "scan3", "rot61"], order(rpage)
    kids = rtree.get_children()
    rtree.see(kids[-1]); pump(0.5)
    assert all(rtree.item(i, "image") for i in kids), [rtree.item(i, "image") for i in kids]
    assert not rpage._failed, rpage._failed
    w, h = rpage.docs.page_size(tmp("rot6.jpg"), 0)        # 세워 찍은 사진은 세로로 긴 쪽
    assert close(w, A4W) and h > w, (w, h)

    rtree.selection_set(kids[1]); rtree.focus(kids[1]); rpage._schedule_preview(); pump(0.3)
    assert rpage._preview_shown and rpage._preview_shown[0] == JPG
    assert "photo.jpg" in rpage.preview_caption.get()

    IMG_OUT = tmp("img_out"); os.makedirs(IMG_OUT)
    targets = [os.path.join(IMG_OUT, n) for n in ("a.png", "b.png")]
    msgs.clear()
    rpage.export_images([rpage.pages[kids[1]], rpage.pages[kids[3]]], targets, "PNG", 72)
    t0 = time.time()
    while not msgs and time.time() - t0 < 20:
        pump(0.05)
    assert msgs and msgs[-1][0] == "info", msgs
    with Image.open(targets[0]) as im:
        assert abs(im.width - 595) <= 1 and abs(im.height - 446) <= 1, im.size
        left, right = im.getpixel((50, im.height // 2)), im.getpixel((im.width - 50, im.height // 2))
        assert left[0] > 200 and right[2] > 200, (left, right)
    with Image.open(targets[1]) as im:
        assert abs(im.convert("L").getpixel((10, 10)) - 128) <= 2
    check_layout(rtop, rpage, ["900x560", "1100x600", "1400x750"])
    rtop.destroy()
    print("10. 렌더링판 썸네일, 미리보기, 이미지로 저장, 화면 배치 OK")
else:
    print("10. 렌더링판: pypdfium2가 없어 건너뜀")

root.destroy()
print("ALL IMAGE IMPORT TESTS PASSED")
