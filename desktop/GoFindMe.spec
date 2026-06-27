# -*- mode: python ; coding: utf-8 -*-
# Build (from the repo root):  pyinstaller desktop/GoFindMe.spec
import os
import sys

from PyInstaller.utils.hooks import collect_all, collect_submodules

# SPECPATH is the directory of this spec (…/desktop); ROOT is the repo root.
ROOT = os.path.abspath(os.path.join(SPECPATH, os.pardir))
sys.path.insert(0, ROOT)

datas = [
    (os.path.join(ROOT, 'static'), 'static'),
    (os.path.join(ROOT, 'legacy'), 'legacy'),
    (os.path.join(ROOT, 'app', 'schema.sql'), 'app'),
]
binaries = []
hiddenimports = collect_submodules('app')

for pkg in ['uvicorn', 'fastapi', 'starlette', 'pydantic', 'pydantic_core',
            'anyio', 'sniffio', 'h11', 'httpx', 'httpcore', 'certifi',
            'passlib', 'argon2', 'cryptography', 'multipart', 'click']:
    try:
        d, b, h = collect_all(pkg)
        datas += d
        binaries += b
        hiddenimports += h
    except Exception:
        pass

# uvicorn imports its protocol/loop/lifespan backends lazily.
hiddenimports += [
    'uvicorn.loops.auto', 'uvicorn.loops.asyncio',
    'uvicorn.protocols.http.auto', 'uvicorn.protocols.http.h11_impl',
    'uvicorn.protocols.websockets.auto',
    'uvicorn.lifespan.on', 'uvicorn.lifespan.off',
]

a = Analysis(
    [os.path.join(ROOT, 'desktop', 'launcher.py')],
    pathex=[ROOT],
    binaries=binaries,
    datas=datas,
    hiddenimports=hiddenimports,
    hookspath=[],
    runtime_hooks=[],
    excludes=[],
    noarchive=False,
)
pyz = PYZ(a.pure)
exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.datas,
    [],
    name='GoFindMe',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    console=True,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
)
