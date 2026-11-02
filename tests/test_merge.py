"""병합 로직 테스트 (화면 없이 실행 가능). 실행: python tests/test_merge.py"""
import os
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(HERE))
sys.path.insert(0, HERE)

from helpers import make_pdf
from pypdf import PdfReader, PdfWriter

import pdf_tool as T

tmp = tempfile.mkdtemp(prefix="pdf_tool_test_")
a = make_pdf(os.path.join(tmp, "a.pdf"), "A", 2)
b = make_pdf(os.path.join(tmp, "b.pdf"), "B", 3)
c = make_pdf(os.path.join(tmp, "c.pdf"), "C", 1)
out = os.path.join(tmp, "out.pdf")

# 1. 지정한 순서대로 합쳐지고 북마크가 만들어진다
total = T.merge_pdfs([c, a, b], out, add_bookmarks=True)
reader = PdfReader(out)
texts = [p.extract_text().strip() for p in reader.pages]
assert total == 6 and texts == ["C1", "A1", "A2", "B1", "B2", "B3"], texts
assert [o.title for o in reader.outline] == ["c", "a", "b"]
print("1. 병합 순서와 북마크 OK")

# 2. 북마크 옵션을 끄면 북마크가 없다
T.merge_pdfs([a, b], out, add_bookmarks=False)
assert len(PdfReader(out).outline) == 0
print("2. 북마크 끄기 OK")

# 3. 손상된 파일은 ValueError
bad = os.path.join(tmp, "bad.pdf")
with open(bad, "w") as f:
    f.write("not a pdf")
try:
    T.open_pdf(bad)
    raise SystemExit("오류가 발생해야 합니다")
except ValueError:
    pass
print("3. 손상 파일 오류 처리 OK")

# 4. 쪽 범위 해석
P = T.parse_page_ranges
assert P("721-732", 800) == list(range(720, 732))
assert P("1-3, 7, 10-11", 20) == [0, 1, 2, 6, 9, 10]
assert P("5-", 8) == [4, 5, 6, 7] and P("-3", 8) == [0, 1, 2] and P("", 4) == [0, 1, 2, 3]
assert P("5,1-2", 8) == [4, 0, 1]
for bad_range in ["0-3", "7-900", "9-2", "abc", "-", "1-2-3"]:
    try:
        P(bad_range, 800)
        raise SystemExit("오류가 발생해야 합니다: " + bad_range)
    except ValueError:
        pass
print("4. 쪽 범위 해석 OK")

# 5. save_pages: 쪽 순서 그대로 저장
pages = [(b, 2), (a, 0), (c, 0)]
T.save_pages(pages, out)
texts = [p.extract_text().strip() for p in PdfReader(out).pages]
assert texts == ["B3", "A1", "C1"], texts
print("5. save_pages OK")
# 6~8. save_pages의 북마크 옵션
def with_outline(src, dst, items):
    """src에 북마크를 넣어 dst로 저장. items: [(제목, 쪽 인덱스, 상위 항목 제목 또는 None), ...]"""
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


# a2: 1장(1쪽) > 1.1절(2쪽), 2장(3쪽) / b2: B장(2쪽)
a3 = make_pdf(os.path.join(tmp, "a3.pdf"), "A", 3)
a2 = with_outline(a3, os.path.join(tmp, "a2.pdf"), [("1장", 0, None), ("1.1절", 1, "1장"), ("2장", 2, None)])
b2 = with_outline(b, os.path.join(tmp, "b2.pdf"), [("B장", 1, None)])
assert [e[:3] for e in T.outline_entries(PdfReader(a2))] == [("1장", 0, 0), ("1.1절", 1, 1), ("2장", 2, 0)]

