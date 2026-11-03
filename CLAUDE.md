# PDF 도구: Claude Code용 프로젝트 지침

이 파일은 새 세션이 시작될 때마다 자동으로 읽힙니다. 세부 내용은 `docs/`의 문서를 필요할 때 읽습니다.

## 프로젝트

PDF 병합, 쪽 범위 추출, 쪽 단위 순서 편집(마우스 드래그)을 제공하는 tkinter GUI 프로그램입니다. 사용자는 주로 논문과 보고서 PDF를 다룹니다. `pdf_tool.py`(GUI)와 공통 모듈 `pdf_common.py`로 이루어진 판을 "경량판"이라고 부르며, 외부 라이브러리는 `pypdf`만 사용합니다. 쪽 썸네일과 미리보기를 더한 "렌더링판"은 `pdf_tool_render.py`(GUI)와 `pdf_render.py`(렌더링 모듈)이며, `pdf_common.py`를 함께 사용하고 `pypdfium2`가 추가로 필요합니다. 렌더링판의 JPG 저장에는 `Pillow`도 사용합니다(없으면 PNG만 저장). 이미지 파일을 쪽으로 불러오는 기능도 `Pillow`를 사용하며, 경량판에서는 선택 사항입니다(없으면 PDF만 불러옴).

## 작업 원칙

이 문서에서 "사용자"는 프로그램을 쓰는 사람이 아니라 이 저장소의 관리자를 가리킵니다(결정 사항, 승인 등).

- 확인하지 않은 것은 확인하지 않았다고 밝힙니다. 관리자의 의도가 불분명하면 추측하지 말고 확인합니다.
- 코드 주석과 화면 문자열은 현재 관례대로 한국어로 작성합니다.
- 새 외부 라이브러리를 추가하기 전에는 관리자에게 먼저 확인합니다. 라이브러리 사용은 최소화합니다. 새 라이브러리를 추가하면 `THIRD_PARTY_NOTICES.md`에도 적습니다.
- 작업은 별도 브랜치에서 진행하고, main에 직접 푸시하지 않습니다. 병합은 관리자가 풀 리퀘스트를 검토한 뒤에 결정합니다.
- 코드를 옮기기만 하는 변경(동작 변화 없음)과 기능을 추가하는 변경은 커밋을 나누고, 가능하면 풀 리퀘스트도 나눕니다.
- 코드를 바꾼 뒤에는 아래 테스트를 실행하고, 실행하지 못했다면 그 사실을 밝힙니다.

## 현재 구조

`pdf_common.py` (경량판과 렌더링판의 공통 모듈):
- 처리 로직 함수: `open_pdf`, `parse_page_ranges`, `merge_pdfs`, `save_pages`, `outline_entries`, `dest_fit`, `copy_named_destinations`, `run_background`
- 이미지 불러오기: `is_image_file`(확장자 `IMAGE_EXTENSIONS`), `image_to_pdf`(이미지 파일 → PDF 바이트), `open_source`(이미지면 PDF로 바꿔서 연 PdfReader). Pillow는 `try: from PIL import Image`로 가져오며 `HAS_PILLOW`로 확인합니다.
  - 이미지 1장 = 1쪽, 쪽 너비 `IMAGE_PAGE_WIDTH`(A4 너비 595.28pt), 높이는 비율대로, 여백 없음. 여러 쪽 TIFF는 쪽마다 1쪽, 움직이는 GIF/WebP는 첫 장면만.
  - JPG(RGB, 회색조)는 파일 내용을 그대로 DCTDecode로 넣고, Exif 방향 3/6/8은 쪽의 /Rotate로 반영합니다. 거울상 방향, CMYK JPG, 그 밖의 형식은 `_flatten_image`로 8비트 RGB/회색조로 바꿔(투명은 흰색 합성, 16비트 회색조는 화소 값과 관계없이 256으로 나눔) zlib 수준 6으로 넣습니다. PDF 파일은 `_build_image_pdf`가 직접 씁니다(pypdf의 비공개 API를 쓰지 않기 위해).
  - `PageTab.open_source(path)`가 PdfReader를 `self.readers`에, 이미지로 만든 PDF 바이트를 `self.image_pdfs`에 보관합니다. 행은 PDF와 똑같이 (이미지 경로, 쪽 인덱스)로 식별하므로 실행 취소, 저장, 북마크, 이미지로 저장은 그대로 동작합니다. 쪽 범위 입력은 PDF에만 적용합니다.
  - 불러오는 동안 창의 커서를 기다림 표시(`watch`)로 바꿉니다. 4000×3000 PNG 사진 1장 변환에 컨테이너에서 약 1~3초 걸렸습니다(JPG는 다시 압축하지 않으므로 거의 즉시).
  - `merge_pdfs`는 `writer.append`를 사용하므로 원본 북마크가 유지됩니다. `save_pages`는 `add_page`를 사용하므로 북마크를 직접 다시 만들며, `file_bookmarks`(파일 이름 북마크)와 `keep_outlines`(원본 북마크 유지) 인자로 제어합니다. 두 인자의 기본값은 False입니다.
  - `save_pages`는 본문 링크(인용 번호, 그림 번호 등)가 가리키는 이름 붙은 대상(named destination)을 `copy_named_destinations`로 원본 좌표(/XYZ 등)까지 옮깁니다. pypdf의 `add_page`는 이 이름을 저장할 때 쪽 맨 위(/FitH)로 다시 만들기 때문입니다(pypdf 6.21.4, 5.9.0에서 확인). 여러 PDF의 이름이 겹치면 뒤 파일의 이름을 `이름~2`로 바꾸고 그 파일 쪽의 링크도 바꿉니다. 원본 북마크도 `dest_fit`으로 쪽 안의 위치를 유지합니다.
