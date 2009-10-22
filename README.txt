Overview
========

Dobbin is a transactional object database for Python (2.6+). It's a
fast and convenient way to persist Python objects on disk.

Key features:

- MVCC concurrency model
- Implemented all in Python
- Multi-thread, multi-process with no configuration
- Zero object access overhead in general case
- Optimal memory sharing between threads
- Efficient storing and serving of binary streams
- Architecture open to alternative storages

Author and license
------------------

Written by Malthe Borch <mborch@gmail.com>.

This software is made available under the BSD license.

Source
------

The source code is kept in version control. Use this command to
anonymously check out the latest project source code::

  svn co http://svn.repoze.org/dobbin/trunk dobbin



