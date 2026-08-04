"""Ponto de entrada de ``python -m mfit2keep``.

Existe para que a CLI seja alcançável sem depender do script instalado em PATH —
útil em container, em cron e em ambiente virtual não ativado.
"""

from mfit2keep.cli import app

if __name__ == "__main__":
    app()