- `DragTree(ttk.Treeview)`: 마우스 드래그 정렬, Ctrl/Shift 선택, 자동 스크롤. `PageTab`의 쪽 목록이 이 위젯을 사용합니다.
  - 끄는 동안에는 행을 움직이지 않고, 놓을 위치에 빨간 가로 표시선(`_indicator`, 목록 위에 `place()`로 겹친 Frame)을 보여 줍니다. 마우스가 행의 위쪽 절반에 있으면 그 행 앞, 아래쪽 절반에 있으면 그 행 뒤가 놓을 위치입니다(`_drop_slot`).
  - 마우스를 놓으면 선택한 행들이 상대 순서를 유지한 채 그 위치에 모입니다(`_gather_selection`). "위치 지정 이동"(`move_selection_to`)도 같은 함수를 사용합니다.
  - 누른 행을 벗어나야 드래그로 간주합니다. 같은 행 안에서 놓으면 클릭으로 처리해서 그 행 하나만 선택합니다.
  - 행을 옮기면(드래그, `shift_selection`, `move_selection_to`) 옮긴 행이 보이도록 스크롤하고(`reveal_selection`), 선택 색을 0.4초 동안 주황색으로 바꿨다가 되돌립니다(`flash_selection`).
  - 선택 색은 위젯마다 따로 만든 스타일(`Drag숫자.Treeview`)의 `map`으로 지정합니다. 그래서 목록에 포커스가 없어도 선택 색이 흐려지지 않고, 강조색 변경이 다른 목록에 영향을 주지 않습니다.
- `IS_MAC`: macOS 여부, `UNDO_LIMIT`: 실행 취소 최대 단계 수, `APP_VERSION`: 프로그램 버전("프로그램 정보"와 자체 검사에 표시). 릴리스할 때는 이 값을 먼저 바꾸고 같은 이름의 태그(`v` + 값)를 올립니다. `tools/build_exe.py`가 `v`로 시작하는 버전이 이 값과 다르면 빌드를 멈춥니다.
- `PageTab`: 쪽 범위 불러오기, 쪽 단위 편집, 저장(여러 PDF를 불러오면 병합), 실행 취소. 프로그램의 유일한 화면이며, 창에 탭 없이 바로 붙습니다. 저장 옵션 체크박스 2개(원본 북마크 유지는 기본 켬, 파일 이름 북마크는 기본 끔)는 버튼 영역이 아니라 목록 아래 줄에 있습니다. 저장 경로가 원본과 같으면 저장하지 않습니다.
  - 예전의 병합 탭(`MergeTab`, 파일 단위 목록)은 이 화면으로 통합하고 삭제했습니다(사용자 승인, 2026-10-30). 파일 단위 선택("이 파일의 쪽 모두 선택")은 우클릭 메뉴 단계에서 추가합니다. `merge_pdfs`는 화면에서 쓰지 않지만 처리 로직 함수로 남겨 두었습니다.
  - 단축키는 `winfo_ismapped()`로 화면에 보일 때만 처리합니다. 지금은 탭이 하나뿐이지만 나중에 탭이나 창이 늘어날 때를 위해 유지합니다.
  - 목록 아래의 위젯(안내 문구, 저장 옵션, 저장 버튼, 진행 막대)은 `side="bottom"`으로 목록보다 먼저 배치합니다. 창이 낮으면 목록이 줄어들고 저장 버튼과 진행 막대는 밀려나지 않습니다(전에는 640×460에서 진행 막대가 보이지 않았음).
