"""
웹판 저장(web/js/pdfsave.js)이 데스크톱판 save_pages와 같은 결과를 내는지 검사합니다.
tests/test_merge.py의 5~12번과 같은 PDF, 같은 기대값을 쓰고, 같은 사례를 데스크톱판으로도 저장해서 결과를 비교합니다.
웹판 저장은 tests/web/save_cases.cjs가 Chromium에서 실행합니다(Node.js와 Playwright 필요).
실행: python tests/web/test_web_save.py
"""
import json
import os
import subprocess
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
TESTS = os.path.dirname(HERE)
sys.path.insert(0, os.path.dirname(TESTS))
sys.path.insert(0, TESTS)

from helpers import make_pdf
from pypdf import PdfReader, PdfWriter
from pypdf.generic import (ArrayObject, DictionaryObject, Fit, FloatObject, NameObject, NullObject,
                           RectangleObject, TextStringObject, DecodedStreamObject)

import pdf_common as C

tmp = tempfile.mkdtemp(prefix="pdf_tool_web_save_")


# ---------- tests/test_merge.py와 같은 도우미 ----------
def with_outline(src, dst, items):
    w = PdfWriter(clone_from=src)
    made = {}
    for title, idx, parent in items:
        made[title] = w.add_outline_item(title, idx, parent=made.get(parent))
    with open(dst, "wb") as f:
        w.write(f)
    return dst


def outline_of(path):
    """[(깊이, 제목, 1부터 시작하는 쪽 번호), ...]"""
    r = PdfReader(path)
    result = []

    def walk(items, depth):
        for it in items:
            if isinstance(it, list):
                walk(it, depth + 1)
            else:
                result.append((depth, it.title, r.get_destination_page_number(it) + 1))
    walk(r.outline, 0)
    return result


def with_links(src, dst, names):
    w = PdfWriter(clone_from=src)
    for name, idx, top in names:
        arr = ArrayObject([w.pages[idx].indirect_reference, NameObject("/XYZ"), FloatObject(72), FloatObject(top), NullObject()])
        w.add_named_destination_array(TextStringObject(name), arr)
        for key, value in [
            ("/A", DictionaryObject({NameObject("/S"): NameObject("/GoTo"), NameObject("/D"): TextStringObject(name)})),
            ("/Dest", TextStringObject(name)),
        ]:
            annot = DictionaryObject({
                NameObject("/Type"): NameObject("/Annot"), NameObject("/Subtype"): NameObject("/Link"),
                NameObject("/Rect"): RectangleObject((10, 10, 50, 50)), NameObject(key): value,
            })
            w.pages[0].setdefault(NameObject("/Annots"), ArrayObject()).append(w._add_object(annot))
    name, idx, top = names[0]
    w.add_outline_item(name, idx, fit=Fit.xyz(72, top, None))
    with open(dst, "wb") as f:
        w.write(f)
    return dst


def named(path):
    r = PdfReader(path)
    return {k: (r.get_destination_page_number(v) + 1, v["/Type"], v.get("/Top")) for k, v in r.named_destinations.items()}


def link_names(path, page):
    r = PdfReader(path)
    result = []
    for ref in r.pages[page].get("/Annots", []):
        a = ref.get_object()
        result.append(str(a["/A"]["/D"]) if "/A" in a else str(a["/Dest"]))
    return result


def texts(path):
    return [p.extract_text().strip() for p in PdfReader(path).pages]


# ---------- 원본 PDF ----------
a = make_pdf(os.path.join(tmp, "a.pdf"), "A", 2)
b = make_pdf(os.path.join(tmp, "b.pdf"), "B", 3)
c = make_pdf(os.path.join(tmp, "c.pdf"), "C", 1)
a3 = make_pdf(os.path.join(tmp, "a3.pdf"), "A", 3)
a2 = with_outline(a3, os.path.join(tmp, "a2.pdf"), [("1장", 0, None), ("1.1절", 1, "1장"), ("2장", 2, None)])
b2 = with_outline(b, os.path.join(tmp, "b2.pdf"), [("B장", 1, None)])
p4 = make_pdf(os.path.join(tmp, "p4.pdf"), "P", 4)
q3 = make_pdf(os.path.join(tmp, "q3.pdf"), "Q", 3)
pl = with_links(p4, os.path.join(tmp, "pl.pdf"), [("cite.a", 3, 300), ("figure.1", 2, 500)])
ql = with_links(q3, os.path.join(tmp, "ql.pdf"), [("figure.1", 2, 400)])
r2 = make_pdf(os.path.join(tmp, "r2.pdf"), "R", 2)
rl = with_links(r2, os.path.join(tmp, "rl.pdf"), [("figure.1", 0, 100), ("figure.1~2", 1, 200)])

