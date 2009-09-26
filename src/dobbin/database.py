import logging
import threading
import transaction

from dobbin.exc import InvalidObjectReference
from dobbin.exc import WriteConflictError
from dobbin.exc import ReadConflictError
from dobbin.exc import ConflictError
from dobbin.persistent import retract
from dobbin.persistent import Local
from dobbin.persistent import Persistent
from dobbin.utils import lazy
from dobbin.utils import assert_persistent
from dobbin.utils import make_timestamp

ROOT_OID = 0

log = logging.getLogger("dobbin.database")

marker = object()

class Database(object):
    """Object database class.

    Initialized with a storage option, e.g. ``TransactionLog``. Common
    usage of the database is via the ``get_root`` and ``set_root``
    methods.

    Database instances are thread-safe.
    """

    def __init__(self, storage, transaction_manager=None):
        self._storage = storage
        self._thread = ThreadState()
        self._tx_manager = transaction_manager or transaction.manager
        self._tx_manager.registerSynch(self)

        # persistent-id to object mapping
        self._oid2obj = {}

        # acquire locks
        l = threading.RLock()
        self._lock_acquire = l.acquire
        self._lock_release = l.release

        # load objects from storage
        self._read()

    def __len__(self):
        return len(self._oid2obj)

    def __repr__(self):
        return '<%s size="%d" storage="%s">' % (
            type(self).__name__,
            len(self),
            type(self._storage).__name__)

    def add(self, obj):
        """Add an object to the database.

        Note that the recommended way to add objects is through the
        root object graph.
        """

        assert_persistent(obj)

        if obj._p_jar is None:
            obj.__dict__['_p_jar'] = self
            self._register(obj)
        elif obj._p_jar is self:
            raise RuntimeError(
                "Object already added to the database.")
        else:
            raise InvalidObjectReference(obj)

    def abort(self, transaction):
        """Abort changes."""

        self.revert(self._thread.registered)
        self.revert(self._thread.committed)

    def revert(self, objects):
        while objects:
            obj = objects.pop()
            self._unregister(obj)

    def commit(self, transaction):
        """Commit changes to disk."""

        committed = self._thread.committed
        registered = self._thread.registered
        timestamp = self._thread.timestamp

        while registered:
            for obj in tuple(registered):
                # if the object has been updated since we begun our
                # transaction, it's a write-conflict.
                if obj._p_serial > timestamp:
                    raise WriteConflictError(obj)

                # assert that object belongs to this database
                if obj._p_jar is not self:
                    raise InvalidObjectReference(obj)

                # ask storage to commit object state
                self._storage.commit(obj, transaction)

                # mark object as committed and remove it from the set of
                # objects registered for this transaction
                committed.add(obj)
                registered.remove(obj)

    def get(self, oid):
        return self._oid2obj.get(oid)

    def get_root(self):
        return self._oid2obj.get(ROOT_OID)

    def save(self, obj):
        self._register(obj)

    def set_root(self, obj):
        assert_persistent(obj)

        if obj._p_oid is not None:
            raise ValueError("Can't elect already persisted root object.")

        if self.get_root() is not None:
            raise RuntimeError("Database root already set.")

        self.add(obj)
        obj._p_oid = ROOT_OID

    def beforeCompletion(self, transaction):
        """Not used."""

    def afterCompletion(self, transaction):
        """Not used."""

    def newTransaction(self, transaction):
        """New transaction.

        We catch up on potential out-of-process transactions.
        """

        self._read()

    def tpc_abort(self, transaction):
        """Abort transaction.

        Called when an exception occurred during ``tpc_vote`` or
        ``tpc_finish``.
        """

        # update timestamp
        timestamp = self._update_timestamp()

        self._storage.tpc_abort(transaction, timestamp)
        self._tpc_cleanup()

    def tpc_begin(self, transaction):
        """Begin commit (two-phase) of a transaction."""

        # begin transaction on storage layer; the storage layer is
        # responsible for obtaining exclusive access to the database
        self._storage.tpc_begin(transaction)

        # catch up on transactions; other processes may have committed
        # transactions which may conflict
        self._read()

    def tpc_vote(self, transaction):
        """Vote on transaction."""

        # pass vote to storage layer
        self._storage.tpc_vote(transaction)

    def tpc_finish(self, transaction):
        """Indicate confirmation that the transaction is done."""

        # update timestamp
        timestamp = self._update_timestamp()

        if self._thread.registered:
            log.critical("Some objects were not committed.")

        oid2obj = self._oid2obj
        for obj in self._thread.committed:
            oid2obj[obj._p_oid] = obj

            # apply state
            state = obj.__getstate__()
            state['_p_serial'] = timestamp
            obj.__dict__.update(state)

            # unregister object with this transaction
            self._unregister(obj)

        self._storage.tpc_finish(transaction, timestamp)
        self._tpc_cleanup()

    def sortKey(self):
        """Sort-key.

        This method is required by the transaction machinery; the key
        returned guarantees that the first thread to check out an
        object wins the transaction.
        """

        return id(self), self._thread.timestamp

    def _tpc_cleanup(self):
        """Performs cleanup operations to support ``tpc_finish`` and
        ``tpc_abort``."""

        self._thread.registered.clear()
        self._thread.committed.clear()
        self._thread.needs_to_join = True

    def _maybe_share_object(self, obj):
        self._lock_acquire()

        try:
            if obj._p_count == 0:
                retract(obj)
                return True
            return False
        finally:
            self._lock_release()

    def _read(self):
        oid2obj = self._oid2obj
        conflicts = set()

        self._lock_acquire()

        try:
            for oid, cls, state, timestamp in self._storage.read(self):
                obj = oid2obj.get(oid)

                # if the object does not exist in the database, we create
                # it using the ``__new__`` constructor
                if obj is None:
                    obj = object.__new__(cls)
                    state['_p_jar'] = self
                    state['_p_oid'] = oid
                    oid2obj[oid] = obj
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

                # update timestamp
                state['_p_serial'] = timestamp

                # set shared state
                Persistent.__setstate__(obj, state)

            if conflicts:
                raise ReadConflictError(*conflicts)
        finally:
            self._lock_release()

    def _register(self, obj):
        if self._thread.needs_to_join:
            self._tx_manager.get().join(self)
            self._thread.needs_to_join = False
            self._thread.timestamp = make_timestamp()

        # if the object has not already been registered with this
        # thread we do so and update the thread-use count
        registered = self._thread.registered
        if obj not in registered:
            registered.add(obj)
            obj._p_count += 1

    def _unregister(self, obj):
        obj._p_count -= 1
        if self._maybe_share_object(obj):
            return True
        obj.__setstate__()

    def _update_timestamp(self):
        timestamp = self._thread.timestamp = make_timestamp()
        return timestamp

    def __deepcopy__(self, memo):
        return self

class ThreadState(threading.local):
    """Thread-local database state."""

    registered = lazy(set)
    committed = lazy(set)
    needs_to_join = True
    timestamp = None
