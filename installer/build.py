"""Build the Windows installer: dist/METATRON-Setup-<version>.exe

    .venv/Scripts/python installer/build.py [--skip-web] [--no-installer]

Steps:
1. build the dashboard (web/ -> src/metatron/product/web);
2. assemble build/app/ = a private Python runtime with the product's packages, the WhatsApp
   gateway with its node_modules, node.exe and the default config;
3. compile installer/metatron.iss with Inno Setup (ISCC.exe).

The app folder is self-contained: nothing is installed system-wide and no admin rights are
needed. Run build/app/python/python.exe -m metatron.product.launcher to try it before packaging.
"""

from __future__ import annotations

import argparse
import os
import shutil
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
BUILD = ROOT / "build" / "app"
VERSION = "1.1.0"

# What the installed product needs (the course's training stack - pandas, scikit-learn,
# matplotlib - is not shipped: the product does not train models).
PRODUCT_DEPS = ["crewai==1.15.33", "fastapi", "uvicorn", "httpx", "python-multipart", "openpyxl",
                "pyyaml", "python-dotenv", "pystray", "pillow"]


def run(cmd: list[str], **kw) -> None:
    print("  $", " ".join(str(c) for c in cmd))
    subprocess.run(cmd, check=True, **kw)


def npm() -> str:
    return shutil.which("npm.cmd") or shutil.which("npm") or "npm"


def build_web() -> None:
    print("1/3 dashboard")
    run([npm(), "ci" if (ROOT / "web" / "package-lock.json").exists() else "install"], cwd=ROOT / "web")
    run([npm(), "run", "build"], cwd=ROOT / "web")


def assemble() -> None:
    print("2/3 app folder")
    if BUILD.exists():
        shutil.rmtree(BUILD)
    base = Path(sys.base_prefix)
    skip = {"site-packages", "test", "idlelib", "tkinter", "turtledemo", "__pycache__", "ensurepip"}
    shutil.copytree(base, BUILD / "python", ignore=lambda d, names: [
        n for n in names if n in skip or n in {"Doc", "include", "Scripts", "tcl", "Tools", "libs"}])
    site = BUILD / "python" / "Lib" / "site-packages"
    site.mkdir(parents=True, exist_ok=True)
    pip = [sys.executable, "-m", "pip", "install", "--target", str(site), "--no-warn-script-location",
           "--disable-pip-version-check", "--upgrade"]
    run(pip + PRODUCT_DEPS)
    run(pip + ["--no-deps", str(ROOT)])
    # data files that pip does not pick up from a source tree
    shutil.copy2(ROOT / "config.yaml", site / "metatron" / "config.yaml")
    web = ROOT / "src" / "metatron" / "product" / "web"
    if not (web / "index.html").exists():
        raise SystemExit("dashboard not built: run without --skip-web")
    shutil.copytree(web, site / "metatron" / "product" / "web", dirs_exist_ok=True)

    gw = BUILD / "gateway"
    gw.mkdir()
    for f in ("index.js", "package.json", "package-lock.json"):
        shutil.copy2(ROOT / "gateway" / f, gw / f)
    run([npm(), "ci", "--omit=dev"], cwd=gw)
    node = Path(shutil.which("node") or "")
    (BUILD / "node").mkdir()
    shutil.copy2(node, BUILD / "node" / "node.exe")
    shutil.copy2(ROOT / "installer" / "metatron.ico", BUILD / "metatron.ico")
    size = sum(f.stat().st_size for f in BUILD.rglob("*") if f.is_file()) / 1e6
    print(f"   app folder: {size:.0f} MB")


def iscc() -> Path:
    for base in (os.getenv("LOCALAPPDATA", ""), os.getenv("ProgramFiles(x86)", ""),
                 os.getenv("ProgramFiles", "")):
        sub = "Programs" if base == os.getenv("LOCALAPPDATA") else ""
        p = Path(base) / sub / "Inno Setup 6" / "ISCC.exe"
        if p.exists():
            return p
    raise FileNotFoundError("Inno Setup 6 not found: winget install JRSoftware.InnoSetup")


def installer() -> None:
    print("3/3 installer")
    (ROOT / "dist").mkdir(exist_ok=True)
    run([str(iscc()), f"/DAppVersion={VERSION}", f"/DBuildDir={BUILD}", f"/DOutDir={ROOT / 'dist'}",
         str(ROOT / "installer" / "metatron.iss")])


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--skip-web", action="store_true")
    ap.add_argument("--no-installer", action="store_true")
    a = ap.parse_args()
    if not a.skip_web:
        build_web()
    assemble()
    if not a.no_installer:
        installer()
    print("done")