# 웹판에서 추가로 확인하는 원본: 1쪽의 링크가 쪽 번호로 4쪽(큰 내용)을 직접 가리킴.
# pdf-lib의 copyPages를 그대로 쓰면 1쪽만 저장해도 4쪽의 내용이 함께 들어감
big = os.path.join(tmp, "big.pdf")
w = PdfWriter(clone_from=make_pdf(os.path.join(tmp, "big0.pdf"), "G", 4))
marker = b"BIGCONTENTMARKER" * 4000
stream = DecodedStreamObject()
stream.set_data(b"% " + marker + b"\n")
w.pages[3][NameObject("/Contents")] = ArrayObject([w.pages[3]["/Contents"], w._add_object(stream)])
annot = DictionaryObject({
    NameObject("/Type"): NameObject("/Annot"), NameObject("/Subtype"): NameObject("/Link"),
    NameObject("/Rect"): RectangleObject((10, 10, 50, 50)),
    NameObject("/Dest"): ArrayObject([w.pages[3].indirect_reference, NameObject("/XYZ"), FloatObject(0), FloatObject(600), NullObject()]),
    NameObject("/P"): w.pages[0].indirect_reference,
})
w.pages[0][NameObject("/Annots")] = ArrayObject([w._add_object(annot)])
with open(big, "wb") as f:
    w.write(f)

# 옛 방식(/Dests 사전과 이름 객체 링크)으로 만든 원본
old = os.path.join(tmp, "old.pdf")
w = PdfWriter(clone_from=make_pdf(os.path.join(tmp, "old0.pdf"), "O", 3))
w._root_object[NameObject("/Dests")] = DictionaryObject({
    NameObject("/sec.2"): ArrayObject([w.pages[2].indirect_reference, NameObject("/XYZ"), FloatObject(0), FloatObject(250), NullObject()]),
})
annot = DictionaryObject({
    NameObject("/Type"): NameObject("/Annot"), NameObject("/Subtype"): NameObject("/Link"),
    NameObject("/Rect"): RectangleObject((10, 10, 50, 50)), NameObject("/Dest"): NameObject("/sec.2"),
})
w.pages[0][NameObject("/Annots")] = ArrayObject([w._add_object(annot)])
with open(old, "wb") as f:
    w.write(f)

# ---------- 사례: 웹판으로 저장 ----------
CASES = {}


def case(key, pages, file_bookmarks=False, keep_outlines=False):
    CASES[key] = {"out": os.path.join(tmp, f"web_{key}.pdf"), "pages": [list(p) for p in pages],
                  "options": {"fileBookmarks": file_bookmarks, "keepOutlines": keep_outlines}}


whole = [(a2, i) for i in range(3)] + [(b2, i) for i in range(3)]
part = [(b2, 1), (a2, 1), (a2, 2), (b2, 0)]
split = [(a2, 0), (b2, 1), (a2, 1)]
both = [(pl, i) for i in range(4)] + [(ql, i) for i in range(3)]
case("order", [(b, 2), (a, 0), (c, 0)])
case("whole_default", whole)
case("whole_all", whole, True, True)
case("part_keep", part, keep_outlines=True)
case("part_all", part, True, True)
case("part_file", part, file_bookmarks=True)
case("dup_keep", [(a2, 2), (a2, 0), (a2, 2)], keep_outlines=True)
case("split_all", split, True, True)
case("split_keep", split, keep_outlines=True)
case("pl_whole", [(pl, i) for i in range(4)])
case("pl_part", [(pl, 3), (pl, 0)])
case("pl_dup", [(pl, 0), (pl, 3), (pl, 3)])
case("pl_keep", [(pl, i) for i in range(4)], keep_outlines=True)
case("both", both)
case("both_swapped", [(ql, 0), (ql, 2), (pl, 0), (pl, 2)])
case("rl", [(pl, 2), (rl, 0), (rl, 1)])
case("big_first", [(big, 0)])
case("big_all", [(big, 0), (big, 3)])
case("old", [(old, 0), (old, 2)])

