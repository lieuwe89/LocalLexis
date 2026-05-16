# PyInstaller spec for the LocalScribe FastAPI sidecar.
# Build:   pyinstaller packaging/localscribe-sidecar.spec --clean
# Output:  dist/localscribe-sidecar (or .exe on Windows)
# The Tauri shell ships this binary alongside the app.
from PyInstaller.utils.hooks import collect_data_files

a = Analysis(
    ['../speechtotext/api/__main__.py'],
    pathex=[],
    binaries=[],
    datas=collect_data_files('pyannote.audio'),  # includes telemetry/config.yaml and other data files
    hiddenimports=[
        'speechtotext.asr.faster_whisper',
        'speechtotext.diarize.pyannote',
        'uvicorn.logging',
    ],
    hookspath=[],
    excludes=['matplotlib', 'tkinter'],
    noarchive=False,
)
pyz = PYZ(a.pure)
exe = EXE(
    pyz, a.scripts, a.binaries, a.datas,
    name='localscribe-sidecar',
    debug=False,
    strip=False,
    upx=False,
    console=True,
)
