User's guide
============

This is the primary documentation for the database. It uses an
interactive narrative which doubles as a doctest.

You can run the tests by issuing the following command at the
command-line prompt::

$ python setup.py test

Setup
-----

The first step is to connect the database to storage. The database
storage layer is abstracted; included with the database is an
implementation which logs transactions to a file, optimized for
long-running processes, e.g. application servers.

To configure the transaction log, we simply provide a path. It needn't
point to an existing file; upon the first commit to the database, the
file will be created.

>>> from dobbin.storage import TransactionLog
>>> storage = TransactionLog(database_path)

We pass the storage to the database constructor for initialization.

>>> from dobbin.database import Database
>>> db = Database(storage)

The database is empty to begin; we can verify this by using the
``len`` method to determine the number of objects stored.

>>> len(db)
0

This object database uses an object graph persistency model, that is,
all persisted objects must be connected to the same graph. Connected
in this context means that another connected object owns a
Python-reference to it.

The empty database has no elected root object; if we ask for it, we
simply get ``None`` as the answer.

>>> db.get_root() is None
True

Setting the root
----------------

Any persistent object can be elected as the database root
object. Persistent objects must inherit from the ``Persistent``
class. These objects form the basis of the concurrency model;
overlapping transactions may write a disjoint set of objects (conflict
resolution mechanisms are available to ease this requirement).

>>> from dobbin.persistent import Persistent
>>> obj = Persistent()

Persistent objects are read-only by default; the state (dict) is
shared between threads. It is not difficult to use or abuse this in
general, but we do prevent setting attributes on objects in shared
state to manifest this point.

>>> obj.name = "John"
Traceback (most recent call last):
 ...
RuntimeError: Can't set attribute in read-only mode.

If we use the ``checkout`` method on the object, its state changes
from read-only to thread-local.

>>> from dobbin.persistent import checkout
>>> checkout(obj)

.. warning:: Applications must check out objects before changing their state.

The object identity is never changed, but the object state is masked
by a thread-local dictionary.

>>> obj.name = 'John'
>>> obj.name
'John'

When an object is first checked out by some thread, a counter is set
to keep track of how many threads have checked out the object. When it
falls to zero (always on a transaction boundary), it's retracted to
the previous shared state.

Electing a database root
------------------------

We can elect this object as the root of the database.

>>> db.set_root(obj)
>>> obj._p_oid
0

The object is now the root of the object graph. To persist changes on
disk, we commit the transaction.

>>> transaction.commit()

As expected, the database contains one object.

>>> len(db)
1

The storage layer should report that a single transaction has been
logged.

>>> len(storage)
1

Transactions
------------

The transaction log always appends data; it will grow with every
transaction.

>>> checkout(obj)
>>> obj.name = 'James'
>>> transaction.commit()

Verify transaction count.

>>> len(storage)
2

Sharing the database
--------------------

While the database is inherently thread-safe, it's up to the storage
layer to manage sharing between instances (which may run in different
processes; no distinction is made). The transaction log may be shared
transparently between processes; no configuration is required.

To illustrate the point in a simple environment, let's configure a
second instance which runs in the same thread.

>>> new_storage = TransactionLog(database_path)
>>> new_db = Database(new_storage)

Objects from this database are new instances, too. The object graphs
between different database instances are disjoint.

>>> new_obj = new_db.get_root()
>>> new_obj is obj
False

Transactions propagate between instances of the same database.

>>> new_obj.name
'James'

Let's examine this further. If we checkout the persistent object from
the first database instance and commit the changes, the same object
from the second database will be updated when we enter a new
transaction.

>>> checkout(obj)
>>> obj.name = 'Jane'
>>> transaction.commit()
>>> len(storage)
3

At this point, the second database won't be up-to-date.

>>> new_obj.name
'James'

When we enter a new transaction, the two instances will again be in
sync.

>>> tx = transaction.begin()
>>> new_obj.name
'Jane'

Conflicts
---------

When two threads try to make changes to the same objects, we have a
write conflict. One thread is guaranteed to win; with conflict
resolution, both may.

.. note:: There is no built-in conflict resolution in the persistent base class.

In a new thread, we check out an object, make changes to it, then wait
for a semaphore before we commit.

>>> from threading import Semaphore
>>> flag = Semaphore()

>>> def run():
...     checkout(obj)
...     obj.name = 'Bob'
...     flag.acquire()
...     transaction.commit()
...     flag.release()

>>> from threading import Thread
>>> thread = Thread(target=run)

>>> flag.acquire()
True

>>> thread.start()

We do the same in the main thread.

>>> checkout(obj)
>>> obj.name = 'Bill'

Releasing the semaphore, the thread will attempt to commit the
transaction.

>>> flag.release()
>>> thread.join()

The transaction was committed.

>>> len(storage)
4

