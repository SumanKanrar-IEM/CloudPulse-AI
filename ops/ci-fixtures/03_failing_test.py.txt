# Breaks: pytest (a deliberately inverted assertion)
def test_deliberately_failing_fixture() -> None:
    assert 1 == 2, "CI fixture 03: this failure is intentional (SC-003)"
