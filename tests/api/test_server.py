import socket

from speechtotext.api.server import pick_port


def test_pick_port_returns_available_port():
    p = pick_port()
    assert 1024 < p < 65536
    s = socket.socket()
    s.bind(("127.0.0.1", p))
    s.close()
