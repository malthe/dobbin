import os
import sys
import tempfile
import transaction

from time import time
from dobbin.tests.base import BaseTestCase

def report_stat(data):
    sys.stderr.write("%s - " % data)

def timing(func, *args, **kwargs):
    t1 = t2 = time()
    i = 0
    while t2 - t1 < 0.4:
        func(*args, **kwargs)
        i += 1
        t2 = time()
    return i, float(t2-t1)/i


class Benchmark(BaseTestCase):
    def _get_root(self, cls):
        assert self.database.root is None
        root = cls()
        self.database.elect(root)
        return root

    def test_commit_many_dobbin(self):
        """Commit (many): Dobbin"""

        from dobbin.persistent import Persistent
        from dobbin.persistent import checkout

        root = self._get_root(Persistent)
        transaction.commit()

        size = os.path.getsize(self._tempfile.name)

        def benchmark():
            transaction.begin()
            items = [Persistent() for i in range(1000)]
            for item in items:
                item.name = 'Bob'
            checkout(root)
            root.items = items
            transaction.commit()

        i, t = timing(benchmark)
        size = os.path.getsize(self._tempfile.name) - size
        report_stat("%0.1f ms (%d kb)" % ((t*1000), size/1024/i))

    def test_commit_single_dobbin(self):
        """Commit (single): Dobbin"""

        from dobbin.persistent import Persistent
        items = [Persistent() for i in range(10000)]
        root = self._get_root(Persistent)
        root.items = items
        transaction.commit()

        from dobbin.persistent import checkout

        items = list(root.items)

        size = os.path.getsize(self._tempfile.name)

        def benchmark():
            transaction.begin()
            item = items.pop()
            checkout(item)
            item.name1 = 'Bob'
            item.name2 = 'Bill'
            item.ref = item
            transaction.commit()

        i, t = timing(benchmark)

        size = os.path.getsize(self._tempfile.name) - size
        report_stat("%0.1f ms (%d bytes)" % ((t*1000), size/i))
        transaction.abort()

    def test_commit_dict_update_dobbin(self):
        """Commit (update dict): Dobbin"""

        from dobbin.persistent import PersistentDict
        root = self._get_root(PersistentDict)
        transaction.commit()

        from dobbin.persistent import checkout

        size = os.path.getsize(self._tempfile.name)

        def benchmark():
            transaction.begin()
            checkout(root)
            root[None] = "abc"
            transaction.commit()

        i, t = timing(benchmark)
        size = os.path.getsize(self._tempfile.name) - size
        report_stat("%0.1f ms (%d bytes)" % ((t*1000), size/i))
