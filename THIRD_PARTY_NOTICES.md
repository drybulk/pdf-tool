# 제3자 라이브러리 고지

이 프로그램 자체의 라이선스는 MIT입니다(`LICENSE`). 아래 라이브러리에는 각자의 라이선스가 적용됩니다.

데스크톱판은 아래의 외부 라이브러리를 사용합니다. 저장소에는 이 라이브러리들의 코드가 들어 있지 않으며, 사용자가 `pip install`로 직접 설치합니다. 각 라이브러리의 저작권과 라이선스는 그 라이브러리의 저작자에게 있습니다.

| 라이브러리 | 사용하는 판 | 라이선스 | 저작권 표기 (라이선스 파일 기준) | 출처 |
|---|---|---|---|---|
| pypdf | 경량판, 렌더링판 | BSD-3-Clause | Copyright (c) 2006-2008, Mathieu Fenniak 외 기여자 | https://github.com/py-pdf/pypdf |
| Pillow | 렌더링판(JPG 저장), 양쪽 판의 이미지 불러오기(선택) | MIT-CMU | Copyright © 1997-2011 by Secret Labs AB, Copyright © 1995-2011 by Fredrik Lundh and contributors, Copyright © 2010 by Jeffrey 'Alex' Clark and contributors | https://github.com/python-pillow/Pillow |
| pypdfium2 | 렌더링판 | Apache-2.0 또는 BSD-3-Clause 중 선택, 그리고 함께 들어 있는 구성 요소의 라이선스 | pypdfium2 기여자 | https://github.com/pypdfium2-team/pypdfium2 |
| PDFium (pypdfium2에 포함) | 렌더링판 | BSD-3-Clause | Copyright 2014 The PDFium Authors | https://pdfium.googlesource.com/pdfium/ |

테스트에만 쓰는 reportlab(테스트용 PDF 생성)은 프로그램과 함께 배포하지 않으므로 이 표에 넣지 않았습니다.

AGPL-3.0 라이선스인 PyMuPDF는 사용하지 않습니다. 선택 근거는 `docs/extension_plan.md`에 있습니다.

## 라이브러리 안에 함께 들어 있는 구성 요소

pip으로 설치하는 배포본(wheel)에는 라이브러리 본체 외에 C 라이브러리가 함께 들어 있습니다. 아래 목록은 이 문서를 작성할 때 확인한 배포본 기준이며, 버전이나 운영체제가 다르면 구성이 달라질 수 있습니다.

- Pillow (Windows용 13.0.0 cp312 win_amd64, 2026-10-30 확인): libjpeg-turbo, FreeType, zlib-ng, libpng, libtiff, libwebp, OpenJPEG, libavif, Little CMS 2, HarfBuzz, raqm, brotli, liblzma. 모두 허용형 라이선스입니다. GPL-3.0인 libimagequant는 링크되어 있지 않았고, LGPL인 FriBiDi는 배포본에 들어 있지 않습니다.
- pypdfium2 (Linux용 5.13.0 x86_64, 2026-11-02 확인): PDFium과 함께 abseil, agg23, fast_float, FreeType, ICU, Little CMS, libjpeg-turbo, OpenJPEG, libpng, libtiff, llvm-libc, simdutf, zlib의 라이선스 문서가 들어 있습니다. Windows용 배포본의 구성은 실행 파일을 만드는 단계에서 다시 확인합니다.

각 구성 요소의 라이선스 전문은 설치된 패키지의 `*.dist-info/licenses/` 폴더에 있습니다.

## 실행 파일로 배포할 때 지켜야 할 사항

라이브러리를 실행 파일(exe) 안에 묶어서 배포하면, 라이브러리의 코드를 함께 배포하는 것이 됩니다. 이때는 다음을 지켜야 합니다. `tools/build_exe.py`는 1번의 문서를 실행 폴더의 `licenses/`에 복사하고, 문서를 찾지 못하면 빌드를 실패로 끝냅니다. 2번의 문장은 이 문서와 Release 설명(`.github/release_notes.md`)에 들어 있습니다.

1. 실행 파일과 함께 아래 라이선스 문서를 넣습니다.
   - pypdf: `pypdf-*.dist-info/licenses/LICENSE`
   - Pillow: `pillow-*.dist-info/licenses/LICENSE` (Pillow에 들어 있는 모든 구성 요소의 고지문이 이 파일 하나에 들어 있습니다)
   - pypdfium2: `pypdfium2-*.dist-info/licenses/` 폴더 전체 (`LICENSES/`와 운영체제별 `BUILD_LICENSES/`)
   - 실행 파일에 함께 묶이는 Python 자체(PSF 라이선스)와 Tcl/Tk의 라이선스 문서. Windows용 Python에는 Tcl의 `license.terms`가 없어서, Tcl 8.6.15 소스의 문서를 `tools/licenses/tcl-license.terms`에 두고 씁니다.