- 메뉴 막대와 우클릭 메뉴 (4단계):
  - 메뉴 막대는 `PageTab.make_menubar(root)`가 만들어 창에 붙입니다. 각 판의 `build_window(root)`가 창 제목, 크기, 메뉴 막대, 화면을 한꺼번에 준비하고 `main()`은 이 함수를 부릅니다. 테스트도 `build_window`를 사용합니다.
  - 구성은 `menu_items()`(파일, 편집, 도움말)와 `context_menu_items()`(우클릭)가 돌려주는 목록으로 정합니다. 항목은 `(이름, 동작, 단축키 표시, 조건)`이고 None은 구분선입니다. 렌더링판은 `_file_menu_items()`와 `context_menu_items()`를 바꿔서 "이미지로 저장..."을 더합니다.
  - 조건(`_menu_condition`): None은 작업 중(`busy`)이 아닐 때, "always"는 항상, "rows"는 목록에 쪽이 있을 때, "selection"은 선택한 쪽이 있을 때, "undo"/"redo"는 기록이 있을 때, "row"는 행을 우클릭했을 때입니다. 메뉴 막대는 `postcommand`로, 우클릭 메뉴는 띄우기 직전에 `update_menu`로 갱신합니다.
  - 우클릭 선택 규칙(`DragTree.select_for_context`): 이미 선택된 행이면 선택을 유지하고, 아니면 그 행만 선택합니다. 그 행을 포커스 행으로 기록하므로 렌더링판 미리보기도 그 쪽으로 바뀝니다. 끄는 중이거나 열 머리글에서는 메뉴를 띄우지 않습니다. macOS에서는 `<Button-2>`와 Control+클릭도 등록합니다(macOS에서 확인하지 않음).
  - "이 파일의 쪽 모두 선택"(`select_file_pages`)은 우클릭한 행과 같은 경로의 쪽을 모두 선택합니다. 메뉴 항목 이름 뒤에 파일 이름을 표시합니다. 이어서 끌거나 "맨 위로"를 고르면 그 파일의 쪽이 한곳에 모입니다.
  - 메뉴를 띄우는 `popup_menu`는 테스트에서 바꿔치기합니다(`tk_popup`은 grab을 잡기 때문). 항목 위치는 `menu_entry(메뉴, 이름)`로 찾습니다.
  - 단축키 Ctrl+O(불러오기), Ctrl+S(저장)를 더했습니다. 대화 상자 같은 다른 창에서 누르면 처리하지 않습니다(`_on_file_key`가 `winfo_toplevel()`을 비교).
  - "도움말 > 프로그램 정보"는 판 이름과 `LIBRARIES`의 버전(`importlib.metadata`), Python과 Tk 버전을 보여 줍니다.
- 렌더링판은 `PageTab`을 상속해서 썸네일과 미리보기를 덧붙입니다. 이를 위해 `PageTab`에는 다음 연결 지점이 있습니다.
  - `_make_list_frame(body)`: 쪽 목록을 담을 프레임을 만들어 배치합니다. 렌더링판은 이 메서드를 바꿔서 나눔 창(목록 | 미리보기)을 만듭니다.
  - `self.tree_scroll`: 목록의 세로 스크롤바입니다. 렌더링판은 스크롤할 때 썸네일을 그리려고 `yscrollcommand`를 감쌉니다.
  - `update_status()`: 행 목록이 바뀌는 모든 경우(불러오기, 실행 취소 복원, 삭제, 비우기)에 호출됩니다. 렌더링판은 이 메서드를 바꿔서 썸네일과 미리보기를 갱신합니다. 행 목록을 바꾸는 새 기능을 추가하면 반드시 `update_status()`를 호출해야 합니다.
- `DragTree`는 행을 클릭하면 그 행을 Treeview의 포커스 행(`focus()`)으로 기록하고, 포커스 행이 바뀌면 `<<RowFocus>>` 가상 이벤트를 보냅니다. 이미 선택된 행을 클릭하면 선택은 바뀌지 않으므로 `<<TreeviewSelect>>`만으로는 알 수 없기 때문입니다.

`pdf_tool.py` (경량판 GUI):
- `main()`만 들어 있습니다. 창을 만들고 공통 모듈의 `PageTab`을 붙입니다.
- 공통 모듈의 이름들을 `from pdf_common import ...`로 가져와 `__all__`로 다시 내보냅니다. 기존 테스트가 `pdf_tool.PageTab`, `pdf_tool.UNDO_LIMIT`처럼 접근하므로 이 방식을 유지합니다.

`pdf_render.py` (렌더링 모듈, pypdfium2 사용):
- `PdfiumDocs(source=None)`: 경로별로 `PdfDocument`를 열어 두고 쪽 크기 조회(`page_size`)와 렌더링(`render_ppm`)을 제공합니다. PDFium이 열지 못하면 `ValueError`를 발생시킵니다. `source(경로)`가 돌려준 값(경로 또는 PDF 바이트)을 엽니다. 렌더링판은 `self.image_pdfs.get(경로, 경로)`를 넘겨서 이미지에서 불러온 쪽을 그립니다.
- `bitmap_to_ppm`: RGB 비트맵을 PPM(P6) 바이트로 바꿉니다. 행 간격(stride)을 고려해 행 단위로 복사합니다.
- `thumb_scale`, `fit_scale`: 썸네일 배율(기본 0.12, A4 기준 칸 `THUMB_BOX` = 72×102 픽셀을 넘지 않게 줄임)과 미리보기 배율(영역에 맞춤)을 계산합니다.
- `LRUCache`: 썸네일 보관용 캐시입니다. 넘치면 가장 오래 쓰지 않은 항목을 버리고 `on_evict`를 호출합니다.
- 이미지 저장용: `PdfiumDocs.render_rgb`(행 간격 없는 RGB 바이트), `encode_png`(표준 라이브러리 zlib, 압축 수준 `PNG_LEVEL` = 6, 해상도는 pHYs 청크에 기록), `encode_jpg`(Pillow), `image_file_names`(`원본이름_p0721.png`, 원본 쪽 번호를 4자리 이상으로 쓰고 이름이 겹치면 `_2`, `_3`을 붙임. Windows처럼 대소문자를 구분하지 않고 비교), `DPI_CHOICES`.
- Pillow는 `try: from PIL import Image`로 가져오며, 없으면 `HAS_PILLOW`가 False이고 JPG 선택이 비활성화됩니다.
- 경량판이 pypdfium2 없이 실행되도록, pypdfium2를 가져오는 코드는 이 파일에만 둡니다.

