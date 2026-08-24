import ast
import pytest
from app.core.security_ast import SecurityVisitor, validate_code


def test_dangerous_code_raises_value_error():
    """Verify that dangerous code (import os; os.system('ls')) raises a ValueError."""
    code = "import os; os.system('ls')"
    with pytest.raises(ValueError, match="Forbidden module import: os"):
        validate_code(code)


def test_dangerous_code_visitor_directly():
    """Verify that SecurityVisitor directly raises ValueError on dangerous code."""
    code = "import os; os.system('ls')"
    tree = ast.parse(code)
    visitor = SecurityVisitor()
    with pytest.raises(ValueError):
        visitor.visit(tree)


@pytest.mark.parametrize(
    "dangerous_code",
    [
        "import os; os.system('ls')",
        "import sys; sys.exit(0)",
        "import subprocess; subprocess.run(['ls'])",
        "from os import system",
        "eval('1 + 1')",
        "exec('print(1)')",
        "open('file.txt')",
    ],
)
def test_various_dangerous_code_snippets(dangerous_code):
    """Verify that various forbidden modules and functions raise ValueError."""
    with pytest.raises(ValueError):
        validate_code(dangerous_code)


def test_data_science_script_passes_cleanly():
    """Verify that data science scripts (import pandas as pd; df.describe()) pass cleanly."""
    code = "import pandas as pd; df.describe()"
    # Should not raise any exception
    validate_code(code)


def test_data_science_script_visitor_directly():
    """Verify that SecurityVisitor directly passes data science script cleanly."""
    code = "import pandas as pd; df.describe()"
    tree = ast.parse(code)
    visitor = SecurityVisitor()
    visitor.visit(tree)


@pytest.mark.parametrize(
    "ds_code",
    [
        "import pandas as pd; df.describe()",
        "import numpy as np\na = np.array([1, 2, 3])\nprint(a.mean())",
        "import matplotlib.pyplot as plt\nplt.plot([1, 2], [3, 4])",
        "df['total'] = df['x'] + df['y']",
    ],
)
def test_various_data_science_snippets(ds_code):
    """Verify that various safe data science code snippets pass cleanly."""
    validate_code(ds_code)
