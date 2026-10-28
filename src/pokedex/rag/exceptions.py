class InvalidIndexError(Exception):
    """Raised when the RAG index is unreadable, inconsistent, or was built with a different embedding model."""
