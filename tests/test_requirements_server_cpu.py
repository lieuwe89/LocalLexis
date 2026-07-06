from pathlib import Path

REQ = Path(__file__).resolve().parent.parent / "requirements-server-cpu.txt"


def test_pins_cpu_torch_stack():
    assert REQ.is_file(), "requirements-server-cpu.txt must exist at repo root"
    lines = [
        ln.strip()
        for ln in REQ.read_text().splitlines()
        if ln.strip() and not ln.strip().startswith("#")
    ]
    assert "torch==2.11.0+cpu" in lines
    assert "torchaudio==2.11.0+cpu" in lines
    assert "torchcodec==0.14.0" in lines