`pdf_tool_render.py` (렌더링판 GUI):
- `RenderPageTab(PageTab)`: 썸네일 열(`#0`)과 미리보기 영역을 더합니다.
  - 썸네일은 화면에 보이는 행과 위아래 2행만 그립니다(`visible_rows`). 한 번에 30ms까지 그리고, 남은 것은 이벤트를 처리한 뒤 이어서 그립니다.
  - 최근 300장을 보관합니다. 캐시에서 버린 그림은 그 그림을 붙인 행에서 떼어 냅니다(`_on_thumb_evicted`). 지운 그림을 행에 남겨 두지 않기 위해서입니다.
  - 그리지 못한 쪽은 회색 칸으로 표시하고 다시 시도하지 않습니다(`_failed`).
  - 미리보기는 포커스 행(마지막으로 클릭하거나 화살표 키로 옮긴 행)을 그리며, 포커스 행이 없으면 선택한 행 중 첫 행을 그립니다. 영역 크기가 바뀌면 150ms 뒤에 다시 그립니다.
  - 목록의 요구 높이는 3행으로 둡니다(`height=3`). 기본값 10행이면 썸네일 행이 높아서 요구 높이가 창보다 커지고, 아래쪽의 저장 버튼과 진행 막대가 밀려나 보이지 않습니다.
  - 이미지 저장: 아래쪽 "새 PDF로 저장" 버튼 왼쪽의 "이미지로 저장" 버튼, "파일" 메뉴, 우클릭 메뉴(`save_images`) → `ImageSaveDialog`(본 창 가운데에 뜸. 저장할 쪽: 선택한 쪽/목록 전체, 형식, DPI 기본 150, JPG 품질 기본 90) → 폴더 선택 → 겹치는 파일이 있으면 덮어쓸지 한 번 확인 → `export_images`. 아래쪽 버튼은 메뉴를 추가한 뒤에도 남겨 둡니다(2026-11-02 사용자 결정).
  - `export_images`: 렌더링은 메인 스레드에서 한 쪽씩(`after`로 나누어) 하고, PNG/JPG 변환과 파일 쓰기는 별도 스레드에서 합니다. 그린 그림은 큐(`EXPORT_QUEUE` = 2장)로 넘겨서 메모리 사용을 제한합니다. 오류가 나면 멈추고, 변환 스레드가 쓰던 파일까지 끝난 뒤에(스레드가 끝날 때까지 20ms마다 확인) 저장한 개수를 알립니다. 그때까지는 `busy`로 다른 편집을 막습니다.
- `fit_window_size`: 기본 창 크기 1200×750을 화면 안에 들어오도록 줄입니다(가로 여백 40, 세로 여백 80픽셀).
- 렌더링은 모두 메인 스레드에서 합니다(PDFium의 스레드 제한).

실행 파일 (6단계):
- `tools/build_exe.py`: PyInstaller로 렌더링판을 폴더 형태(onedir, 창만 있고 콘솔 없음)로 묶고, `LICENSE`, `THIRD_PARTY_NOTICES.md`, `README.md`, `licenses/`(각 라이브러리의 `dist-info/licenses`, Python의 `LICENSE.txt`, Tcl/Tk의 `license.terms`)를 넣은 뒤 zip(`build/pdf-tool-<버전>-<운영체제>-<cpu>.zip`)을 만듭니다. 라이선스 문서를 찾지 못하면 실패로 끝납니다(Linux에서 시험할 때는 `--allow-missing-runtime-licenses`). Windows용 Python(python.org, GitHub Actions의 3.12.10)의 `tcl` 폴더에는 Tk의 `license.terms`만 있고 Tcl의 것은 없으며, Python의 `LICENSE.txt`에도 Tcl/Tk 라이선스 문구가 없었습니다. 그래서 Tcl 8.6.15 소스의 `license.terms`를 `tools/licenses/tcl-license.terms`에 두고 씁니다. `--copy-metadata`로 라이브러리 메타데이터를 넣어야 "프로그램 정보"의 버전이 나옵니다.
- 아이콘: `assets/icon.ico`(exe 아이콘, 16~256픽셀 7가지 크기), `assets/icon.png`(256픽셀, 창 아이콘), `assets/icon_source.png`(84픽셀 원본 조각). 사용자가 준 스프라이트 시트(1536×2288, 칸 192×208)의 첫 칸에서 (78, 44)~(140, 128)을 잘라 꼬리 부분을 지우고 아래 8픽셀을 흐리게 한 뒤 정사각형으로 맞췄습니다. 원본이 작아서 256픽셀은 약간 흐립니다. `pdf_common.set_window_icon(root)`이 양쪽 판의 `build_window`에서 창 아이콘을 정하고(`resource_path`는 실행 파일에서 `sys._MEIPASS` 기준), 파일이 없으면 기본 아이콘을 둡니다. `build_exe.py`가 `--icon`과 `--add-data`로 넣습니다.
- `pdf_selftest.py`: `pdf-tool.exe --selftest 결과파일`로 실행하는 자체 검사입니다(창 없는 실행 파일은 콘솔 출력이 없으므로 파일에 씀, 종료 코드 0/1). 라이브러리 버전, PDF/이미지 불러오기, 썸네일 렌더링, PNG/JPG 변환, PDF 저장, 창 만들기를 확인합니다. `build_exe.py`가 빌드 끝에 실행합니다. 결과 파일은 BOM이 있는 UTF-8로 씁니다(Windows PowerShell 5의 `Get-Content`가 BOM 없는 UTF-8을 CP949로 읽어 한국어가 깨졌음, 2026-11-03 사용자 확인). `pdf_tool_render.main()`이 `--selftest` 인자를 처리합니다.
- `.github/workflows/build-exe.yml`: 풀 리퀘스트와 수동 실행에서는 Windows(windows-latest, Python 3.12)에서 빌드와 자체 검사만 하고 zip을 Artifacts에 올립니다. `v*` 태그를 올리면 zip을 붙인 Release 초안을 만듭니다(설명은 `.github/release_notes.md`). 한국어 출력 때문에 `PYTHONUTF8=1`을 설정합니다.
- 빌드 도구는 `requirements-build.txt`에 버전을 고정합니다(PyInstaller 6.22.3, hooks-contrib 2026.9). Linux 컨테이너에서 빌드한 실행 파일은 약 59MB(zip 약 29MB)였고 자체 검사를 통과했습니다.

