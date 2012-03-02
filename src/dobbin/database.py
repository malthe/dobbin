import logging
import mmap
import os
import re
import sys
import shutil
import threading
import base64

if sys.version_info[:3] < (3, 0, 0):
    import cPickle as pickle
    from cStringIO import StringIO as BytesIO
    def is_filelike(obj):
        return isinstance(obj, file)
else:
    import pickle
    from io import BytesIO
    from io import IOBase
    def is_filelike(obj):
        return isinstance(obj, IOBase)

from fcntl import flock
from fcntl import LOCK_EX
from fcntl import LOCK_UN
from fcntl import LOCK_NB

from dobbin.exc import IntegrityError
from dobbin.persistent import Persistent
from dobbin.persistent import PersistentFile
from dobbin.manager import Manager

# transaction log segment types
LOG_VERSION = 0
LOG_RECORD = 1
LOG_STREAM = 2

re_id = re.compile(r'(?P<protocol>[a-z]+)://(?P<token>.+)')
logger = logging.getLogger('dobbin.database')


class Database(Manager):
    """Object database which stores data in a single file."""

    _rstream = None
    _wstream = None
    _oid = 0

    def __init__(self, path):
        self._path = path

        # open stream for reading
        self._open()

        # pickle writer
        self._buffer = BytesIO()
        self._pickler = pickle.Pickler(self._buffer, pickle.HIGHEST_PROTOCOL)
        self._offsets = {}

        super(Database, self).__init__()

    def __copy__(self):
        return type(self)(self._path)

    def new_oid(self, obj):
        oid = obj._p_oid = self._oid + 1
        self._oid = oid
        return oid

    def close(self):
        self.lock_acquire()
        try:
            self._rstream.close()
            self._rstream = None
        finally:
            self.lock_release()

    def read(self, jar, timestamp):
        """Read transactions newer than ``timestamp``."""

        if timestamp is None:
            offset = 0
        else:
            try:
                offset = self._offsets[timestamp]
            except KeyError:
                raise ValueError(
                    "No offset found for timestamp: %s." % timestamp
                    )

        stream = self._open_mmap(offset)
        if stream is None:
            return

        size = stream.size()
        unpickler = pickle.Unpickler(stream)

        def load(oid):
            match = re_id.match(oid)
            if match is None:
                raise ValueError('Protocol mismatch: %s.' % oid)

            protocol = match.group('protocol')
            token = match.group('token')

            if protocol == 'oid':
                p = base64.b64decode(token.encode('ascii'))
                oid, cls = pickle.loads(p)
                return jar.get(oid, cls)

            if protocol == 'file':
                offset, length = map(int, token.split(':'))
                return PersistentStream(self._opener, offset, length)

            raise ValueError('Unknown protocol: %s.' % protocol)

        unpickler.persistent_load = load

        entries = []
        while size > offset:
            segment_type, segment = unpickler.load()
            offset = stream.tell()

            if segment_type == LOG_VERSION:
                entries.append(segment)

            elif segment_type == LOG_RECORD:
                self._offsets[segment.timestamp] = offset
                yield segment, entries
                del entries[:]

            elif segment_type == LOG_STREAM:
                name, length = segment
                stream.seek(length, os.SEEK_CUR)

        if entries:
            raise IntegrityError(
                "Transaction record not found for %d entries." % len(entries))

    def write(self, oid, cls, state):
        def persistent_id(obj):
            """This closure provides persistent identifier tokens for
            persistent objects and files.
            """

            if isinstance(obj, Persistent):
                if obj._p_jar is None:
                    self.add(obj)

                oid = obj._p_oid
                if oid is None:
                    oid = self.new_oid(obj)

                p = pickle.dumps((oid, obj._p_class))
                e = base64.b64encode(p).decode('ascii')

                return "oid://%s" % e

            if isinstance(obj, PersistentStream):
                return "file://%d:%d" % (obj.offset, obj.length)

            if isinstance(obj, PersistentFile):
                # write transaction log segment
                offset, length = self._write_stream(obj)

                # switch identity to transaction stream
                obj.__dict__.clear()
                obj.__class__ = PersistentStream
                obj.__init__(self._opener, offset, length)

                return "file://%d:%d" % (offset, length)

            if is_filelike(obj):
                raise TypeError(
                    "Can't persist files; use the ``PersistentFile`` wrapper.")

        self._pickler.persistent_id = persistent_id

        # pickle object state; note that the pickler instance is set
        # up to write to a buffer in memory --- the reason being that
        # pickling may fail, which is likely to result in integrity
        # errors if we write directly to disk (another critical
        # benefit is that the ``persistent_id`` method is free to
        # write data to disk, circumventing the pickle buffer; this is
        # used to write file streams in parallel with the pickle
        # operation); all in all: brittle machinery.
        self._write(LOG_VERSION, (oid, cls, state))

    def tpc_abort(self, transaction):
        self.lock_acquire()
        try:
            if transaction is not self.tx_ref:
                return
            try:
                # write transaction record
                self._write(
                    LOG_RECORD, TransactionRecord(self.tx_timestamp, False)
                    )
                self._flush()
            finally:
                # update transaction state
                self.tx_ref = None

                # release commit-lock
                self._commitlock_release()

                # close stream
                self._wstream.close()
        finally:
            self.lock_release()

        super(Database, self).tpc_abort(transaction)

    def tpc_begin(self, transaction):
        self.lock_acquire()
        try:
            if self.tx_ref is transaction:
                return

            # open write stream
            wstream = self._wstream = open(self._path, 'ab+')

            # acquire commit lock
            fd = wstream.fileno()
            self._commitlock_acquire = lambda: flock(fd, LOCK_EX | LOCK_NB)
            self._commitlock_release = lambda: flock(fd, LOCK_UN)

            self.lock_release()

            try:
                self._commitlock_acquire()
            except IOError:
                self.lock_acquire()
                self.tx_ref = None
                raise

            # acquire lock and store transaction
            self.lock_acquire()
            self.tx_ref = transaction

            # clear pickle memory; we shouldn't actually have to do
            # this---since we're anyway reading the log from the
            # beginning; XXX: look into this further
            self._pickler.clear_memo()
        finally:
            self.lock_release()

        super(Database, self).tpc_begin(transaction)

    def tpc_vote(self, transaction):
        self.lock_acquire()
        try:
            if transaction is not self.tx_ref:
                return
        finally:
            self.lock_release()

        super(Database, self).tpc_vote(transaction)

    def tpc_finish(self, transaction):
        self.lock_acquire()
        try:
            if transaction is not self.tx_ref:
                return
            try:
                # write transaction record
                self._write(
                    LOG_RECORD, TransactionRecord(self.tx_timestamp, True)
                    )
                self._flush()
            finally:
                # update transaction state
                self.tx_ref = None

                # release commit-lock
                self._commitlock_release()

                # close stream
                self._wstream.close()
        finally:
            self.lock_release()

        super(Database, self).tpc_finish(transaction)

    def _flush(self, offset=0):
        stream = self._buffer

        # persist changes on disk
        stream.seek(offset)
        bytes = stream.read()
        self._wstream.write(bytes)

        # truncate stream
        stream.seek(offset)
        stream.truncate()

        # update offset mapping
        offset = self._wstream.tell()
        self._offsets[self.tx_timestamp] = offset

        return offset

    def _open(self):
        if os.path.exists(self._path):
            f = self._rstream = open(self._path, 'rb+')
            return f

    def _open_mmap(self, offset=0):
        if self._rstream is None and not self._open():
            return

        try:
            _map = mmap.mmap(self._rstream.fileno(), 0, mmap.PROT_READ)
            _map.seek(offset)
        except (ValueError, mmap.error):
            return
        return _map

    def _opener(self):
        return open(self._path, 'rb')

    def _write(self, segment_type, data):
        try:
            self._pickler.dump((segment_type, data))
        except Exception as e:
            logger.critical("Could not pickle data: %s (type %d).\n%s" % (
                repr(data), segment_type, str(e)))
            self._flush()
            raise

    def _write_stream(self, stream):
        pos = stream.tell()
        stream.seek(0, os.SEEK_END)
        length = stream.tell() - pos
        stream.seek(pos)
        log = pickle.dumps((LOG_STREAM, (stream.name, length)))
        self._wstream.write(log)
        offset = self._wstream.tell()
        shutil.copyfileobj(stream, self._wstream, length)
        stream.close()
        return offset, length


