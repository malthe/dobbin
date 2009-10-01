class ConflictError(Exception):
    """Two transactions tried to modify the same object at once."""

    def __init__(self, obj):
        self.object = obj

class WriteConflictError(ConflictError):
    """Conflict that arises when a checked out object has been
    modified by another process."""

class ReadConflictError(ConflictError):
    """Conflict that arises when a transaction can't be applied to one
    or more objects which is part of the working set."""

    def __init__(self, *objects):
        self.objects = objects

    def __repr__(self):
        return '<%s objects="%d">' % (
            type(self).__name__, len(self.objects))

class IntegrityError(Exception):
    """Integrity error."""

    def __init__(self, message):
        self.message = message

    def __repr__(self):
        return '<%s %s>' % (
            type(self).__name__, repr(self.reason))

class ObjectGraphError(Exception):
    """Object graph integrity error."""

class InvalidObjectReference(Exception):
    """Object reference invalid for this database."""

    def __init__(self, obj):
        self.object = obj
