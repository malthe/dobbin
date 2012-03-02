import os
import sys
import copy
import threading
import transaction
import types
import weakref

from dobbin.exc import ObjectGraphError
from dobbin.utils import make_timestamp
from dobbin.utils import add_class_properties
from dobbin.utils import marker

EMPTY = marker()
MARKER = marker()
DELETE = marker()
IGNORE = marker()

setattr = object.__setattr__
delattr = object.__delattr__
setitem = dict.__setitem__
getitem = dict.__getitem__
delitem = dict.__delitem__
contains_item = dict.__contains__

_co_lock = threading.RLock()
_ci_lock = threading.Lock()


def checkout(obj):
    """Checks out the object for this thread to make local changes."""

    if not isinstance(obj, Persistent):
        raise TypeError("Object %s is not type ``Persistent``." % repr(obj))

    _co_lock.acquire()
    try:
        obj._p_checkout()

        if obj._p_jar is not None:
            obj._p_jar.save(obj)
    finally:
        _co_lock.release()


class Persistent(object):
    """Persistent base class.

    All persistent objects must derive from this class. Persistent
    classes are responsible for MVCC-compliance on a thread-level.

    The ``_p_checkout`` method is called once when the object is first
    checked out by any one thread, while the ``_p_checkin`` is called
    when all threads are done with the object.
    """

    _p_jar = None
    _p_oid = None
    _p_serial = None
    _p_resolve_conflict = None

    def __new__(cls, *args, **kwargs):
        for base in cls.__mro__:
            if base.__new__ is cls.__new__:
                continue
            try:
                inst = base.__new__(cls)
            except TypeError:
                continue
            break
        else:
            raise TypeError("Can't create object of type %s." % repr(cls))

        checkout(inst)
        return inst

    def __deepcopy__(self, memo):
        return self

    def __hash__(self):
        return id(self)

    def __getstate__(self):
        return self.__dict__

    def __delattr__(self, key):
        raise TypeError("Can't delete attribute of shared object.")

    def __setstate__(self, new_state={}):
        self.__dict__.update(new_state)

    def __setattr__(self, key, value):
        raise TypeError("Can't set attribute on shared object.")

    def _p_checkin(self):
        raise TypeError("Object not checked out.")

    def _p_checkout(self):
        state = self.__dict__
        setattr(self, '__dict__', {'_p_state': state})

        # assign new class
        wc = WorkingCopyDict(state)
        setattr(self, '__class__', self._p_class(wc))

        # notify object of checkout; we pass in the instance
        # dictionary since it may be masked by the new class
        return self._p_checkout()

    def _p_class(self, dict):
        cls = self.__class__
        d = {'_p_class': cls, '__dict__': dict}

        add_class_properties(cls, Local, d)

        class metacls(type):
            def mro(cls):
                mro = type.mro(cls)
                mro.insert(mro.index(Persistent), Local)
                return tuple(mro)

        return metacls("Local%s" % cls.__name__, (Local, cls), d)


class PersistentDict(Persistent, dict):
    """Persistent dictionary.

    Caution: Iteration through a checked out dictionary will
    transparently check out keys and/or values (whichever is
    retrieved).
    """

    _p_items = None

    def __init__(self, state=None):
        if state is not None:
            self.__dict__.update(state)

    def __repr__(self):
        return "<%s.%s at 0x%x>" % (
            type(self).__module__, type(self).__name__, id(self))

    def __getstate__(self):
        return self.__dict__, self

    def __setstate__(self, updated=None):
        if updated is None:
            updated = {}, {}
        new_state, new_items = updated
        self.__dict__.update(new_state)
        self.update(new_items)

    def __delitem__(self, key, value):
        raise TypeError("Can't delete entry from shared dictionary.")

    def __setitem__(self, key, value):
        raise TypeError("Can't set entry on shared dictionary.")

    def _p_class(self, d):
        items = WorkingCopyDict(self)
        cls = self.__class__
        d = {'_p_class': cls, '_p_items': items, '__dict__': d}

        # copy dictionary methods
        exclude = LocalDict.__dict__
        for key in dict.__dict__:
            if key not in exclude:
                value = getattr(items, key, None)
                if isinstance(value, types.MethodType):
                    d[key] = staticmethod(value)

        add_class_properties(cls, LocalDict, d)
        return type("Local%s" % cls.__name__, (LocalDict, cls), d)