# 6. 기본값은 지금까지와 같이 북마크 없음
whole = [(a2, i) for i in range(3)] + [(b2, i) for i in range(3)]
T.save_pages(whole, out)
assert outline_of(out) == []
# 파일 전체를 원래 순서로 저장하면 merge_pdfs와 같은 목차가 된다
T.save_pages(whole, out, file_bookmarks=True, keep_outlines=True)
merged = os.path.join(tmp, "merged.pdf")
T.merge_pdfs([a2, b2], merged, add_bookmarks=True)
expected = [(0, "a2", 1), (1, "1장", 1), (2, "1.1절", 2), (1, "2장", 3), (0, "b2", 4), (1, "B장", 5)]
assert outline_of(out) == outline_of(merged) == expected, (outline_of(out), outline_of(merged))
print("6. 북마크 기본값과 merge_pdfs와의 일치 OK")

# 7. 일부 쪽만, 순서를 바꿔서: 빠진 쪽의 북마크는 없어지고, 빠진 상위 항목의 하위 항목은 위로 올라간다
pages = [(b2, 1), (a2, 1), (a2, 2), (b2, 0)]
T.save_pages(pages, out, keep_outlines=True)
# 순서는 파일이 처음 나오는 순서, 같은 파일 안에서는 원본 목차의 순서
assert outline_of(out) == [(0, "B장", 1), (0, "1.1절", 2), (0, "2장", 3)], outline_of(out)
# 파일 이름 북마크는 같은 파일이 이어지는 구간마다 만들어지고, 원본 북마크는 그 쪽이 속한 구간 아래에 들어간다
T.save_pages(pages, out, file_bookmarks=True, keep_outlines=True)
assert outline_of(out) == [
    (0, "b2", 1), (1, "B장", 1), (0, "a2", 2), (1, "1.1절", 2), (1, "2장", 3), (0, "b2", 4)
], outline_of(out)
T.save_pages(pages, out, file_bookmarks=True)
assert outline_of(out) == [(0, "b2", 1), (0, "a2", 2), (0, "b2", 4)], outline_of(out)
print("7. 일부 쪽, 순서 변경 시 북마크 OK")

# 8. 같은 쪽이 두 번 들어 있으면 원본 북마크는 처음 나오는 위치를 가리킨다
T.save_pages([(a2, 2), (a2, 0), (a2, 2)], out, keep_outlines=True)
assert outline_of(out) == [(0, "1장", 2), (0, "2장", 1)], outline_of(out)
print("8. 중복 쪽 북마크 OK")

# 9. 상위 항목과 하위 항목이 같은 파일의 서로 다른 구간에 있으면, 파일 이름 북마크를 만들 때는 하위 항목이 자기 구간 아래에 들어간다
pages = [(a2, 0), (b2, 1), (a2, 1)]
T.save_pages(pages, out, file_bookmarks=True, keep_outlines=True)
assert outline_of(out) == [
    (0, "a2", 1), (1, "1장", 1), (0, "b2", 2), (1, "B장", 2), (0, "a2", 3), (1, "1.1절", 3)
], outline_of(out)
# 파일 이름 북마크가 없으면 구간을 나눌 기준이 없으므로 원본의 상하 관계를 유지한다
T.save_pages(pages, out, keep_outlines=True)
assert outline_of(out) == [(0, "1장", 1), (1, "1.1절", 3), (0, "B장", 2)], outline_of(out)
print("9. 구간이 나뉜 상하 관계 OK")
# 10~12. 이름 붙은 대상(named destination)과 본문 링크: 쪽 안의 위치(좌표) 유지
from pypdf.generic import (ArrayObject, DictionaryObject, Fit, FloatObject, NameObject, NullObject,
                           RectangleObject, TextStringObject)


def with_links(src, dst, names):
    """
    LaTeX(hyperref) 논문처럼 만듦. names: [(이름, 대상 쪽 인덱스, 위쪽 좌표), ...]
    첫 쪽에 이름마다 링크 2개(/A GoTo 방식과 /Dest 방식)를 넣음. 첫 번째 이름은 북마크도 같은 위치를 가리킴.
    """
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
    """{이름: (1부터 시작하는 쪽 번호, 대상 종류, 위쪽 좌표)}"""
    r = PdfReader(path)
    return {k: (r.get_destination_page_number(v) + 1, v["/Type"], v.get("/Top")) for k, v in r.named_destinations.items()}


