# PDF 도구

PDF 병합, 쪽 범위 추출, 쪽 단위 순서 편집(마우스 드래그)을 제공하는 tkinter 기반 GUI 프로그램입니다.
두 가지 판이 있습니다.

| 판 | 실행 파일 | 외부 라이브러리 | 차이 |
|---|---|---|---|
| 경량판 | `pdf_tool.py` | `pypdf` | 기본 기능 |
| 렌더링판 | `pdf_tool_render.py` | `pypdf`, `pypdfium2` | 쪽 목록에 썸네일을 표시하고, 클릭한 쪽을 오른쪽에 크게 보여 줍니다 |

GUI는 파이썬에 기본으로 포함된 `tkinter`를 사용합니다.

## 설치와 실행

```
pip install -r requirements.txt
python pdf_tool.py
```

실행에는 `pdf_tool.py`와 같은 폴더에 있는 공통 모듈 `pdf_common.py`가 함께 필요합니다.

렌더링판:

```
pip install -r requirements-render.txt
python pdf_tool_render.py
```

렌더링판은 `pdf_common.py`와 `pdf_render.py`가 같은 폴더에 있어야 합니다. 기본 창 크기는 1200×750이며, 화면이 작으면 화면 안에 들어오도록 줄어듭니다.

검증한 환경은 Python 3.12, pypdf 5.9.0입니다.

## 기능

**탭 1. PDF 병합**
- 여러 PDF를 추가하고 순서를 정한 뒤 하나로 합칩니다. 목록은 순서, 파일 이름, 쪽수, 폴더를 표로 보여 줍니다.
- 행을 마우스로 끌거나 위/아래 버튼으로 순서를 바꿀 수 있습니다. 끌 때의 동작은 탭 2와 같습니다.
- 파일 이름으로 북마크(목차)를 추가하는 옵션이 있습니다.

**탭 2. 페이지 추출 / 편집**
- 쪽 범위를 지정해서 불러옵니다. 예: `721-732`, `1-3, 10, 15-20`, `5-`(5쪽부터 끝까지), 비우면 전체. 쪽 번호는 PDF 뷰어의 쪽 번호 기준이며 입력한 순서가 유지됩니다.
- 쪽을 마우스로 끌어서 순서를 바꿀 수 있습니다. 끄는 동안 놓을 위치에 빨간 가로선이 나타나고, 마우스를 놓으면 그 위치로 옮겨집니다.
- Ctrl/Shift+클릭으로 여러 쪽을 선택해 함께 옮길 수 있습니다. 떨어져 있는 쪽들을 선택해 끌어도 놓은 위치에 원래 순서대로 모입니다. 목록 바깥으로 끌면 자동 스크롤됩니다.
- 쪽을 옮기면 옮긴 쪽이 화면에 보이도록 스크롤되고, 잠깐 주황색으로 강조됩니다.
- 선택 삭제, 위/아래 이동, 맨 위/맨 아래, 위치 지정 이동, 전체 선택, 목록 비우기를 지원합니다.
- 현재 화면의 순서 그대로 새 PDF로 저장합니다.

**렌더링판에서 추가되는 기능 (탭 2)**
- 쪽 목록의 각 행에 썸네일을 표시합니다. 화면에 보이는 쪽만 그리고, 최근 300장을 보관합니다.
- 마지막으로 클릭한 쪽(키보드 위/아래 화살표로 옮긴 쪽 포함)을 오른쪽 미리보기 영역에 맞게 크게 보여 줍니다.
- 목록과 미리보기 사이의 경계를 마우스로 끌어서 두 영역의 폭을 조절할 수 있습니다.

## 단축키 (탭 2)

| 키 | 동작 |
|---|---|
| Ctrl+Z | 실행 취소 (최대 100단계) |
| Ctrl+Y, Ctrl+Shift+Z | 다시 실행 |
| Ctrl+A | 전체 선택 |
| Delete | 선택 삭제 |

## 테스트

```
pip install -r requirements.txt -r requirements-dev.txt
xvfb-run -a python tests/test_page_tab.py   # Linux. 화면이 있는 환경에서는 xvfb-run 없이 실행
xvfb-run -a python tests/test_undo.py
xvfb-run -a python tests/test_common.py
xvfb-run -a python tests/test_merge_tab.py
python tests/test_merge.py

# 렌더링판 (pip install -r requirements-render.txt 필요)
xvfb-run -a python tests/test_render.py
```

Linux에서는 `python3-tk`와 `xvfb`가 필요합니다.

렌더링 속도는 `python tools/bench_render.py 파일.pdf [--pages 100]`으로 측정할 수 있습니다. 썸네일, 미리보기, 200/300 DPI 렌더링의 쪽당 시간을 출력합니다. 각 쪽을 처음 그리는 시간을 따로 보여 주고, 시간이 가장 길었던 쪽 번호와 저장용 PNG를 만드는 시간도 함께 출력합니다.

## 문서

- `CLAUDE.md`: 작업 원칙과 프로젝트 맥락 (Claude Code가 세션 시작 때 읽는 파일)
- `docs/extension_plan.md`: 미리보기, 이미지 저장, 메뉴 구조의 확장 계획
