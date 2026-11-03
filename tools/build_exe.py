"""렌더링판(pdf_tool_render.py)을 PyInstaller로 묶어서 배포용 zip을 만듭니다.

사용법 (저장소 맨 위 폴더에서):
    pip install -r requirements-render.txt -r requirements-build.txt
    python tools/build_exe.py --version v0.1.0

결과:
    build/dist/pdf-tool/            실행 폴더 (pdf-tool.exe 와 _internal 폴더)
    build/pdf-tool-<버전>-<운영체제>.zip

실행 폴더에는 프로그램의 LICENSE, THIRD_PARTY_NOTICES.md, README.md와
licenses/ 폴더(외부 라이브러리, Python, Tcl/Tk의 라이선스 문서)를 함께 넣습니다.
라이선스 문서를 찾지 못하면 빌드를 실패로 끝냅니다(배포 조건을 지키기 위해).
마지막으로 만든 실행 파일을 --selftest로 실행해서(pdf_selftest.py) 구성 요소가 모두 들어갔는지 확인합니다.
Linux에서는 화면이 필요하므로 xvfb-run으로 실행합니다.
"""

import argparse
import importlib.metadata
import os
import platform
import shutil
import subprocess
import sys
import sysconfig
import tkinter
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
BUILD = ROOT / "build"
NAME = "pdf-tool"
ENTRY = ROOT / "pdf_tool_render.py"
# 실행 파일에 들어가는 외부 라이브러리 (배포 이름)
DISTRIBUTIONS = ("pypdf", "pillow", "pypdfium2")
# 실행 폴더에 그대로 복사하는 저장소 문서
DOCS = ("LICENSE", "THIRD_PARTY_NOTICES.md", "README.md")
# Tcl의 라이선스 문서. https://raw.githubusercontent.com/tcltk/tcl/core-8-6-15/license.terms 를 그대로 복사함
TCL_LICENSE = ROOT / "tools" / "licenses" / "tcl-license.terms"


def fail(message):
    print("오류: " + message, file=sys.stderr)
    sys.exit(1)


def run_pyinstaller():
    import PyInstaller.__main__

    args = [
        str(ENTRY),
        "--name", NAME,
        "--onedir",
        "--windowed",
        "--noconfirm",
        "--clean",
        "--distpath", str(BUILD / "dist"),
        "--workpath", str(BUILD / "work"),
        "--specpath", str(BUILD),
        # 테스트용 라이브러리가 설치되어 있어도 넣지 않습니다.
        "--exclude-module", "reportlab",
    ]
    # "도움말 > 프로그램 정보"가 importlib.metadata로 버전을 읽으므로 메타데이터를 넣습니다.
    for name in DISTRIBUTIONS:
        args += ["--copy-metadata", name]
    PyInstaller.__main__.run(args)


def copy_library_licenses(dest):
    """각 라이브러리의 dist-info/licenses 아래 파일을 licenses/<이름>/ 으로 복사합니다."""
    for name in DISTRIBUTIONS:
        try:
            dist = importlib.metadata.distribution(name)
        except importlib.metadata.PackageNotFoundError:
            fail(f"{name}이(가) 설치되어 있지 않습니다.")
        copied = 0
        for item in dist.files or ():
            parts = Path(item).parts
            if len(parts) < 3 or not parts[0].endswith(".dist-info") or parts[1] != "licenses":
                continue
            src = Path(dist.locate_file(item))
            target = dest / name / Path(*parts[2:])
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(src, target)
            copied += 1
        if not copied:
            fail(f"{name} {dist.version}의 라이선스 문서(dist-info/licenses)를 찾지 못했습니다.")
        print(f"  {name} {dist.version}: 라이선스 문서 {copied}개")


def python_license():
    candidates = [
        Path(sys.base_prefix) / "LICENSE.txt",  # Windows (python.org 설치본)
        Path(sysconfig.get_paths()["stdlib"]) / "LICENSE.txt",  # Linux, macOS
    ]
    for path in candidates:
        if path.is_file():
            return path
    return None


def tcl_tk_licenses():
    """Tcl과 Tk의 license.terms를 찾습니다. 없으면 빈 목록을 돌려줍니다."""
    interp = tkinter.Tcl()
    found = []
    library = Path(interp.eval("set tcl_library"))
    tcl_candidates = [library / "license.terms", library.parent / "license.terms"]
    tcl_candidates += sorted(library.parent.glob("tcl*/license.terms"))
    for path in tcl_candidates:
        if path.is_file():
            found.append(("tcl", path))
            break
    # tk 라이브러리 폴더는 tcl 라이브러리 폴더와 같은 곳에 있습니다 (예: tcl/tk8.6).
    for folder in sorted(library.parent.glob("tk*")):
        path = folder / "license.terms"
        if path.is_file():
            found.append(("tk", path))
            break
    return found