class TransactionRecord(object):
    def __init__(self, timestamp, status):
        self.timestamp = timestamp
        self.status = status


class PersistentStream(object):
    """Binary stream persisted in the transaction log.

    Features a file-like API as well as iteration (independent from
    each other; iteration will always acquire its own file handle).
    """

    chunk_size = 32768

    def __init__(self, opener, offset, length):
        self.offset = offset
        self.length = length
        self._opener = opener
        self._thread = threading.local()

    def __deepcopy__(self, memo):
        return self

    def __iter__(self):
        """Iterate through stream.

        We always open a new file handle, detached entirely from the
        instance. It's automatically closed when the handle is
        garbage-collected since it falls out of scope at the end of
        the method.
        """

        f = self._opener()
        f.seek(self.offset)

        remaining = self.length
        chunk_size = self.chunk_size
        read = self.read

        while remaining > 0:
            count = min(chunk_size, remaining)
            bytes = read(count, f)
            remaining -= len(bytes)
            yield bytes

        f.close()

    def _get_thread_local_stream(self):
        try:
            return self._thread.stream
        except AttributeError:
            return

    def _set_thread_local_stream(self, stream):
        self._thread.stream = stream

    stream = property(_get_thread_local_stream, _set_thread_local_stream)

    @property
    def closed(self):
        if self.stream is None:
            return True
        return self.stream.closed

    @property
    def name(self):
        return self.stream.name

    def close(self):
        if self.stream is None:
            raise RuntimeError("File already closed.")

        self.stream.close()
        self.stream = None

    def open(self):
        if self.stream is not None:
            raise RuntimeError("File already open.")

        # open file for reading
        self.stream = self._opener()

        # seek to offset, if required
        if self.offset is not None:
            self.stream.seek(self.offset)

    def read(self, size=None, stream=None):
        if stream is None:
            stream = self.stream
            if stream is None:
                raise ValueError("File not open for reading.")
        if size is None:
            size = self.length
        return stream.read(min(size, self.length))

    def seek(self, offset, whence=os.SEEK_SET):
        if self.offset is not None:
            offset += self.offset
        self.stream.seek(offset, whence)

    def tell(self):
        offset = self.stream.tell()
        if self.offset is not None:
            offset -= self.offset
        return offset
