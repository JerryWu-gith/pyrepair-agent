"""Owned Linux-container safety assertions, never run as host project tests."""

import errno
import os
import socket
from pathlib import Path

import pytest


def test_non_root():
    assert os.getuid() > 0
    assert os.getgid() > 0


def test_readonly_root():
    with pytest.raises(OSError) as error:
        Path("/pyrepair-readonly-probe").write_text("owned", encoding="utf-8")
    assert error.value.errno == errno.EROFS


def test_readonly_input():
    with pytest.raises(OSError) as error:
        Path("/input/repo/pyproject.toml").write_text("owned", encoding="utf-8")
    assert error.value.errno == errno.EROFS


def test_credentials_absent():
    assert "PYREPAIR_CREDENTIAL_SENTINEL" not in os.environ
    assert "DEEPSEEK_API_KEY" not in os.environ
    assert "OPENAI_API_KEY" not in os.environ
    assert not Path("/input/repo/.env").exists()


def test_external_network_blocked():
    assert {name for _, name in socket.if_nameindex()} == {"lo"}
    for address in ("1.1.1.1", "8.8.8.8"):
        with socket.socket() as stream:
            stream.settimeout(1)
            assert stream.connect_ex((address, 443)) != 0


def test_loopback_available():
    with socket.socket() as server:
        server.bind(("127.0.0.1", 0))
        server.listen(1)
        with socket.create_connection(server.getsockname(), timeout=1):
            connection, _ = server.accept()
            connection.close()


def test_seccomp_active():
    status = Path("/proc/self/status").read_text(encoding="utf-8")
    modes = [
        line.partition(":")[2].strip()
        for line in status.splitlines()
        if line.startswith("Seccomp:")
    ]
    assert modes == ["2"]


def test_runtime_versions():
    import sys
    from importlib.metadata import version

    assert sys.version_info[:3] == (3, 13, 5)
    for name, expected in {
        "pytest": "9.1.1",
        "iniconfig": "2.1.0",
        "packaging": "25.0",
        "pluggy": "1.6.0",
        "pygments": "2.19.2",
    }.items():
        assert version(name) == expected