def copy_runtime_licenses(dest, allow_missing):
    dest.mkdir(parents=True, exist_ok=True)
    py = python_license()
    if py is None:
        if not allow_missing:
            fail("Python의 LICENSE.txt를 찾지 못했습니다.")
        print("  경고: Python의 LICENSE.txt를 찾지 못했습니다.")
    else:
        shutil.copy2(py, dest / "Python-LICENSE.txt")
        print(f"  Python {platform.python_version()}: {py}")

    tcl = tcl_tk_licenses()
    for kind, path in tcl:
        shutil.copy2(path, dest / f"{kind}-license.terms")
        print(f"  {kind}: {path}")
    kinds = {kind for kind, _ in tcl}
    if "tcl" not in kinds:
        # Windows용 Python(python.org 설치본)의 tcl 폴더에는 Tk의 license.terms만 있고 Tcl의 것은 없습니다
        # (GitHub Actions의 Python 3.12.10에서 확인). Tcl 8.6.15 소스의 license.terms를 저장소에 두고 씁니다.
        shutil.copy2(TCL_LICENSE, dest / "tcl-license.terms")
        print(f"  tcl: {TCL_LICENSE.relative_to(ROOT)} (Tcl 8.6.15 소스의 license.terms)")
    if "tk" not in kinds:
        if not allow_missing:
            fail("Tk의 라이선스 문서(license.terms)를 찾지 못했습니다.")
        print("  경고: Tk의 라이선스 문서를 찾지 못했습니다.")


def check_bundle(app):
    """실행 폴더에 꼭 있어야 할 파일을 확인합니다."""
    internal = app / "_internal"
    exe = app / (NAME + (".exe" if sys.platform == "win32" else ""))
    if not exe.is_file():
        fail(f"실행 파일이 없습니다: {exe}")
    pdfium = [p for p in internal.rglob("*pdfium*") if p.suffix in (".dll", ".so", ".dylib")]
    if not pdfium:
        fail("PDFium 라이브러리가 실행 폴더에 들어가지 않았습니다.")
    for name in DISTRIBUTIONS:
        if not any(internal.glob(f"{name}-*.dist-info")):
            fail(f"{name}의 메타데이터가 실행 폴더에 들어가지 않았습니다.")
    if not any(internal.rglob("init.tcl")):
        fail("Tcl 데이터가 실행 폴더에 들어가지 않았습니다.")
    print(f"  확인: {exe.name}, {pdfium[0].name}, 메타데이터 {len(DISTRIBUTIONS)}개, Tcl 데이터")


def run_selftest(app):
    """만든 실행 파일을 --selftest로 실행해서 PDFium, Pillow, Tcl/Tk가 동작하는지 확인합니다."""
    exe = app / (NAME + (".exe" if sys.platform == "win32" else ""))
    result = BUILD / "selftest.txt"
    if result.exists():
        result.unlink()
    try:
        code = subprocess.run([str(exe), "--selftest", str(result)], timeout=120).returncode
    except subprocess.TimeoutExpired:
        fail("자체 검사가 120초 안에 끝나지 않았습니다.")
    text = result.read_text(encoding="utf-8-sig") if result.exists() else "(결과 파일 없음)\n"
    print("자체 검사 결과:\n" + text, end="")
    if code != 0:
        fail(f"자체 검사에 실패했습니다 (종료 코드 {code}).")


def make_zip(app, version):
    system = {"win32": "windows", "darwin": "macos"}.get(sys.platform, sys.platform)
    machine = platform.machine().lower().replace("amd64", "x64").replace("x86_64", "x64")
    archive = BUILD / f"{NAME}-{version}-{system}-{machine}.zip"
    if archive.exists():
        archive.unlink()
    with zipfile.ZipFile(archive, "w", zipfile.ZIP_DEFLATED) as zf:
        for path in sorted(app.rglob("*")):
            if path.is_file():
                zf.write(path, Path(NAME) / path.relative_to(app))
    print(f"zip: {archive} ({archive.stat().st_size / 1e6:.1f} MB)")
    return archive


def app_version():
    """pdf_common.APP_VERSION을 읽습니다 (프로그램 정보에 표시되는 버전)."""
    sys.path.insert(0, str(ROOT))
    from pdf_common import APP_VERSION
    return APP_VERSION


def main():
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--version", default=os.environ.get("GITHUB_REF_NAME", "dev"),
                        help="zip 파일 이름에 넣을 버전 (기본: 태그 이름 또는 dev). v로 시작하면 APP_VERSION과 같아야 함")
    parser.add_argument("--allow-missing-runtime-licenses", action="store_true",
                        help="Python, Tcl/Tk의 라이선스 문서가 없어도 계속합니다 (시험 빌드용)")
    parser.add_argument("--skip-selftest", action="store_true",
                        help="만든 실행 파일의 자체 검사(--selftest)를 건너뜁니다")
    args = parser.parse_args()
    version = args.version.replace("/", "-")
    # 릴리스용 버전(v로 시작)은 프로그램 정보에 표시되는 버전과 같아야 합니다.
    expected = "v" + app_version()
    if version.startswith("v") and version != expected:
        fail(f"버전 {version}이(가) pdf_common.APP_VERSION({expected})과 다릅니다. "
             "pdf_common.py의 APP_VERSION을 먼저 바꾸거나 태그 이름을 고칩니다.")

    run_pyinstaller()
    app = BUILD / "dist" / NAME
    print("문서와 라이선스 복사:")
    for doc in DOCS:
        shutil.copy2(ROOT / doc, app / doc)
    copy_library_licenses(app / "licenses")
    copy_runtime_licenses(app / "licenses", args.allow_missing_runtime_licenses)
    check_bundle(app)
    if not args.skip_selftest:
        run_selftest(app)
    make_zip(app, version)


if __name__ == "__main__":
    main()
