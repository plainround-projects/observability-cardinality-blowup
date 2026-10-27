"""Named errors that cross layer boundaries."""


class DomainError(Exception):
    """Base class for every error this project raises on purpose."""


class InvalidIdentifierError(DomainError):
    """A user or tenant id is empty, too long or contains characters outside the allowed set."""
