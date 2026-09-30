"""병합 로직 테스트 (화면 없이 실행 가능). 실행: python tests/test_merge.py"""
import os
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(HERE))
sys.path.insert(0, HERE)

from helpers import make_pdf
from pypdf import PdfReader

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
print("ALL MERGE TESTS PASSED")
