# LocalScribe sidecar packaging

Build the FastAPI sidecar as a standalone binary:

    pip install -e ".[api,packaging]"
    pyinstaller packaging/localscribe-sidecar.spec --clean

Output: `dist/localscribe-sidecar` (Linux/macOS) or `dist/localscribe-sidecar.exe` (Windows).

Note: pyannote + torch are heavy. Expect 600–900 MB.
Run a smoke test:

    ./dist/localscribe-sidecar &
    curl http://127.0.0.1:<port>/health    # port comes from the JSON handshake
