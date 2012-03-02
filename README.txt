Overview
========

Dobbin is a fast and convenient way to persist a Python object graph
on disk.

  The object graph consists of *persistent nodes*, which are objects
  that are based on one of the persistent base classes::

    from dobbin.persistent import Persistent

    foo = Persistent()
    foo.bar = 'baz'

  Each of these nodes can have arbitrary objects connected to it; the
  only requirement is that Python's `pickle
  <http://docs.python.org/library/pickle.html>`_ module can serialize
  the objects.

  Persistent objects are fully object-oriented::

    class Frobnitz(Persistent):
        ...

  The object graph is built by object reference::

    foo.frob = Frobnitz()

  To commit changes to disk, we use the ``commit()`` method from the
  `transaction <http://pypi.python.org/pypi/transaction>`_
  module. Note that we must first elect a root object, thus connecting
  the object graph to the database handle::

    from dobbin.database import Database

    jar = Database('data.fs')
    jar.elect(foo)

    transaction.commit()

  Consequently, if we want to make changes to one or more objects in
  the graph, we must first *check out* the objects in question::

    from dobbin.persistent import checkout

    checkout(foo)
    foo.bar = 'boz'

    transaction.commit()

  The ``checkout(obj)`` function puts the object in *shared* state. It
  only works on object that are persistent nodes.

Dobbin is available on Python 2.6 and up including Python 3.x.

Key features:

- 100% Python, fully compliant with `PEP8 <http://www.python.org/dev/peps/pep-0008/>`_
- Threads share data when possible
- Multi-threaded, multi-process `MVCC
  <http://en.wikipedia.org/wiki/Multiversion_concurrency_control>`_
  concurrency model
- Efficient storage and streaming of binary blobs
- Pluggable architecture

Getting the code
----------------

You can `download <http://pypi.python.org/pypi/Dobbin#downloads>`_ the
package from the Python package index or install the latest release
using setuptools or the newer `distribute
<http://packages.python.org/distribute/>`_ (required for Python 3.x)::

  $ easy_install dobbin

Note that this will install the `transaction
<http://pypi.python.org/pypi/transaction>`_ module as a package
dependency.

The project is hosted in a `GitHub repository
<http://github.com/malthe/dobbin>`_. Code contributions are
welcome. The easiest way is to use the `pull request
<http://help.github.com/pull-requests/>`_ interface.


Author and license
------------------

Written by Malthe Borch <mborch@gmail.com>.

This software is made available under the BSD license.