class PersistentFile(object):
    """Persistent file.

    Pass an open file to persist it in the database. The file you pass
    in should not closed before the transaction ends (usually it will
    fall naturally out of scope, which prompts Python to close it).

    :param stream: open stream-like object

    Typical usage is the input-stream of an HTTP request.
    """

    def __init__(self, stream):
        self.stream = stream

    def close(self):
        self.stream.close()

    @property
    def closed(self):
        self.stream.closed

    @property
    def name(self):
        return self.stream.name

    def tell(self):
        return self.stream.tell()

    def seek(self, offset, whence=os.SEEK_SET):
        return self.stream.seek(offset, whence)

    def read(self, size=-1):
        return self.stream.read(size)


class Local(Persistent):
    """Persistent object with thread-local state.

    Changes can be made to the instance ``__dict__`` or any other way
    provided by the object through its methods (basically, the object
    is safe to use or abuse as required by the application).

    When data is read from the object (e.g. attributes), a deep-copied
    value is returned; subsequent reads to the same value return the
    same copy.

    The ``__setstate__`` method is used to commit a changeset (as
    reported by the ``__getstate__`` method). It's ill-advised to call
    this method from user-code.

    The ``__oldstate__`` method returns the state as it was when the
    transaction begun.

    Note that while changes are committed immediately to the shared
    state of the object, the *reverse* changeset is added to an
    internal list such that other threads may counter the changes in
    on-going transactions (providing a consistent dataset, i.e. MVCC
    isolation).

    The object can return to shared state only when all threads have
    transactions that date after the most recent changeset. The
    synchronizer calls the ``_p_checkin`` method when this is the
    case.
    """

    _p_jar = property(lambda self: self._p_state.get('_p_jar'))
    _p_oid = property(lambda self: self._p_state.get('_p_oid'))
    _p_serial = property(lambda self: self._p_state.get('_p_serial'))
    _p_state = None

    def __getstate__(self):
        return self.__dict__.__getstate__()

    def __oldstate__(self):
        return self.__dict__.__oldstate__()

    def __setstate__(self, new_state={}):
        self.__dict__.__setstate__(new_state)

    def __getattr__(self, key):
        try:
            return self.__dict__[key]
        except KeyError:
            raise AttributeError(key)

    def __setattr__(self, key, value):
        if key.startswith('_p_') or key.startswith('__'):
            self._p_state[key] = value
        else:
            self.__dict__[key] = value

    def _p_checkin(self):
        _ci_lock.acquire()
        try:
            setattr(self, '__class__', self._p_class)
            setattr(self, '__dict__', self._p_state)
        finally:
            _ci_lock.release()

    def _p_checkout(self):
        self.__dict__.__init__()
        sync(self)


class LocalDict(Local, PersistentDict):
    """Persistent dictionary with thread-local state."""

    def __getstate__(self):
        return self.__dict__.__getstate__(), self._p_items.__getstate__()

    def __setstate__(self, updated=None):
        if updated is None:
            updated = {}, {}
        new_state, new_items = updated
        self.__dict__.__setstate__(new_state)
        self._p_items.__setstate__(new_items)


class Broken(Persistent):
    """Broken object.

    When a persistent object references another persistent object
    which hasn't yet been loaded, it gets this superclass.
    """

    def __new__(cls, oid, obj_class):
        for base in reversed(obj_class.mro()):
            try:
                inst = base.__new__(obj_class)
                break
            except TypeError:
                pass
        else:
            raise
        cls = type(cls.__name__, (cls, obj_class), {})
        setattr(inst, "__class__", cls)
        return inst

    def __init__(self, oid, cls):
        setattr(self, '_p_oid', oid)


