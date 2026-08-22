# Breaks: pytest (a deliberately inverted assertion, computed at runtime so mypy's
# comparison-overlap check -- which correctly flags literal `1 == 2` as always-false --
# does not also fire. The failure must isolate to pytest alone.)
def test_deliberately_failing_fixture() -> None:
    computed = len([1])
    assert computed == 2, "CI fixture 03: this failure is intentional (SC-003)"