spec = os.path.join(tmp, "cases.json")
with open(spec, "w", encoding="utf-8") as f:
    json.dump({"cases": list(CASES.values())}, f, ensure_ascii=False)
node = subprocess.run(["node", os.path.join(HERE, "save_cases.cjs"), spec], capture_output=True, text=True, encoding="utf-8")
if node.returncode != 0:
    print(node.stdout, node.stderr)
    raise SystemExit("웹판 저장 실행 실패")
out = {k: v["out"] for k, v in CASES.items()}


def desktop(key):
    """같은 사례를 데스크톱판 save_pages로 저장한 결과 경로"""
    v = CASES[key]
    path = os.path.join(tmp, f"py_{key}.pdf")
    C.save_pages([tuple(p) for p in v["pages"]], path,
                 file_bookmarks=v["options"]["fileBookmarks"], keep_outlines=v["options"]["keepOutlines"])
    return path


def same_as_desktop(key):
    py = desktop(key)
    js = out[key]
    assert texts(js) == texts(py), (key, texts(js), texts(py))
    assert outline_of(js) == outline_of(py), (key, outline_of(js), outline_of(py))
    assert named(js) == named(py), (key, named(js), named(py))
    for i in range(len(PdfReader(py).pages)):
        assert link_names(js, i) == link_names(py, i), (key, i, link_names(js, i), link_names(py, i))


# 5. 쪽 순서
assert texts(out["order"]) == ["B3", "A1", "C1"], texts(out["order"])
print("5. 쪽 순서 OK")

# 6. 북마크 기본값, 파일 전체를 원래 순서로 저장하면 merge_pdfs와 같은 목차
assert outline_of(out["whole_default"]) == []
expected = [(0, "a2", 1), (1, "1장", 1), (2, "1.1절", 2), (1, "2장", 3), (0, "b2", 4), (1, "B장", 5)]
assert outline_of(out["whole_all"]) == expected, outline_of(out["whole_all"])
print("6. 북마크 기본값과 merge_pdfs와의 일치 OK")

# 7. 일부 쪽, 순서 변경
assert outline_of(out["part_keep"]) == [(0, "B장", 1), (0, "1.1절", 2), (0, "2장", 3)], outline_of(out["part_keep"])
assert outline_of(out["part_all"]) == [
    (0, "b2", 1), (1, "B장", 1), (0, "a2", 2), (1, "1.1절", 2), (1, "2장", 3), (0, "b2", 4)
], outline_of(out["part_all"])
assert outline_of(out["part_file"]) == [(0, "b2", 1), (0, "a2", 2), (0, "b2", 4)], outline_of(out["part_file"])
print("7. 일부 쪽, 순서 변경 시 북마크 OK")

# 8. 같은 쪽 두 번: 처음 나오는 위치
assert outline_of(out["dup_keep"]) == [(0, "1장", 2), (0, "2장", 1)], outline_of(out["dup_keep"])
assert texts(out["dup_keep"]) == ["A3", "A1", "A3"]
print("8. 중복 쪽 북마크 OK")

# 9. 구간이 나뉜 상하 관계
assert outline_of(out["split_all"]) == [
    (0, "a2", 1), (1, "1장", 1), (0, "b2", 2), (1, "B장", 2), (0, "a2", 3), (1, "1.1절", 3)
], outline_of(out["split_all"])
assert outline_of(out["split_keep"]) == [(0, "1장", 1), (1, "1.1절", 3), (0, "B장", 2)], outline_of(out["split_keep"])
print("9. 구간이 나뉜 상하 관계 OK")