`tools/bench_render.py`: 실제 PDF로 렌더링 속도를 재는 스크립트입니다. 썸네일, 미리보기, 200/300 DPI의 렌더링, PPM 변환, Tk 이미지 생성 시간을 쪽당 평균과 최대로 출력합니다. 쪽마다 썸네일 배율로 먼저 한 번 그려서 "처음 그리기" 행에 따로 기록하므로, 나머지 행은 모두 같은 조건(이미 한 번 그린 쪽)에서 비교할 수 있습니다. 최대값이 나온 쪽 번호, 쪽 불러오기(`doc[i]`) 평균, 저장용 배율의 PNG 만들기 시간(zlib 수준 1과 6)도 출력합니다. 측정 전에 첫 파일의 첫 쪽을 따로 한 번 그려서 프로그램 시작 직후의 비용을 제외합니다.

구현 규칙:
- 테스트는 `filedialog`, `messagebox`의 함수를 tkinter 모듈 객체에서 바꿔치기합니다. 따라서 코드에서는 `messagebox.showinfo(...)`처럼 모듈을 거쳐서 호출하고, `from tkinter.messagebox import showinfo`처럼 가져오지 않습니다.
- tkinter는 메인 스레드에서만 호출합니다. 오래 걸리는 작업은 별도 스레드에서 실행하고, 결과는 큐로 전달합니다.
- `PageTab`의 각 행은 Treeview 행 ID로 식별하며, `self.pages`가 행 ID를 (PDF 경로, 0부터 시작하는 쪽 인덱스)에 대응시킵니다.
- 실행 취소는 작업 직전의 쪽 목록 `[(경로, 쪽 인덱스), ...]`을 저장하는 방식이며 최대 100단계입니다. 복원할 때는 목록을 다시 구성하고 스크롤 위치를 유지합니다. 단축키는 Ctrl+Z, Ctrl+Y, Ctrl+Shift+Z입니다.

## 결정 사항

