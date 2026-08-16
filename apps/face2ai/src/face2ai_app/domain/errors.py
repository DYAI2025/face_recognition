class Face2AIError(Exception):
    """Base domain error."""


class RecognitionUnavailable(Face2AIError):
    pass


class InvalidFrame(Face2AIError):
    pass


class EnrollmentRejected(Face2AIError):
    pass


class IdentityStoreCorrupted(Face2AIError):
    """Raised when persisted identity data cannot be safely decoded or validated."""