def link_names(path, page):
    """그 쪽의 링크가 가리키는 이름 목록 (주석 순서대로)"""
    r = PdfReader(path)
    result = []
    for ref in r.pages[page].get("/Annots", []):
        a = ref.get_object()
        result.append(str(a["/A"]["/D"]) if "/A" in a else str(a["/Dest"]))
    return result


p4 = make_pdf(os.path.join(tmp, "p4.pdf"), "P", 4)
q3 = make_pdf(os.path.join(tmp, "q3.pdf"), "Q", 3)
pl = with_links(p4, os.path.join(tmp, "pl.pdf"), [("cite.a", 3, 300), ("figure.1", 2, 500)])
ql = with_links(q3, os.path.join(tmp, "ql.pdf"), [("figure.1", 2, 400)])

# 10. 전체를 저장해도, 일부 쪽만 순서를 바꿔 저장해도 원본 좌표(/XYZ 위쪽 좌표)를 유지한다
T.save_pages([(pl, i) for i in range(4)], out)
assert named(out) == {"cite.a": (4, "/XYZ", 300), "figure.1": (3, "/XYZ", 500)}, named(out)
T.save_pages([(pl, 3), (pl, 0)], out)                   # 4쪽, 1쪽 순서. 3쪽(figure.1)은 빠짐
assert named(out) == {"cite.a": (1, "/XYZ", 300)}, named(out)
assert link_names(out, 1) == ["cite.a", "cite.a", "figure.1", "figure.1"]
T.save_pages([(pl, 0), (pl, 3), (pl, 3)], out)          # 같은 쪽 두 번: 처음 나오는 위치
assert named(out)["cite.a"] == (2, "/XYZ", 300), named(out)
# 원본 북마크도 쪽 안의 위치를 유지한다
T.save_pages([(pl, i) for i in range(4)], out, keep_outlines=True)
r = PdfReader(out)
assert [(o.title, r.get_destination_page_number(o) + 1, o["/Type"], o["/Top"]) for o in r.outline] == [("cite.a", 4, "/XYZ", 300)]
print("10. 이름 붙은 대상과 북마크의 위치 유지 OK")

# 11. 두 논문을 합칠 때 이름이 겹치면 뒤 논문의 이름을 바꾸고, 뒤 논문의 링크도 바꾼 이름을 가리킨다
pages = [(pl, i) for i in range(4)] + [(ql, i) for i in range(3)]
T.save_pages(pages, out)
assert named(out) == {
    "cite.a": (4, "/XYZ", 300), "figure.1": (3, "/XYZ", 500), "figure.1~2": (7, "/XYZ", 400)
}, named(out)
assert link_names(out, 0) == ["cite.a", "cite.a", "figure.1", "figure.1"]
assert link_names(out, 4) == ["figure.1~2", "figure.1~2"]
# 순서를 바꿔 뒤 논문의 쪽이 먼저 나와도, 이름은 파일이 처음 나오는 순서로 정함
T.save_pages([(ql, 0), (ql, 2), (pl, 0), (pl, 2)], out)
assert named(out) == {"figure.1": (2, "/XYZ", 400), "figure.1~2": (4, "/XYZ", 500)}, named(out)
assert link_names(out, 0) == ["figure.1", "figure.1"]
assert link_names(out, 2) == ["cite.a", "cite.a", "figure.1~2", "figure.1~2"]
print("11. 여러 논문의 이름 충돌 처리 OK")

# 12. 저장해도 불러온 원본(readers 캐시)은 바뀌지 않는다 (같은 목록을 다시 저장해도 결과가 같음)
readers = {}
T.save_pages(pages, out, readers=readers)
first = named(out)
assert link_names(ql, 0) == ["figure.1", "figure.1"]
assert [str(a.get_object().get("/Dest") or a.get_object()["/A"]["/D"]) for a in readers[ql].pages[0]["/Annots"]] == ["figure.1", "figure.1"]
T.save_pages(pages, out, readers=readers)
assert named(out) == first and link_names(out, 4) == ["figure.1~2", "figure.1~2"], (named(out), link_names(out, 4))
print("12. 원본 보존 OK")
print("ALL MERGE TESTS PASSED")