사용자가 확정한 내용:
- 미리보기 렌더링판은 경량판과 분리합니다. 렌더링 라이브러리는 라이선스를 고려해 선택합니다.
- 쪽을 이미지(JPG, PNG)로 저장하는 기능을 원합니다. 이 기능은 렌더링 라이브러리가 필요하므로 렌더링판에 들어갑니다.
- 앞으로 UI를 확장한다면 왼쪽 상단의 메뉴 막대(VS Code처럼 파일, 편집, 도움말 등)와 우클릭 메뉴를 사용합니다. 4단계에서 메뉴 막대(파일, 편집, 도움말)와 우클릭 메뉴를 만들었습니다.
- 인쇄된 쪽 번호로 범위를 지정하는 기능은 필요하지 않습니다.
- 오른쪽 버튼 영역은 이미 충분하므로 버튼을 더 늘리지 않습니다.
- 경량판과 렌더링판은 공통 모듈(`pdf_common.py`)을 함께 사용하는 구조로 합니다. 독립된 파일 2개 방식은 사용하지 않습니다.
- 렌더링 라이브러리는 pypdfium2입니다(버전 5.14 이상, 6 미만). PyMuPDF는 AGPL 또는 상용 라이선스라서 제외했습니다. 근거는 `docs/extension_plan.md`에 있습니다.
- 렌더링판의 의존성은 `requirements-render.txt`에 따로 둡니다. `requirements.txt`는 경량판용으로 pypdf만 둡니다.
- 렌더링판 화면은 `[쪽 목록 | 미리보기] [버튼]` 순서이고, 목록과 미리보기 사이의 폭은 끌어서 조절합니다. 기본 창 크기는 1200×750이며 화면이 작으면 줄입니다.
- 썸네일 배율은 0.12에서 시작합니다. 크기 변경 기능은 4단계의 "보기 > 썸네일 크기" 메뉴에서 다룹니다.
- 미리보기는 마지막으로 클릭한 쪽을 영역에 맞게 그립니다. 확대, 축소, 쪽 안의 스크롤은 2단계에 넣지 않았습니다.
- 썸네일 캐시는 300장, 렌더링은 메인 스레드에서 나누어 처리합니다.
- 배포 계획: 저장소를 공개로 전환하고 GitHub Releases에 실행 파일을 올리며, 웹 버전도 만들 예정입니다. 라이선스와 저작권 고지는 5단계에서 정리합니다. 외부 라이브러리의 고지는 `THIRD_PARTY_NOTICES.md`에 있습니다.
- 작업 순서는 아래 "작업 순서"를 따릅니다.
- JPG 저장에 Pillow를 사용합니다(2026-10-30, "라이선스 문제가 없다면 써도 됨"). Windows용 Pillow 13.0.0 wheel의 라이선스 문서를 확인한 결과, 본체(MIT-CMU)와 함께 들어 있는 라이브러리(libjpeg-turbo, FreeType, zlib-ng 등)는 모두 허용형이고 GPL 계열 구성 요소(libimagequant, FriBiDi)는 들어 있지 않았습니다. 실행 파일을 배포할 때 Pillow의 `dist-info/licenses/LICENSE`를 함께 넣어야 합니다(5단계).
- 저장소 라이선스는 MIT, 저작권자 표기는 `drybulk`입니다(2026-11-02 확정). 아이콘도 MIT를 따르며, 그림의 출처는 따로 적지 않습니다(2026-11-03 사용자 결정). 외부 라이브러리는 모두 허용형이라 충돌하지 않습니다.
- "파일 이름으로 북마크 추가"는 기본으로 꺼 둡니다(2026-11-02 확정).
- 아래쪽 "이미지로 저장" 버튼은 메뉴가 생긴 뒤에도 남겨 둡니다(2026-11-02).
- 불러오기에서 PDF뿐 아니라 이미지 파일도 쪽으로 불러와 PDF 쪽과 섞어 저장할 수 있게 합니다(2026-11-02 요청). 쪽 크기(A4 너비 맞춤), 지원 형식, 쪽 범위는 PDF에만 적용한다는 점은 기본안으로 구현했고 사용자 확인을 기다리는 중입니다.
- 이미지 저장의 세부 사항(2026-10-30 확정): 진입은 아래쪽 버튼 하나(오른쪽 버튼 영역은 늘리지 않음), 저장할 쪽은 선택한 쪽 또는 목록 전체, DPI 기본 150, JPG 품질 1~95 입력(기본 90), 파일 이름은 원본 쪽 번호 기준이고 겹치면 `_2`, 기존 파일은 덮어쓸지 한 번 확인, Pillow가 없으면 JPG만 비활성화.

아직 결정되지 않은 내용 (작업 전에 사용자에게 확인):
- 웹 버전의 구조. tkinter는 브라우저에서 실행할 수 없으므로 화면은 새로 만들어야 합니다. 처리 로직을 얼마나 재사용할지와 브라우저에서 쓸 렌더링 방식은 아직 검토하지 않았습니다.

## 테스트

```
pip install -r requirements.txt -r requirements-dev.txt
# Linux에서는 python3-tk 와 xvfb 가 필요합니다.
xvfb-run -a python tests/test_page_tab.py
xvfb-run -a python tests/test_undo.py
xvfb-run -a python tests/test_common.py
xvfb-run -a python tests/test_menu.py   # 창 크기를 인자로 줄 수 있음 (예: 1100x600)
python tests/test_merge.py
xvfb-run -a python tests/test_image_import.py   # Pillow 필요. pypdfium2가 있으면 렌더링판도 검사

# 렌더링판 (pip install -r requirements-render.txt 필요)
xvfb-run -a python tests/test_render.py
xvfb-run -a python tests/test_image_export.py
xvfb-run -a python tests/test_selftest.py   # 실행 파일 자체 검사의 동작
```

