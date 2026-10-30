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
assert T.outline_entries(PdfReader(a2)) == [("1장", 0, 0), ("1.1절", 1, 1), ("2장", 2, 0)]

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
print("ALL MERGE TESTS PASSED")
