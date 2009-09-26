Overview
========

Dobbin is a transactional object database for Python. It's a fast and
convenient way to persist Python objects on disk.

Key features:

- Multi-thread, multi-process with no configuration
- Persistent objects carry no overhead in general case
- Threads share most object data
- Does not attempt to manage memory
- Implemented all in Python
- Efficient storing and serving of binary streams

Author and license
------------------

Written by Malthe Borch <mborch@gmail.com>.

This software is made available under the BSD license.

Source
------

The source code is kept in version control. Use this command to
anonymously check out the latest project source code::

svn co http://svn.repoze.org/dobbin/trunk dobbin