- `test_menu.py`는 메뉴 구성, 항목 사용 가능 여부(빈 목록, 저장 중), 우클릭 선택 규칙, "이 파일의 쪽 모두 선택", 메뉴로 이동/삭제/실행 취소/저장, Ctrl+O/Ctrl+S(다른 창에서는 무시), 도움말, 종료, 메뉴 막대를 붙인 창의 화면 배치(경량판 640×460~1100×600, 렌더링판 900×560~1400×750)를 검사합니다. pypdfium2가 있으면 렌더링판의 "이미지로 저장..." 항목과 미리보기도 검사합니다.
- `test_render.py`는 PPM 변환, 썸네일 크기와 색 순서, 회전한 쪽, LRU 캐시, 창 크기 맞춤, 화면 배치, 지연 로딩, 캐시 상한, 미리보기, 경량판 기능(드래그, 실행 취소, 저장) 유지, 그리지 못한 쪽 표시를 검사합니다. pypdfium2가 없으면 안내 문구를 출력하고 끝납니다.
- 렌더링 테스트에서 쓰는 reportlab의 기본 쪽 크기는 A4(595×842pt)입니다.
- `test_image_export.py`는 RGB/PNG/JPG 변환, 파일 이름 규칙, 버튼 배치, 저장 대화 상자(기본값, 품질 검사, 취소, Pillow가 없을 때), 선택한 쪽/전체 저장, 덮어쓰기 확인, 같은 쪽 두 번, 오류 처리, 저장 중 화면 반응을 검사합니다. Pillow가 필요합니다.
- 대화 상자 위치 테스트는 Windows의 제목 표시줄과 테두리 때문에 대화 상자 가운데가 본 창 가운데보다 오른쪽 아래로 밀리므로(배율 100%에서 9, 37픽셀) 80픽셀까지 허용합니다.
- 대화 상자 테스트는 `root.after`로 `page._image_dialog`를 조작한 뒤 `ok()`/`cancel()`을 부릅니다. 검사가 실패해도 대화 상자를 닫아야 `wait_window`에서 멈추지 않습니다. 대화 상자에 키 이벤트를 보내려면 먼저 `focus_force()`가 필요합니다.
- `test_render.py`의 테스트는 Windows(행이 더 높음)와 다른 창 크기에서도 통과해야 합니다. 행을 클릭하는 `rowy`는 행 전체가 보일 때까지 스크롤한 뒤 좌표를 구합니다. 일부만 보이는 행은 `see()`가 스크롤하지 않아서 행 가운데 좌표가 목록 밖이 될 수 있기 때문입니다. 미리보기 그림은 높이에 맞춰질 수도 있으므로 크기 변화 검사는 영역을 그림보다 좁게 만들어서 합니다. 창 크기를 바꿔 가며(예: 1100×600~1400×750) 확인하면 Windows 실패를 미리 잡을 수 있습니다.
- PDFium이 그린 그림의 크기는 `쪽 크기 × 배율`을 반올림한 값과 1픽셀 다를 수 있습니다(A4 150 DPI 높이 1754.2 → 1755).
- `test_image_import.py`는 이미지 → PDF 변환(JPG 그대로 넣기, Exif 방향, 투명, 팔레트, 16비트, CMYK, BMP, WebP, 여러 쪽 TIFF, 움직이는 GIF, 손상 파일, Pillow 없음), PDF와 이미지를 섞어 불러오기(범위는 PDF에만), 순서 바꾸기, 실행 취소, 저장(쪽 크기, JPG 원본 그대로, 파일 이름 북마크), 화면 배치를 검사합니다. pypdfium2가 있으면 렌더링판의 썸네일, 미리보기, 이미지로 저장도 검사합니다.
- `test_common.py`는 `pdf_tool.py` 없이 `pdf_common.py`만 가져와서 처리 로직, `run_background`, `DragTree`를 검사하고, 마지막에 `pdf_tool.py`가 공통 모듈의 객체(`PageTab` 포함)를 그대로 사용하는지 확인합니다.
- `xvfb-run`이 없으면 `Xvfb :99 &` 실행 후 `DISPLAY=:99 python tests/test_undo.py`처럼 실행합니다.
- 화면이 있는 환경에서는 `xvfb-run` 없이 그대로 실행해도 됩니다.
- 드래그 테스트는 합성 이벤트로 수행합니다. `<ButtonPress-1>`, `<B1-Motion>`(state=0x100), `<ButtonRelease-1>` 순서이며, 좌표는 `tree.bbox(행)`로 구합니다.
- 놓는 좌표가 행의 정확한 가운데(`y + h//2`)이면 아래쪽 절반으로 판정되어 그 행 뒤에 놓입니다. 행 앞에 놓으려면 행 위쪽 가까이(`y + 2`)를 사용합니다.
- 자동 스크롤 테스트는 끄는 동안 순서가 바뀌지 않으므로, `tree.yview()`가 끝에 닿을 때까지 기다린 뒤 마우스를 놓습니다.
- 행을 옮긴 직후 0.4초 동안은 선택 색이 강조색입니다. 선택 색을 검사하려면 그 시간만큼 기다려야 합니다.

## 주의할 점 (확인된 사항)

- `ttk.Treeview.set(행, 열)`은 값의 원래 타입을 반환합니다. "새 순서" 열은 int, "원본 쪽" 열은 str입니다. 비교할 때 타입을 맞춰야 합니다.
- Tk의 `Command` 수정자 키 바인딩은 macOS에서만 등록합니다. 다른 운영체제에서 등록하면 NumLock 상태와 충돌할 가능성이 있습니다. Windows에서 실제로 재현해 보지는 않았습니다.
- 단축키는 `bind_all(..., add="+")`로 등록하고 `winfo_ismapped()`로 현재 탭일 때만 처리합니다. 입력 칸(Entry)에서는 기본 동작을 유지합니다.
- 열 머리글 클릭과 열 크기 조절은 Treeview의 기본 동작에 맡기며, 행 클릭만 `DragTree`가 처리합니다.
- 드래그 중 자동 스크롤 속도는 마우스가 목록 밖으로 벗어난 거리 10픽셀마다 한 칸씩 늘어납니다(30ms 주기).
- `identify_row(y)`는 목록 아래 바깥 좌표에서 화면에 보이지 않는 행을 돌려줄 수 있고, 그 행의 `bbox`는 빈 값입니다. `bbox` 결과를 분해하기 전에 비어 있는지 확인해야 합니다.
- 맨 아래까지 스크롤하면 마지막 행 아래에 행 높이보다 작은 빈 공간이 남을 수 있습니다. 그 공간의 좌표에서는 `identify_row`가 빈 문자열을 돌려줍니다. 빈 공간의 크기는 창 높이와 운영체제의 행 높이에 따라 달라집니다(Windows에서 확인).
- Xvfb에는 창 관리자가 없으므로 테스트에서 단축키 이벤트를 보내기 전에 `focus_force()`가 필요합니다.

