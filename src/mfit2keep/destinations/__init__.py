"""Destinos disponíveis para as notas de treino."""

from .base import NoteDestination, NoteResult
from .local import LocalMarkdownDestination

__all__ = ["LocalMarkdownDestination", "NoteDestination", "NoteResult"]
