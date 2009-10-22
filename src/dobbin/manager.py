import threading
import transaction

from dobbin.exc import InvalidObjectReference
from dobbin.exc import WriteConflictError
from dobbin.exc import ReadConflictError
from dobbin.exc import ConflictError
from dobbin.persistent import checkout
from dobbin.persistent import Broken
from dobbin.persistent import Persistent
from dobbin.persistent import sync

ROOT_OID = 0

setattr = object.__setattr__

class Manager(object):
    """Transactional object manager.

    This class implements a two-phase transactional object manager.

    Subclasses must implement:

    -new_oid(obj)
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
        return self.get(ROOT_OID)

    def abort(self, transaction):
        """Abort changes."""

        self._revert(self._thread.modified)
        self._revert(self._thread.committed)

    def add(self, obj):
        """Add an object to the database.

        Note that the recommended way to add objects is through the
        root object graph.
        """

        if obj._p_jar is None:
            obj._p_jar = self
        elif obj._p_jar is self:
            raise RuntimeError("Object already added to the database.")
        else:
            raise InvalidObjectReference(obj)

        checkout(obj)

    def afterCompletion(self, transaction):
        pass

    def beforeCompletion(self, transaction):
        pass

    def commit(self, transaction):
        """Commit changes to disk."""

        committed = self._thread.committed
        modified = self._thread.modified
        timestamp = self._thread.timestamp

        # update transaction timestamp
        self._thread.timestamp = sync.timestamp

        while modified:
            for obj in tuple(modified):
                # assert that object belongs to this database
                if obj._p_jar is not self:
                    raise InvalidObjectReference(obj)

                # if the object has been updated since we begun our
                # transaction, it's a write-conflict.
                if obj._p_serial > timestamp:
                    try:
                        state = self._resolve(obj)
                    except ConflictError:
                        raise WriteConflictError(obj)
                else:
                    state = obj.__getstate__()

                # make sure the object has an oid
                oid = obj._p_oid
                if oid is None:
                    oid = self.new_oid(obj)

                self.write(oid, obj._p_class, state)
                committed.append((obj, state))
                modified.remove(obj)

        # update database timestamp
        self.tx_timestamp = self._thread.timestamp

    def get(self, oid, cls=None):
        obj = self._oid2obj.get(oid)
        if obj is None and cls is not None:
            obj = Broken(oid, cls)
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
        return self._register(obj)

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

        state = self._thread
        oid2obj = self._oid2obj
        timestamp = self._thread.timestamp
        committed = self._thread.committed

        while committed:
            obj, state = committed.pop()
            oid2obj[obj._p_oid] = obj
            obj.__setstate__(state)
            obj._p_serial = timestamp

        self._tpc_cleanup()

    def _register(self, obj):
        if self._thread.needs_to_join:
            transaction.get().join(self)
            self._thread.needs_to_join = False
            self._thread.timestamp = sync.timestamp

        modified = self._thread.modified
        if obj not in modified:
            modified.add(obj)

    def _read(self, jar, start=None, end=None):
        conflicts = set()

        for record, objects in self.read(jar, start):
            timestamp = record.timestamp
            if end and timestamp > end:
                break

            for oid, cls, state in objects:
                obj = jar.get(oid, cls)

                if obj in self._thread.modified:
                    # if our version of the object is persistent-local
                    # then we have a write conflict; it may be
                    # resolved, if the object provides a conflict
                    # resolution method; it gets called with three
                    # arguments: (old_state, saved_state, new_state).
                    try:
                        state = self._resolve(obj, new_state=state)
                    except ConflictError:
                        conflicts.add(obj)
                else:
                    setattr(obj, "__class__", cls)

                # update timestamp
                setattr(obj, '_p_serial', timestamp)

                # associate with this database
                setattr(obj, '_p_jar', jar)

                # set shared state
                obj.__setstate__(state)

            yield record

        if conflicts:
            raise ReadConflictError(*conflicts)

    def _resolve(self, obj, new_state=None):
        self.lock_acquire()
        try:
            if obj._p_resolve_conflict is None:
                raise ConflictError(obj)
            if new_state is None:
                new_state = obj.__getstate__()
            return obj._p_resolve_conflict(
                obj.__oldstate__(), super(type(obj), obj).__getstate__(), new_state)
        finally:
            self.lock_release()

    def _revert(self, objects):
        while objects:
            obj = objects.pop()
            obj.__setstate__()

    def _sync(self):
        for record in self._read(self, self.tx_timestamp):
            self.tx_count += 1
            self.tx_timestamp = record.timestamp

    def _tpc_cleanup(self):
        """Performs cleanup operations to support ``tpc_finish`` and
        ``tpc_abort``."""

        self._thread.needs_to_join = True
        self.tx_count += 1

class ThreadState(threading.local):
    """Thread-local database state."""

    needs_to_join = True
    timestamp = None

    def __init__(self):
        self.modified = set()
        self.committed = []