Trying to commit the transaction in the main thread, we get a write
conflict.

>>> transaction.commit()
Traceback (most recent call last):
 ...
WriteConflictError...

The commit failed; this has implications beyond the exception being
raised. A transaction record was written to disk.

>>> len(storage)
5

Checked out objects have been reverted to the state of the most recent
transaction.

>>> obj.name
'Bob'

We must abort the failed transaction explicitly.

>>> transaction.abort()

When all threads are done with an object they've previously checked
out, its state is retracted to shared. To verify this, we try and set
an attribute on it.

>>> obj.name = "John"
Traceback (most recent call last):
 ...
RuntimeError: Can't set attribute in read-only mode.

Two threads each belonging to different processes can conflict too,
obviously. We can simulate two processes by again opening a new
thread, but this time use the second database instance.

We begin a new transaction such that both database instances are
up-to-date.

>>> tx = transaction.begin()

Confirm that the storages are indeed up-to-date (and have registered
the same number of transactions).

>>> len(storage) == len(new_storage)
True

>>> def run():
...     checkout(new_obj)
...     new_obj.name = 'Ian'
...     flag.acquire()
...     transaction.commit()
...     flag.release()

>>> thread = Thread(target=run)

>>> flag.acquire()
True

>>> thread.start()

We do the same in the main thread.

>>> checkout(obj)
>>> obj.name = 'Ilya'

Releasing the semaphore, the thread will attempt to commit the
transaction.

>>> flag.release()
  >>> thread.join()

The transaction was committed.

>>> len(new_storage)
6

If try to commit the transaction in the main thread, we get a read
conflict; the reason why it's not a write conflict is that the storage
first catches up on new transactions which causes a read conflict.

>>> transaction.commit()
Traceback (most recent call last):
 ...
ReadConflictError...

Again, the failed transaction is recorded.

>>> len(storage)
7

The state of the object reflects the transaction which was committed
in the thread.

>>> obj.name
'Ian'

We clean up from the failed transaction.

>>> transaction.abort()

More objects
------------

When objects are added to the object graph, they are automatically
persisted.

>>> another = Persistent()
>>> checkout(another)
>>> another.name = 'Karla'

>>> checkout(obj)
>>> obj.another = another

We commit the transaction and observe that the object count has
grown. The new object has been assigned an oid as well (these are not
in general predictable; they are assigned by the storage).

>>> transaction.commit()
>>> len(db)
2

>>> another._p_oid is not None
True

As we check out the object that carries the reference and access any
attribute, a deep-copy of the shared state is made behind the
scenes. Persistent objects are never copied, however, which a simple
identity check will confirm.

>>> checkout(obj)
>>> obj.another is another
True

Circular references are permitted.

>>> checkout(another)
>>> another.another = obj
>>> transaction.commit()

Again, we can verify the identity.

>>> another.another is obj
True

Storing files
-------------

We can persist open files (or any stream object) by enclosing them in
a *persistent file* wrapper. The wrapper is immutable; it's for single
use only.

>>> from tempfile import TemporaryFile
>>> file = TemporaryFile()
>>> file.write('abc')
>>> file.seek(0)

Note that the file is read from the current position and until the end
of the file.

>>> from dobbin.persistent import PersistentFile
>>> pfile = PersistentFile(file)

Let's store this persistent file as an attribute on our object.

>>> checkout(obj)
>>> obj.file = pfile
>>> transaction.commit()

Note that the persistent file has been given a new class by the
storage layer. It's the same object (in terms of object identity), but
since it's now stored in the database and is only available as a file
stream, we call it a *persistent stream*.

>>> obj.file
<dobbin.storage.PersistentStream object at ...>

We must manually close the file we provided to the persistent wrapper
(or let it fall out of scope).

>>> file.close()

Using persistent streams
------------------------

There are two ways to use persistent streams; either by iterating
through it, in which case it automatically gets a file handle
(implicitly closed when the iterator is garbage-collected), or through
a file-like API.

We use the ``open`` method to open the stream; this is always
required when using the stream as a file.

>>> obj.file.open()
>>> obj.file.read()
'abc'

The ``seek`` and ``tell`` methods work as expected.

>>> obj.file.tell()
3L

We can seek to the beginning and repeat the exercise.

>>> obj.file.seek(0)
>>> obj.file.read()
'abc'

As any file, we have to close it after use.

>>> obj.file.close()

In addition we can use iteration to read the file; in this case, we
needn't bother opening or closing the file. This is automatically done
for us. Note that this makes persistent streams suitable as return
values for WSGI applications.

>>> "".join(obj.file)
'abc'

Iteration is strictly independent from the other methods. We can
observe that the file remains closed.

>>> obj.file.closed
True

Cleanup
-------

>>> transaction.commit()

This concludes the narrative.
