# Breaks: mypy (assigns str to an int-annotated name; returns wrong type)
def count_resources(n: int) -> int:
    total: int = "not an integer"
    return total