class WorkingCopyDict(threading.local):
    """Working-copy instance dictionary which provides data
    consistency through the course of a transaction."""

    __slots__ = '_p_dict', '_p_changes', '_p_active'

    def _p_apply(self, start, local):
        for timestamp, change in self._p_changes:
            if start and timestamp < start:
                continue

            if change.pop(EMPTY, False):
                local.clear()

            exclude = set(local.keys())
            for key in change:
                if key not in exclude:
                    value = change[key]
                    key = copy.deepcopy(key)
                    value = copy.deepcopy(value)
                    local[key] = value

    def __new__(cls, d):
        inst = threading.local.__new__(cls)
        threading.local.__setattr__(inst, '_p_dict', d)
        threading.local.__setattr__(inst, '_p_active', {})
        threading.local.__setattr__(inst, '_p_changes', [])
        return inst

    def __init__(self, *args):
        local = self.__dict__

        # mark this thread as active (it may already be marked as
        # such, but we still need to update the timestamp to catch up
        # on changes)
        self._p_active[id(local)] = sync.timestamp, local

        # apply required changesets
        self._p_apply(sync.timestamp, local)

    def __contains__(self, key):
        value = self.__dict__.get(key, MARKER)
        if value is DELETE:
            return False
        if value is not MARKER:
            return True

        return contains_item(self._p_dict, key)

    def __delitem__(self, key):
        self[key] = DELETE

    def __getitem__(self, key):
        local = self.__dict__
        try:
            value = local[key]
        except KeyError:
            pass
        else:
            if value is DELETE:
                raise KeyError(key)
            if value is not IGNORE:
                return value

        shared = self._p_dict
        if not contains_item(local, EMPTY):
            value = getitem(shared, key)
            new_value = copy.deepcopy(value)
            if value is not new_value:
                local[key] = new_value
            return new_value

        raise KeyError(key)

    def __setitem__(self, key, value):
        self.__dict__[key] = value

    def __iter__(self):
        # first iterate over local entries; we record each entry so
        # avoid duplicates when later iterating over shared entries
        keys = []
        for key, value in self.__dict__.items():
            if key is IGNORE:
                continue
            if key is not DELETE:
                yield key
            keys.append(key)

        for key in dict.__iter__(self._p_dict):
            if key not in keys:
                # deep-copy the key; if it's not the same object, we
                # set it on the local copy, with a marker value
                new_key = copy.deepcopy(key)
                if new_key is not key:
                    self[new_key] = IGNORE
                yield new_key

    def __getstate__(self):
        return self

    def __oldstate__(self):
        local = self._p_dict.copy()
        changes = {}
        self._p_apply(None, changes)
        local.update(changes)
        return local

    def __reduce__(self):
        return dict, (self.__dict__,)

    def __setstate__(self, new_state):
        # if the state is a working copy dictionary, we just use the
        # local entries (see the ``__reduce__`` method)
        if isinstance(new_state, WorkingCopyDict):
            new_state = new_state.__dict__

        if new_state:
            change = {}
            shared = self._p_dict

            if EMPTY in new_state:
                change.update(shared)
                dict.clear(shared)

            for key, value in new_state.items():
                if value is IGNORE:
                    continue

                change[key] = dict.get(shared, key, DELETE)

                if value is DELETE:
                    delitem(shared, key)
                elif value is not IGNORE:
                    setitem(shared, key, value)

            self._p_changes.append((sync.timestamp, change))

        local = self.__dict__
        local.clear()
        self._p_active[id(local)] = None, local

        # apply changeset immediately
        for timestamp, d in self._p_active.values():
            if d is not local:
                self._p_apply(timestamp, d)

    def clear(self):
        local = self.__dict__
        local.clear()
        local[EMPTY] = True

    def copy(self):
        return dict(self.items())

    @classmethod
    def fromkeys(cls, iterable, value=None):
        d = cls()
        for key in iterable:
            d[key] = value
        return d

    def get(self, key, default=None):
        try:
            return self[key]
        except KeyError:
            return default

    def has_key(self, key):
        return key in self

    def items(self):
        return [(key, self[key]) for key in self]

    def iteritems(self):
        return ((key, self[key]) for key in self)

    def iterkeys(self):
        return iter(self)

    def itervalues(self):
        return (self[key] for key in self)

    def keys(self):
        return [key for key in self]

    def pop(self, key, default=MARKER):
        shared = self._p_dict
        local = self.__dict__

        value = local.get(key, MARKER)
        if value not in (MARKER, DELETE):
            if contains_item(shared, key):
                local[key] = DELETE
            else:
                del local[key]
            return value

        value = dict.get(shared, key, MARKER)
        if value is not MARKER:
            local[key] = DELETE
            return value

        if default is not MARKER:
            return default

        raise KeyError(key)

    def popitem(self):
        for key in self:
            return key, self.pop(key)
        raise KeyError("Can't pop item from empty dictionary.")

    def setdefault(self, key, default):
        value = self.get(key, MARKER)
        if value is not MARKER:
            return value
        self[key] = default
        return default

    def update(self, d):
        for key, value in d.items():
            self[key] = value

    def values(self):
        return [self[key] for key in self]


