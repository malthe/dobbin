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

Persistent objects
------------------

Any persistent object can be elected as the database root
object. Persistent objects must inherit from the ``Persistent``
class. These objects form the basis of the concurrency model;
overlapping transactions may write a disjoint set of objects (conflict
resolution mechanisms are available to ease this requirement).

>>> from dobbin.persistent import Persistent
>>> obj = Persistent()

Persistent objects begin life in *local* state. In this state we can
both read and write attributes. However, when we want to write to an
object which has previously been persisted in the database, we must
check it out explicitly using the ``checkout`` method. We will see how
this works shortly.

>>> obj.name = 'John'
>>> obj.name
'John'

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

Checking out objects
--------------------

The object is now persisted in the database. This means that we must
now check it out before we are allowed to write to it.

>>> obj.name = "John"
Traceback (most recent call last):
 ...
TypeError: Can't set attribute on shared object.

We use the ``checkout`` method on the object to change its state to
local.

>>> from dobbin.persistent import checkout
>>> checkout(obj)

.. warning:: Applications must check out already persisted objects before changing their state.

The ``checkout`` method does not have a return value; this is because
the object identity never actually changes. Instead custom attribute
accessor and mutator methods are used to provide a thread-local object
state. This happens transparent to the user.

After checking out the object, we can both read and write attributes.

>>> obj.name = 'James'

When an object is first checked out by some thread, a counter is set
to keep track of how many threads have checked out the object. When it
falls to zero (always on a transaction boundary), it's retracted to
the previous shared state.

>>> transaction.commit()

This increases the transaction count by one.

>>> db.tx_count
2

Concurrency
-----------

The object manager (which implements the low-level functionality) is
inherently thread-safe; it uses the MMVC concurrency model.

It's up to the database which sits on top of the object manager to
support concurrency between external processes sharing the same
database (the included database implementation uses a file-locking
scheme to extend the MVCC concurrency model to external processes; no
configuration is required).

We can demonstrate concurrency between two separate processes by
running a second database instance in the same thread.

>>> new_db = Database(database_path)
>>> new_obj = new_db.root

Objects from this database are disjoint from those of the first
database.

>>> new_obj is obj
False

The new database instance has already read the previously committed
transactions and applied them to its object graph.

>>> new_obj.name
'James'

Let's examine this further. If we check out a persistent object from
the first database instance and commit the changes, that same object
from the second database will be updated as soon as we begin a new
transaction.

>>> checkout(obj)
>>> obj.name = 'Jane'
>>> transaction.commit()

The database has registered the transaction; the new instance hasn't.

>>> db.tx_count - new_db.tx_count
1

The object graphs are not synchronized.

>>> new_obj.name
'James'

Applications must begin a new transaction to stay in sync.

>>> tx = transaction.begin()
>>> new_obj.name
'Jane'

Conflicts
---------

When concurrent transactions attempt to modify the same objects, we
get a write conflict in all but one (first to get the commit-lock wins
the transaction).

Objects can provide conflict resolution capabilities such that two
concurrent transactions may update the same object.

.. note:: There is no built-in conflict resolution in the persistent base class.

As an example, let's create a counter object; it could represent a
counter which keeps track of visitors on a website. To provide
conflict resolution for instances of this class, we implement a
``_p_resolve_conflict`` method.

>>> class Counter(Persistent):
...     def __init__(self):
...         self.count = 0
...
...     def hit(self):
...         self.count += 1
...
...     @staticmethod
...     def _p_resolve_conflict(old_state, saved_state, new_state):
...         saved_diff = saved_state['count'] - old_state['count']
...         new_diff = new_state['count']- old_state['count']
...         return {'count': old_state['count'] + saved_diff + new_diff}

As a doctest technicality, we set the class on the builtin module.

>>> import __builtin__; __builtin__.Counter = Counter

Next we instantiate a counter instance, then add it to object graph.

>>> counter = Counter()
>>> checkout(obj)
>>> obj.counter = counter
>>> transaction.commit()

To demonstrate the conflict resolution functionality of this class, we
update the counter in two concurrent transactions. We will attempt one
of the transactions in a separate thread.

>>> from threading import Semaphore
>>> flag = Semaphore()
>>> flag.acquire()
True

>>> def run():
...     counter = db.root.counter
...     assert counter is not None
...     checkout(counter)
...     counter.hit()
...     flag.acquire()
...     try: transaction.commit()
...     finally: flag.release()

>>> from threading import Thread
>>> thread = Thread(target=run)
>>> thread.start()

In the main thread we check out the same object and assign a different
attribute value.

>>> checkout(counter)
>>> counter.count
0
>>> counter.hit()

Releasing the semaphore, the thread will commit the transaction.

>>> flag.release()
>>> thread.join()

As we commit the transaction running in the main thread, we expect the
counter to have been increased twice.

>>> transaction.commit()
>>> counter.count
2

More objects
------------

Persistent objects must be connected to the object graph, before
they're persisted in the database. If we check out a persistent object
and commit the transaction without adding it to the object graph, an
exception is raised.

>>> another = Persistent()
>>> transaction.commit()
Traceback (most recent call last):
 ...
ObjectGraphError: <dobbin.persistent.LocalPersistent object at ...> not connected to graph.

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
3

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

We can use the ``snapshot`` method to merge all database transactions
until a given timestamp and write the snapshot as a single transaction
to a new database.

>>> tmp_path = "%s.tmp" % database_path
>>> tmp_db = Database(tmp_path)

To include all transactions (i.e. the current state), we just pass the
target database.

>>> db.snapshot(tmp_db)

The snapshot contains three objects.

>>> len(tmp_db)
4

They were persisted in a single transaction.

>>> tmp_db.tx_count
1

We can confirm that the state indeed matches that of the current
database.

>>> tmp_obj = tmp_db.root

The object graph is equal to that of the original database.

>>> tmp_obj.name
'Jane'
>>> tmp_obj.another.name
'Karla'
>>> tmp_obj.pdict['obj'] is tmp_obj
True
>>> tmp_obj.pdict.name
'Bob'

Binary streams are included in the snapshot, too.

>>> "".join(tmp_obj.file)
'abc'

Cleanup
-------

>>> transaction.commit()

This concludes the narrative.
