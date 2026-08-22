# Breaks: ruff (E501 line-too-long, F401 unused import, T201 print)
import os
def   badly_spaced( x ):
    print("this is a very long line that goes well past the hundred character limit configured in pyproject.toml for ruff")
    return x
