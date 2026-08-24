import pytest


@pytest.fixture(autouse=True)
def fail_test_phase(request):
    if request.node.name == "test_setup_error":
        raise RuntimeError("setup failed")
    yield
    if request.node.name == "test_teardown_error":
        raise RuntimeError("teardown failed")


def test_setup_error():
    pass


def test_teardown_error():
    pass
