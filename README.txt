Overview
========

Dobbin is a transactional object database for Python (versions 2.6 and
up including Python 3.x). It's a fast and convenient way to persist
Python objects on disk.

Key features:

- MVCC concurrency model
- Implemented all in Python
- Multi-thread, multi-process with no configuration
- Zero object access overhead in general case
- Optimal memory sharing between threads
- Efficient storing and serving of binary streams
- Architecture open to alternative storages

Getting the code
----------------

You can `download <http://pypi.python.org/pypi/Dobbin#downloads>`_ the
package from the Python package index or install the latest release
using setuptools or the newer `distribute
<http://packages.python.org/distribute/>`_ (required for Python 3.x)::

  $ easy_install Dobbin

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
