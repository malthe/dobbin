import logging
import threading
import transaction

from dobbin.exc import InvalidObjectReference
from dobbin.exc import WriteConflictError
from dobbin.exc import ReadConflictError
from dobbin.exc import ConflictError
from dobbin.persistent import retract
from dobbin.persistent import Broken
from dobbin.persistent import Local
from dobbin.persistent import Persistent
from dobbin.utils import make_timestamp

ROOT_OID = 0

log = logging.getLogger("dobbin.common")

marker = object()

class Manager(object):
    """Transactional object manager.

    This class implements a two-phase transactional object manager.

    Subclasses must implement:

    -read(jar, timestamp)
    -write(obj)

    Subclasses can implement:

    -tpc_begin
    -tpc_vote
    -tpc_abort
    -tpc_finish

    """

    tx_ref = None
    tx_count = 0
    tx_timestamp = None

    def __init__(self):
        # define reentrant thread-lock
        l = threading.RLock()
        self.lock_acquire = l.acquire
        self.lock_release = l.release

        # persistent-id to object mapping
        self._oid2obj = {}

        # initialize thread-local state
        self._thread = ThreadState()

        # load objects from storage
        self._sync()

    def __deepcopy__(self, memo):
        return self

    def __len__(self):
        return len(self._oid2obj)

    def __repr__(self):
        return '<%s size="%d">' % (type(self).__name__, len(self))

    @property
    def root(self):
        if self._thread.timestamp is None:
            transaction.manager.registerSynch(self)
            tx = transaction.manager.get()
            self.newTransaction(tx)
        return self.get(ROOT_OID, None)

    def abort(self, transaction):
        """Abort changes."""

        self._revert(self._thread.registered)
        self._revert(self._thread.committed)

    def add(self, obj):
        """Add an object to the database.

        Note that the recommended way to add objects is through the
        root object graph.
        """

        if not isinstance(obj, Persistent):
            raise TypeError(
                "Can't add non-persistent object.")

        if not isinstance(obj, Local):
            raise TypeError(
                "Check out object before adding it to the database.")

        if obj._p_jar is None:
            obj._p_jar = self
            self._register(obj)
        elif obj._p_jar is self:
            raise RuntimeError(
                "Object already added to the database.")
        else:
            raise InvalidObjectReference(obj)

    def afterCompletion(self, transaction):
        pass

    def beforeCompletion(self, transaction):
        pass

    def commit(self, transaction):
        """Commit changes to disk."""

        committed = self._thread.committed
        registered = self._thread.registered
        timestamp = self._thread.timestamp

        # update transaction timestamp
        self._thread.timestamp = make_timestamp()

        while registered:
            for obj in tuple(registered):
                # assert that object belongs to this database
                if obj._p_jar is not self:
                    raise InvalidObjectReference(obj)

                # if the object has been updated since we begun our
                # transaction, it's a write-conflict.
                if obj._p_serial > timestamp:
                    raise WriteConflictError(obj)

                self.write(obj)
                committed.add(obj)
                registered.remove(obj)

        # update database timestamp
        self.tx_timestamp = self._thread.timestamp

    def get(self, oid, default=marker):
        obj = self._oid2obj.get(oid, default)
        if obj is marker:
            obj = Broken(oid)
            self._oid2obj[oid] = obj
        return obj

    def elect(self, obj):
        """Elect object as database root."""

        if not isinstance(obj, Persistent):
            raise TypeError(
                "Can't set non-persistent object as database root.")

        if obj._p_oid is not None:
            raise ValueError("Can't elect already persisted object.")

        if self.root is not None:
            raise RuntimeError("This database already has a root object.")

        obj._p_oid = ROOT_OID
        self.add(obj)

    def newTransaction(self, transaction):
        """New transaction."""

        self._sync()

    def save(self, obj):
        self._register(obj)

    def snapshot(self, database, timestamp=None):
        """Return database snapshot."""

        # restore snapshot from database
        for record in self._read(database, end=timestamp):
            pass

        # write snapshot to storage
        tx = transaction.Transaction()
        tx.join(database)
        tx.commit()

    def sortKey(self):
        """Sort-key.

        This method is required by the transaction machinery; the key
        returned guarantees that the first thread to check out an
        object wins the transaction.
        """

        return id(self), self._thread.timestamp

    def tpc_abort(self, transaction):
        """Abort transaction.

        Called when an exception occurred during ``tpc_vote`` or
        ``tpc_finish``.
        """

        self._tpc_cleanup()

    def tpc_begin(self, transaction):
        """Begin commit (two-phase) of a transaction."""

        # catch up on transactions; other processes may have committed
        # transactions which may conflict
        self._sync()

    def tpc_vote(self, transaction):
        """Vote on transaction."""

    def tpc_finish(self, transaction):
        """Indicate confirmation that the transaction is done."""

        oid2obj = self._oid2obj
        for obj in self._thread.committed:
            oid2obj[obj._p_oid] = obj

            state = obj.__getstate__()
            obj.__setstate__(state)
            obj._p_serial = self._thread.timestamp

            # unregister object with this transaction
            self._unregister(obj)

        self._tpc_cleanup()

    def _maybe_share_object(self, obj):
        if obj._p_count == 0:
            retract(obj)
            return True
        return False

    def _read(self, jar, start=None, end=None):
        mapping = jar._oid2obj
        conflicts = set()

        for record, objects in self.read(jar, start):
            timestamp = record.timestamp
            if end and timestamp > end:
                break

            for oid, cls, state in objects:
                obj = mapping.get(oid)

                # if the object does not exist in the database, we create
                # it using the ``__new__`` constructor
                if obj is None:
                    obj = object.__new__(cls)
                    state['_p_oid'] = oid
                    mapping[oid] = obj
                elif isinstance(obj, Local):
                    # if our version of the object is persistent-local
                    # then we have a write conflict; it may be
                    # resolved, if the object provides a conflict
                    # resolution method; it gets called with three
                    # arguments: (old_state, saved_state, new_state).
                    try:
                        if obj._p_resolve_conflict is None:
                            raise ReadConflictError(obj)
                        state = obj._p_resolve_conflict(
                            obj.__getstate__(), obj.__dict__, state)
                    except ConflictError:
                        conflicts.add(obj)
                else:
                    object.__setattr__(obj, "__class__", cls)

                # update timestamp
                state['_p_serial'] = timestamp

                # associate with this database
                state['_p_jar'] = jar

                # set shared state
                obj.__setstate__(state)

            yield record

        if conflicts:
            raise ReadConflictError(*conflicts)

    def _register(self, obj):
        if self._thread.needs_to_join:
            transaction.get().join(self)
            self._thread.needs_to_join = False
            self._thread.timestamp = make_timestamp()

        # if the object has not already been registered with this
        # thread we do so and update the thread-use count
        registered = self._thread.registered
        if obj not in registered:
            registered.add(obj)
            obj._p_count += 1

    def _revert(self, objects):
        while objects:
            obj = objects.pop()
            self._unregister(obj)

    def _sync(self):
        for record in self._read(self, self.tx_timestamp):
            self.tx_count += 1
            self.tx_timestamp = record.timestamp

    def _tpc_cleanup(self):
        """Performs cleanup operations to support ``tpc_finish`` and
        ``tpc_abort``."""

        self._thread.registered.clear()
        self._thread.committed.clear()
        self._thread.needs_to_join = True
        self.tx_count += 1

    def _unregister(self, obj):
        obj._p_count -= 1
        if self._maybe_share_object(obj):
            return True
        obj.__dict__.clear()

class ThreadState(threading.local):
    """Thread-local database state."""

    needs_to_join = True
    timestamp = None

    def __init__(self):
        self.registered = set()
        self.committed = set()