# 10. 이름 붙은 대상과 북마크의 위치 유지
assert named(out["pl_whole"]) == {"cite.a": (4, "/XYZ", 300), "figure.1": (3, "/XYZ", 500)}, named(out["pl_whole"])
assert named(out["pl_part"]) == {"cite.a": (1, "/XYZ", 300)}, named(out["pl_part"])
assert link_names(out["pl_part"], 1) == ["cite.a", "cite.a", "figure.1", "figure.1"]
assert named(out["pl_dup"])["cite.a"] == (2, "/XYZ", 300), named(out["pl_dup"])
r = PdfReader(out["pl_keep"])
assert [(o.title, r.get_destination_page_number(o) + 1, o["/Type"], o["/Top"]) for o in r.outline] == [("cite.a", 4, "/XYZ", 300)]
print("10. 이름 붙은 대상과 북마크의 위치 유지 OK")

# 11. 여러 논문의 이름 충돌
assert named(out["both"]) == {
    "cite.a": (4, "/XYZ", 300), "figure.1": (3, "/XYZ", 500), "figure.1~2": (7, "/XYZ", 400)
}, named(out["both"])
assert link_names(out["both"], 0) == ["cite.a", "cite.a", "figure.1", "figure.1"]
assert link_names(out["both"], 4) == ["figure.1~2", "figure.1~2"]
assert named(out["both_swapped"]) == {"figure.1": (2, "/XYZ", 400), "figure.1~2": (4, "/XYZ", 500)}, named(out["both_swapped"])
assert link_names(out["both_swapped"], 0) == ["figure.1", "figure.1"]
assert link_names(out["both_swapped"], 2) == ["cite.a", "cite.a", "figure.1~2", "figure.1~2"]
assert named(out["rl"]) == {"figure.1": (1, "/XYZ", 500), "figure.1~3": (2, "/XYZ", 100), "figure.1~2": (3, "/XYZ", 200)}, named(out["rl"])
assert link_names(out["rl"], 1) == ["figure.1~3", "figure.1~3", "figure.1~2", "figure.1~2"], link_names(out["rl"], 1)
print("11. 여러 논문의 이름 충돌 처리 OK")

# 12. 데스크톱판과 같은 결과 (쪽 내용, 북마크, 이름 붙은 대상, 링크)
for key in ["order", "whole_default", "whole_all", "part_keep", "part_all", "part_file", "dup_keep", "split_all",
            "split_keep", "pl_whole", "pl_part", "pl_dup", "pl_keep", "both", "both_swapped", "rl"]:
    same_as_desktop(key)
print("12. 데스크톱판 save_pages와 같은 결과 OK")

# 13. 링크가 가리키는 쪽을 빼고 저장하면 그 쪽의 내용이 들어가지 않음 (pdf-lib copyPages의 문제 회피)
with open(out["big_first"], "rb") as f:
    data = f.read()
assert b"BIGCONTENTMARKER" not in data, "빠진 쪽의 내용이 함께 저장됨"
assert len(data) < 20000, len(data)
rb = PdfReader(out["big_first"])
link = rb.pages[0]["/Annots"][0].get_object()
assert isinstance(link["/Dest"][0], NullObject), link["/Dest"]          # 결과에 없는 쪽은 null
assert link.raw_get("/P").idnum == rb.pages[0].indirect_reference.idnum       # 주석의 /P는 결과의 쪽
rb = PdfReader(out["big_all"])
link = rb.pages[0]["/Annots"][0].get_object()
assert rb.get_destination_page_number(  # 직접 쪽을 가리키는 링크도 결과의 쪽(2쪽)을 가리킴
    rb._build_destination("x", link["/Dest"])) == 1
with open(out["big_all"], "rb") as f:
    assert f.read().count(b"BIGCONTENTMARKER" * 10) <= 400, "같은 내용이 여러 번 들어감"
print("13. 링크 대상 쪽의 내용이 함께 복사되지 않음 OK")

# 14. 옛 방식(/Dests 사전, 이름 객체 링크): 이름 트리로 옮기고 링크는 문자열로 바꿈
assert named(out["old"]) == {"sec.2": (2, "/XYZ", 250)}, named(out["old"])
assert link_names(out["old"], 0) == ["sec.2"], link_names(out["old"], 0)
print("14. 옛 방식의 이름 붙은 대상 OK")
print("ALL WEB SAVE TESTS PASSED")
