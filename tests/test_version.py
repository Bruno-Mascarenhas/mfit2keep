"""A versão do pacote e a do ``pyproject.toml`` não podem divergir.

A v1.1.0 foi publicada com o ``__version__`` ainda em 1.0.0, e nada acusou.
"""

import tomllib
from pathlib import Path

import mfit2keep

PYPROJECT = Path(__file__).resolve().parent.parent / "pyproject.toml"


def test_package_version_matches_the_one_declared_in_pyproject() -> None:
    declared = tomllib.loads(PYPROJECT.read_text(encoding="utf-8"))["project"]["version"]

    assert mfit2keep.__version__ == declared
