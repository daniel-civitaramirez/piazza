"""Trivial smoke test to verify the test harness works."""


def test_trivial():
    assert 1 + 1 == 2


def test_project_importable():
    import piazza  # noqa: F401
