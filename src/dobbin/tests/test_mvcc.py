from dobbin.tests.base import BaseTestCase

import transaction

class PersistentMVCCTestCase(BaseTestCase):
    def setUp(self):
        super(PersistentMVCCTestCase, self).setUp()
        import threading
        self._flag = threading.Semaphore()
        self._flag.acquire()

    def _get_root(self):
        assert self.database.root is None
        from dobbin.persistent import Persistent
        root = Persistent()
        self.database.elect(root)
        transaction.commit()
        return root

    def _get_thread(self, obj):
        flag = self._flag
        from dobbin.persistent import checkout

        def run():
            checkout(obj)
            obj.name = 'Bob'
            flag.acquire()
            try:
                transaction.commit()
            finally:
                flag.release()

        import threading
        thread = threading.Thread(target=run)
        thread.start()
        return thread

    def test_integrity(self):
        obj = self._get_root()
        thread = self._get_thread(obj)

        from dobbin.persistent import checkout
        checkout(obj)

        self._flag.release()
        thread.join()

        self.assertRaises(AttributeError, getattr, obj, 'name')

    def test_write_conflict(self):
        obj = self._get_root()
        thread = self._get_thread(obj)

        from dobbin.persistent import checkout
        checkout(obj)
        obj.name = 'Bill'

        self._flag.release()
        thread.join()

        from dobbin.exc import WriteConflictError
        self.assertRaises(WriteConflictError, transaction.commit)
        transaction.abort()

        self.assertEqual(obj.name, 'Bob')

    def test_read_conflict(self):
        from copy import copy
        obj = self._get_root()

        new_db = copy(obj._p_jar)
        thread = self._get_thread(new_db.root)

        from dobbin.persistent import checkout
        checkout(obj)
        obj.name = 'Bill'

        self._flag.release()
        thread.join()

        from dobbin.exc import ReadConflictError
        self.assertRaises(ReadConflictError, transaction.commit)
        transaction.abort()

        self.assertEqual(obj.name, 'Bob')

    def tearDown(self):
        self._flag.release()
        super(PersistentMVCCTestCase, self).tearDown()

class PersistentDictMVCCTestCase(PersistentMVCCTestCase):
    pass
