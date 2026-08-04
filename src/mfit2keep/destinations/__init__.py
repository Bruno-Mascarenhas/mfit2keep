"""Destinos disponíveis para as notas de treino."""

from mfit2keep.destinations.base import NoteDestination, NoteResult
from mfit2keep.destinations.local import LocalMarkdownDestination

__all__ = ["LocalMarkdownDestination", "NoteDestination", "NoteResult"]