class Synchronizer(threading.local):
    """Object synchronizer.

    The synchronizer (which is instantiated globally as a singleton)
    keeps a global set of connected objects (objects in local state
    that are connected to a database) and a thread-local set of
    unconnected objects (which are objects in local state that are not
    connected to a database and thus only known to that particular
    thread).

    When a transaction is begun, the timestamp is recorded
    (``sync.timestamp``).

    When a transaction is about to be committed, the timestamp is
    updated.

    When a transaction is committed, it is asserted that there are no
    unconnected objects.

    When a transaction ends, we determine if any connected objects can
    return to shared state.

    The synchronizer provides a sorting key that makes sure it is
    visited last in each transaction phase.
    """

    __slots__ = "_connected",

    if sys.version_info[:3] < (2, 7, 0):
        __slots__ += ("__weakref__", )

    timestamp = None
    _tx_start = weakref.WeakKeyDictionary()
    _tx_lock = threading.Lock()

    def __new__(cls):
        inst = threading.local.__new__(cls)
        inst._connected = set()
        return inst

    def __init__(self):
        self._unconnected = set()
        transaction.manager.registerSynch(self)
        tx = transaction.get()
        self.newTransaction(tx)

    def __call__(self, obj):
        pool = self._unconnected if obj._p_jar is None else self._connected
        pool.add(obj)

        # make sure we have a valid transaction timestamp
        thread = threading.current_thread()
        self._tx_start[thread] = self.timestamp

    def abort(self, tx):
        pass

    def afterCompletion(self, tx):
        connected = self._connected

        self._tx_lock.acquire()
        try:
            # compute earliest and latest transaction timestamp
            timestamps = tuple(filter(None, self._tx_start.values()))
            earliest = min(timestamps) if timestamps else None

            reconnect = set()
            while connected:
                obj = connected.pop()

                # check if the earliest transaction began after the last
                # change was committed to the object
                last = obj._p_serial
                if earliest is None or last is not None and earliest >= last:
                    obj._p_checkin()
                else:
                    reconnect.add(obj)

            connected |= reconnect
        finally:
            self._tx_lock.release()

        self._unconnected.clear()
        self._tx_start[threading.current_thread()] = None

    def beforeCompletion(self, tx):
        self.timestamp = make_timestamp()
        self._tx_start[threading.current_thread()] = None

        if self._unconnected:
            transaction.get().join(self)

    def newTransaction(self, tx):
        thread = threading.current_thread()
        self._tx_start[thread] = self.timestamp = make_timestamp()

        # we check out the objects we've activated in a previous
        # transaction and which haven't been retracted to a shared
        # state; this allows the local state to catch up on changesets
        for obj in self._connected:
            obj._p_checkout()

    def commit(self, tx):
        pass

    def sortKey(self):
        return (id(object),)

    def tpc_begin(self, tx):
        pass

    def tpc_abort(self, tx):
        pass

    def tpc_vote(self, tx):
        connected = self._connected
        unconnected = self._unconnected

        for obj in unconnected:
            if obj._p_jar is not None:
                connected.add(obj)
            else:
                raise ObjectGraphError(
                    "%s not connected to graph." % repr(obj))

    def tpc_finish(self, tx):
        pass

sync = Synchronizer()