## 렌더링판 설계 근거 (측정과 조사 결과)

- pypdfium2 5.14.0에서 확인한 사항: `page.render(scale=..., rev_byteorder=True)`는 RGB 순서의 3채널 비트맵을 돌려줍니다. 쪽에 회전(/Rotate)이 있으면 `page.get_size()`와 그린 그림 모두 회전이 반영된 크기입니다. 비트맵의 `buffer`는 ctypes 배열이므로 자를 때는 `memoryview`로 감쌉니다(그대로 자르면 정수 리스트가 되어 느립니다).
- 측정 스크립트에서 큰 데이터(300 DPI PPM 약 26MB)를 측정 구간 안에서 해제하면 해제 시간이 다음 측정에 섞입니다. 측정 구간 밖에서 해제해야 합니다.
- PDFium은 스레드 안전하지 않습니다. 렌더링은 메인 스레드에서 몇 행씩 나누어 처리하거나 PDFium 호출을 잠금으로 직렬화해야 합니다.
- pypdfium2 5.14.0 재측정(Linux 컨테이너, Xeon 2.8GHz 4코어, Python 3.12.3, 합성 PDF 200쪽): 쪽당 평균 렌더링 시간은 썸네일(배율 0.12) 7.0ms, 화면 미리보기(배율 1.0) 9.7ms, 200 DPI 23.5ms, 300 DPI 41.5ms였습니다. Tk 이미지 생성은 썸네일 0.2ms, 미리보기 7.0ms였습니다. 자세한 표는 `docs/extension_plan.md` 5-1에 있습니다.
- 최초 측정(pypdfium2 5.6.0, 다른 컴퓨터)은 썸네일(배율 0.25) 10.7ms, 미리보기 15.2ms, 200 DPI 37.6ms, 300 DPI 56.1ms였습니다. 측정한 컴퓨터가 달라서 두 결과를 버전 차이로 비교할 수 없습니다.
- 두 측정 모두 합성 PDF 기준입니다. 고해상도 스캔본은 더 느릴 수 있으며, 사용자가 실제 PDF로 Windows에서 측정할 예정입니다.
- 렌더링 결과를 PPM(P6) 형식으로 만들어 `tk.PhotoImage(data=..., format="PPM")`에 넘기면 Pillow 없이 표시할 수 있습니다.
- 표준 라이브러리 `zlib`으로 작성한 PNG는 Pillow로 변환한 결과와 픽셀 단위로 같았습니다. JPG 저장에는 Pillow가 필요합니다.
- 비트맵의 행 간격(stride)이 너비×3과 같다고 가정하지 말고, 행 단위로 잘라서 복사합니다.
- 배포할 때는 PDFium과 그 구성 요소의 라이선스 문서를 함께 제공해야 합니다. pypdfium2 배포본의 `dist-info/licenses`에 문서가 들어 있습니다.

## 작업 순서 (안)

1. 공통 모듈 분리. 경량판이 기존과 동일하게 동작하는지 회귀 테스트로 확인 (작은 작업, 완료)
2. 렌더링판: 큰 미리보기와 썸네일 목록. 지연 로딩과 캐시 (큰 작업, 완료)
3. 이미지 저장: 쪽 범위, DPI(72, 150, 200, 300), 형식(PNG, JPG), 파일명 규칙 (중간 작업, 완료)
4. 메뉴 막대와 우클릭 메뉴 (양쪽 판 공통, 중간 작업, 완료). "보기" 메뉴(썸네일 크기, 미리보기 표시 여부)는 만들지 않고 5단계로 넘어갔습니다(2026-11-02 사용자 결정).
5. 공개 배포 준비: 저장소 라이선스(MIT), 제3자 라이브러리 고지(`THIRD_PARTY_NOTICES.md`), 문서 정리 (완료, PR #12). 저장소 공개 전환은 실행 파일 준비가 끝난 뒤에 하기로 했습니다(2026-11-03 사용자 결정).
6. GitHub Releases에 실행 파일 배포 (`THIRD_PARTY_NOTICES.md`의 "실행 파일로 배포할 때 지켜야 할 사항"을 따름, 진행 중). 방식: PyInstaller, 렌더링판만, 폴더를 zip으로, GitHub Actions에서 빌드, 첫 버전 `v0.1.0`(2026-11-03 사용자 승인, PyInstaller 사용 포함).
7. 웹 버전 (구조는 아직 정하지 않음)

## 참고 문서

- `docs/extension_plan.md`: 라이브러리 비교, 라이선스, 구조 계획, 메뉴 계획, 출처
- `THIRD_PARTY_NOTICES.md`: 외부 라이브러리의 라이선스와 실행 파일 배포 시 지켜야 할 사항
