User's guide
============

This is the primary documentation for the database. It uses an
interactive narrative which doubles as a doctest.

You can run the tests by issuing the following command at the
command-line prompt::

$ python setup.py test

Setup
-----

The database stores transactions in a single file. It's optimized for
long-running processes, e.g. application servers.

The first step is to initialize a database object. To configure it we
provide a path on the file system. The path needn't exist already.

>>> from dobbin.database import Database
>>> db = Database(database_path)

This particular path does not already exist. This is a new
database. We can verify it by using the ``len`` method to determine
the number of objects stored.

>>> len(db)
0

The database uses an object graph persistency model. Objects must be
transitively connected to the root node of the database (by Python
reference).

Since this is an empty database, there is no root object yet.

>>> db.root is None
True

Checking out an object
----------------------

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

The ``checkout`` does not have a return value; this is because the
object identity never actually changes. Instead the attribute accessor
and mutator methods are used to provide a thread-local object
state. This happens transparent to the user.

After checking out the object, we can both read and write attributes.

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

>>> db.elect(obj)
>>> obj._p_jar is db
True

The object is now the root of the object graph. To persist changes on
disk, we commit the transaction.

>>> transaction.commit()

As expected, the database contains one object.

>>> len(db)
1

The ``tx_count`` attribute returns the number of transactions which
have been written to the database (successful and failed).

>>> db.tx_count
1

Transactions
------------

The transaction log always appends data; it will grow with every
transaction.

>>> checkout(obj)
>>> obj.name = 'James'
>>> transaction.commit()

Verify transaction count.

>>> db.tx_count
2

Sharing the database
--------------------

The object manager (which implements the low-level functionality) is
inherently thread-safe. It's up to the database which sits on top of
the object manager to support sharing between external actors.

The included implementation support sharing transparently (using file
locking); no configuration is required.

To illustrate this in a simple environment, we'll configure a second
instance which runs in the same thread.

>>> new_db = Database(database_path)

Objects from this database are new instances, too. The object graphs
between different database instances are disjoint.

>>> new_obj = new_db.root
>>> new_obj is obj
False
>>> new_obj._p_jar is new_db
True

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
>>> db.tx_count
3

At this point, the second database won't be up-to-date.

>>> new_obj.name
'James'

When we enter a new transaction, the two instances will again be in
sync.

>>> tx = transaction.begin()
>>> new_obj.name
'Jane'

Internal conflicts
------------------

When two threads try to make changes to the same objects, we have a
write conflict. One thread is guaranteed to win; with conflict
resolution, both may.

.. note:: There is no built-in conflict resolution in the persistent base class.

In a new thread, we check out the root object, make changes to it,
then wait for a semaphore before we commit.

>>> from threading import Semaphore
>>> flag = Semaphore()

>>> def run():
...     obj = db.root
...     assert obj is not None
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

>>> db.tx_count
4

Trying to commit the transaction in the main thread, we get a write
conflict.

>>> transaction.commit()
Traceback (most recent call last):
 ...
WriteConflictError...

The commit failed; this has implications beyond the exception being
raised. A transaction record was written to disk.

>>> db.tx_count
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

External conflicts
------------------

Two threads each belonging to different processes can conflict too,
obviously. We can simulate two processes by again opening a new
thread, but this time use the second database instance.

We begin a new transaction such that both database instances are
up-to-date.

>>> tx = transaction.begin()

Confirm that the databases are indeed up-to-date (and have registered
the same number of transactions).

>>> db.tx_count == new_db.tx_count
True

>>> def run():
...     new_obj = new_db.root
...     assert new_obj is not None
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

>>> new_db.tx_count
6

If we attempt a commit in the main thread, a read conflict is raised;
the reason why it's not a write conflict is that the database first
catches up on new transactions.

>>> transaction.commit()
Traceback (most recent call last):
 ...
ReadConflictError...

Again, the failed transaction is recorded.

>>> db.tx_count
7

The state of the object reflects the transaction which was committed
in the thread.

>>> obj.name
'Ian'

We clean up from the failed transaction.

>>> transaction.abort()

More objects
------------

Persistent objects must be connected to the object graph, before
they're persisted in the database. If we check out a persistent object
and commit the transaction without adding it to the object graph, an
exception is raised.

>>> another = Persistent()
>>> checkout(another)
>>> transaction.commit()
Traceback (most recent call last):
 ...
ObjectGraphError: <dobbin.persistent.Persistent object at ...> not connected to graph.

We abort the transaction and try again, this time connecting the
object using an attribute reference.

>>> transaction.abort()
>>> checkout(another)
>>> another.name = 'Karla'
>>> checkout(obj)
>>> obj.another = another

We commit the transaction and observe that the object count has
grown. The new object has been assigned an oid as well (these are not
in general predictable; they are assigned by the database on commit).

>>> transaction.commit()
>>> len(db)
2

>>> another._p_oid is not None
True

If we begin a new transaction, the new object will propagate to the
second database instance.

>>> tx = transaction.begin()
>>> new_obj.another.name
'Karla'

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

Note that the persistent file has been given a new class. It's the
same object (in terms of object identity), but since it's now stored
in the database and is only available as a file stream, we call it a
*persistent stream*.

>>> obj.file
<dobbin.database.PersistentStream object at ...>

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

>>> int(obj.file.tell())
3

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

Start a new transaction (to prompt database catch-up) and confirm that
file is available from second database.

>>> tx = transaction.begin()
>>> "".join(new_obj.file)
'abc'

Persistent dictionary
---------------------

It's not advisable in general to use the built-in ``dict`` type to
store records in the database, in particular not if you expect
frequent minor changes. Instead the ``PersistentDict`` class should be
used (directly, or subclassed).

It operates as a normal Python dictionary and provides the same
methods.

>>> from dobbin.persistent import PersistentDict
>>> pdict = PersistentDict()

Check out objects and connect to object graph.

>>> checkout(obj)
>>> checkout(pdict)
>>> obj.pdict = pdict

You can store any key/value combination that works with standard
dictionaries.

>>> pdict['obj'] = obj
>>> pdict['obj'] is obj
True

The ``PersistentDict`` stores attributes, too. Note that attributes
and dictionary entries are independent from each other.

>>> pdict.name = 'Bob'
>>> pdict.name
'Bob'

Committing the changes.

>>> transaction.commit()
>>> pdict['obj'] is obj
True
>>> pdict.name
'Bob'

Snapshots
---------

We can use the ``snapshot`` method to merge transactions until a given
timestamp and write a snapshot of the database state as a single
transaction.

>>> tmp_path = "%s.tmp" % database_path
>>> tmp_db = Database(tmp_path)

To include all transactions (i.e. the current state), we just pass the
target database.

>>> db.snapshot(tmp_db)

The snapshot contains three objects.

>>> len(tmp_db)
3

They were persisted in a single transaction.

>>> tmp_db.tx_count
1

We can confirm that the state indeed matches that of the current
database.

>>> tmp_obj = tmp_db.root
>>> tmp_obj.name
'Ian'

>>> tmp_obj.another.name
'Karla'

>>> "".join(tmp_obj.file)
'abc'

Cleanup
-------

>>> transaction.commit()

This concludes the narrative.
