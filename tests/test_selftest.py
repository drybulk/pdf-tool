"""실행 파일 자체 검사(pdf_selftest.py) 테스트: 개발 환경에서 모든 검사를 통과하는지, 실패를 알리는지 확인합니다.
실행: xvfb-run -a python tests/test_selftest.py   (pip install -r requirements-render.txt 필요)
"""
import os
import subprocess
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, ROOT)

import importlib.util
if importlib.util.find_spec("pypdfium2") is None:
    raise SystemExit("pypdfium2가 설치되어 있지 않습니다: pip install -r requirements-render.txt")

import pdf_selftest

TMP = tempfile.mkdtemp(prefix="pdf_tool_test_")

# ---------- 1. 모든 검사 통과, 결과 파일 ----------
result = os.path.join(TMP, "result.txt")
assert pdf_selftest.run(result) == 0
text = open(result, encoding="utf-8").read()
assert "FAIL" not in text and text.rstrip().endswith("결과: 통과"), text
for name in ("라이브러리 버전", "PDF/이미지 불러오기", "렌더링과 이미지 변환", "PDF 저장", "창 만들기"):
    assert f"OK   {name}" in text, (name, text)
print("1. 모든 검사 통과 OK")

# ---------- 2. 검사 하나가 실패하면 종료 코드 1과 오류 내용 ----------
import pdf_render
original = pdf_render.encode_jpg
pdf_render.encode_jpg = lambda *a, **k: b"not a jpg"
try:
    assert pdf_selftest.run(result) == 1
finally:
    pdf_render.encode_jpg = original
text = open(result, encoding="utf-8").read()
assert "FAIL 렌더링과 이미지 변환" in text and "PNG/JPG 변환 결과가 올바르지 않습니다" in text, text
assert "OK   창 만들기" in text and text.rstrip().endswith("결과: 실패"), text
print("2. 실패 보고 OK")

# ---------- 3. 프로그램의 --selftest 인자: 종료 코드와 결과 파일, 창을 띄운 채 멈추지 않음 ----------
result2 = os.path.join(TMP, "result2.txt")
proc = subprocess.run([sys.executable, os.path.join(ROOT, "pdf_tool_render.py"), "--selftest", result2], timeout=120)
assert proc.returncode == 0, proc.returncode
assert open(result2, encoding="utf-8").read().rstrip().endswith("결과: 통과")
print("3. --selftest 인자 OK")

print("ALL SELFTEST TESTS PASSED")
