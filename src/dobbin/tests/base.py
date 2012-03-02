import unittest
import tempfile
import transaction

class BaseTestCase(unittest.TestCase):
    def setUp(self):
        transaction.abort()
        transaction.begin()
        from dobbin.database import Database
        self._tempfile = tempfile.NamedTemporaryFile()
        self.database = Database(self._tempfile.name)

    def tearDown(self):
        self._tempfile.close()
        tx = transaction.get()
        transaction.manager.free(tx)
        self.database.close()
