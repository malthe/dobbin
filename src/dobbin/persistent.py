import copy
import os
import threading

marker = object()

def checkout(obj):
    """Puts the object in local state, such that the object can be
    changed without breaking the data integrity of other threads."""

    if not isinstance(obj, Persistent):
        raise TypeError("Object is not persistent.")

    # return objects in local state immediately
    if isinstance(obj, Local):
        obj._p_jar.save(obj)
        return

    # upgrade class with persistent local bindings
    obj.__class__ = make_persistent_local(obj.__class__)

    __dict__ = obj.__dict__
    _p_local = __dict__.get("_p_local", marker)
    if _p_local is marker:
        __dict__['_p_local'] = threading.local()

    # we assume that this object will be modified
    if obj._p_jar is not None:
        if obj._p_oid is None:
            obj._p_jar.add(obj)
        else:
            obj._p_jar.save(obj)

def retract(obj):
    """Returns the object to shared state."""

    if not isinstance(obj, Local):
        raise TypeError("Object is not local-persistent.")

    cls = undo_persistent_local(type(obj))
    object.__setattr__(obj, "__class__", cls)
    del obj._p_local
    return obj

def make_persistent_local(cls):
    """Returns a class that derives from ``Local``."""

    return type(cls.__name__, (Local, cls), {})

def undo_persistent_local(cls):
    """Returns the class that was made local."""

    return cls.__bases__[1]

def update_local(inst, _p_local_dict):
    """Updates local dictionary with a deep copy of the shared state."""

    __dict__ = object.__getattribute__(inst, "__dict__")
    _p_local_dict.update(copy.deepcopy(__dict__))

class Persistent(object):
    """Persistent base class."""

    _p_jar = None
    _p_oid = None
    _p_serial = None
    _p_resolve_conflict = None

    def __setattr__(self, key, value):
        if key.startswith("__"):
            return object.__setattr__(self, key, value)
        if key.startswith("_p_"):
            raise ValueError("Can't set system attribute: %s." % key)
        raise RuntimeError("Can't set attribute in read-only mode.")

    def __setstate__(self, state):
        self.__dict__.update(state)

    def __deepcopy__(self, memo):
        """Persistent objects are never deep-copied."""

        return self

class Local(Persistent):
    """Objects that derive from this class have thread-local state,
    which is prepared on-demand on a per-thread basis."""

    _p_count = 0
    _p_local = None

    def __getstate__(self):
        state = {}
        for key, value in self._p_local.__dict__.items():
            if key.startswith('_p_'):
                continue
            state[key] = value
        state['_p_oid'] = self._p_oid
        return state

    def __setstate__(self, new_state=None):
        state = self._p_local.__dict__
        state.clear()
        if new_state is not None:
            state.update(new_state)

    def __setattr__(self, key, value):
        if key.startswith('_p_') or key.startswith('__'):
            object.__setattr__(self, key, value)

        _p_local_dict = self._p_local.__dict__
        if not _p_local_dict:
            update_local(self, _p_local_dict)

        _p_local_dict[key] = value

    def __getattribute__(self, key):
        if key.startswith('_p_') or key.startswith('__'):
            return object.__getattribute__(self, key)

        _p_local_dict = self._p_local.__dict__
        if not _p_local_dict:
            update_local(self, _p_local_dict)

        try:
            return _p_local_dict[key]
        except KeyError:
            # raise regular attribute-error; the thread-local
            # dictionary is an implementation detail that does not
            # benefit debugging
            raise AttributeError(key)

class PersistentFile(threading.local):
    """Persistent file.

    Pass an open file to persist it in the database. The file you pass
    in should not closed before the transaction ends (usually it will
    fall naturally out of scope, which prompts Python to close it).

    :param stream: open stream-like object

    Typical usage is the input-stream of an HTTP request.
    """

    def __init__(self, stream):
        self.stream = stream

    @property
    def name(self):
        return self.stream.name

    def tell(self):
        return self.stream.tell()

    def seek(self, offset, whence=os.SEEK_SET):
        return self.stream.seek(offset, whence)

    def read(self, size=-1):
        return self.stream.read(size)