2. 배포 문서에 아래 문장을 적습니다. libjpeg-turbo(IJG 라이선스)와 FreeType(FTL)의 라이선스가 요구하는 문장이며, Pillow와 PDFium이 모두 이 두 라이브러리를 포함합니다.

> This software is based in part on the work of the Independent JPEG Group.
>
> Portions of this software are copyright © 2026 The FreeType Project (www.freetype.org). All rights reserved.

FreeType 문장의 연도는 FreeType 라이선스의 안내에 따라 배포하는 해로 적습니다.

## 웹판 (`web/`)

웹판은 데스크톱판과 달리 라이브러리 파일을 저장소의 `web/vendor/`에 함께 둡니다. 웹 페이지로 올리면 이 파일들을 함께 배포하게 되므로, 각 라이브러리의 라이선스 문서를 같은 폴더에 두었습니다.

| 라이브러리 | 판 | 라이선스 | 저작권 표기 | 출처 | 라이선스 문서 |
|---|---|---|---|---|---|
| pdf.js (`pdfjs-dist`) | 6.5.438 | Apache-2.0 | Mozilla Foundation | https://github.com/mozilla/pdf.js | `web/vendor/pdfjs/LICENSE` |
| pdf-lib (`@cantoo/pdf-lib`, 원래 pdf-lib의 관리되는 갈래) | 2.11.1 | MIT | Copyright (c) 2019 Andrew Dillon | https://github.com/cantoo-scribe/pdf-lib | `web/vendor/pdf-lib/LICENSE.md` |

함께 들어 있는 구성 요소:

- pdf.js의 데이터 파일
  - `cmaps/`: Adobe의 CMap 자료(BSD 형식의 허용형 라이선스, Copyright 1990-2009 Adobe Systems Incorporated). 문서: `web/vendor/pdfjs/cmaps/LICENSE`
  - `standard_fonts/`: Foxit 글꼴(PDFium, BSD-3-Clause). 문서: `standard_fonts/LICENSE_FOXIT`. pdf.js 배포본에 있는 Liberation 글꼴은 GPL-2.0(글꼴 예외 조항 포함)이라서 넣지 않았습니다.
  - `wasm/`: JBIG2 디코더(PDFium, BSD-3-Clause, 그리고 pdf.js 부분은 Apache-2.0), OpenJPEG 디코더(BSD-2-Clause), qcms 색 관리(MIT). 문서: `wasm/LICENSE_*`. pdf.js의 문서 스크립트 실행용 QuickJS는 쓰지 않으므로 넣지 않았습니다.
  - `iccs/`: ICC 색 프로파일(CC0-1.0). 문서: `iccs/LICENSE`
- pdf-lib의 `pdf-lib.esm.min.js`에 함께 묶여 있는 라이브러리: fflate(MIT), culori(MIT), node-html-better-parser(MIT), tslib(0BSD). 각 라이브러리의 버전은 npm 레지스트리의 의존성 범위 기준이며, 묶인 정확한 판은 확인하지 않았습니다.

웹판 테스트에만 쓰는 Playwright(Apache-2.0)는 배포하지 않으므로 표에 넣지 않았습니다.

Chrome 확장(`tools/build_extension.py`로 만듦)은 웹판의 파일을 그대로 담으므로 위의 라이브러리와 라이선스 문서가 같은 위치(`vendor/`)에 함께 들어갑니다. 저장소의 `LICENSE`와 이 문서도 확장의 맨 위 폴더에 넣습니다. 확장에만 쓰는 외부 라이브러리는 없습니다.

## 프로그램 아이콘

`assets/icon.ico`, `assets/icon.png`, `assets/icon_source.png`는 저장소 관리자가 제공한 그림으로 만들었으며, 이 저장소의 다른 파일과 같이 MIT 라이선스를 따릅니다.

## 빌드에만 쓰는 도구

실행 파일은 PyInstaller(GPL-2.0 이상, 만든 실행 파일은 어떤 라이선스로든 배포할 수 있다는 예외 조항 포함)로 만듭니다. PyInstaller는 프로그램이 사용하는 라이브러리가 아니므로 위의 표에 넣지 않았습니다.
