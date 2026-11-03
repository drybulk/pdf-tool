"""
웹판(web/)을 Chrome 확장으로 묶습니다. 외부 라이브러리 없이 Python 표준 라이브러리만 씁니다.

결과:
- build/extension/: Chrome의 "압축해제된 확장 프로그램을 로드합니다"로 바로 설치할 수 있는 폴더
- build/pdf-tool-extension-<버전>.zip: Chrome 웹 스토어에 올릴 때 쓰는 zip (위 폴더와 같은 내용)

확장의 버전은 pdf_common.APP_VERSION을 씁니다. web/js/version.js의 값이 다르면 멈춥니다.
실행: python tools/build_extension.py
"""
import json
import os
import re
import shutil
import sys
import zipfile

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
WEB = os.path.join(ROOT, "web")
EXT = os.path.join(ROOT, "extension")
BUILD = os.path.join(ROOT, "build")
OUT = os.path.join(BUILD, "extension")

# web/에서 확장에 넣지 않는 파일 (설명 문서)
SKIP_WEB = {"README.md"}
# 저장소에서 함께 넣는 문서 (라이선스와 제3자 고지)
DOCS = ["LICENSE", "THIRD_PARTY_NOTICES.md"]


def read_version(path, pattern):
    with open(path, encoding="utf-8") as f:
        m = re.search(pattern, f.read(), re.M)
    if not m:
        sys.exit(f"버전을 찾지 못했습니다: {path}")
    return m.group(1)


def main():
    version = read_version(os.path.join(ROOT, "pdf_common.py"), r'^APP_VERSION = "([^"]+)"')
    web_version = read_version(os.path.join(WEB, "js", "version.js"), r'^export const APP_VERSION = "([^"]+)"')
    if version != web_version:
        sys.exit(f"web/js/version.js의 APP_VERSION({web_version})이 pdf_common.APP_VERSION({version})과 다릅니다.")
    # Chrome 확장의 버전은 점으로 나눈 1~4개의 정수(각 0~65535)만 쓸 수 있음
    if not re.fullmatch(r"\d{1,5}(\.\d{1,5}){0,3}", version) or any(int(x) > 65535 for x in version.split(".")):
        sys.exit(f"Chrome 확장의 버전으로 쓸 수 없는 값입니다: {version}")

    if os.path.exists(OUT):
        shutil.rmtree(OUT)
    shutil.copytree(WEB, OUT, ignore=lambda d, names: [n for n in names if d == WEB and n in SKIP_WEB])
    shutil.copy2(os.path.join(EXT, "background.js"), OUT)
    shutil.copytree(os.path.join(EXT, "icons"), os.path.join(OUT, "icons"))
    for name in DOCS:
        shutil.copy2(os.path.join(ROOT, name), OUT)
    with open(os.path.join(EXT, "manifest.json"), encoding="utf-8") as f:
        manifest = json.load(f)
    manifest["version"] = version
    with open(os.path.join(OUT, "manifest.json"), "w", encoding="utf-8", newline="\n") as f:
        json.dump(manifest, f, ensure_ascii=False, indent=2)
        f.write("\n")

    zip_path = os.path.join(BUILD, f"pdf-tool-extension-{version}.zip")
    files = []
    with zipfile.ZipFile(zip_path, "w", zipfile.ZIP_DEFLATED) as z:
        for d, dirs, names in os.walk(OUT):
            dirs.sort()
            for n in sorted(names):
                full = os.path.join(d, n)
                arc = os.path.relpath(full, OUT).replace(os.sep, "/")
                z.write(full, arc)
                files.append(arc)
    size = os.path.getsize(zip_path)
    print(f"확장 폴더: {OUT}")
    print(f"스토어용 zip: {zip_path} ({len(files)}개 파일, {size / 1024 / 1024:.1f}MB)")
    print("설치: Chrome 주소창에 chrome://extensions 입력 → 오른쪽 위 '개발자 모드' 켜기 → "
          "'압축해제된 확장 프로그램을 로드합니다' → 위 확장 폴더 선택")


if __name__ == "__main__":
    main()
