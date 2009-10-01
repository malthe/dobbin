import unittest
import tempfile

class BaseTestCase(unittest.TestCase):
    def setUp(self):
        from dobbin.storage import TransactionLog
        self._tempfile = tempfile.NamedTemporaryFile()
        storage = TransactionLog(self._tempfile.name)
        from dobbin.database import Database
        self.database = Database(storage)

    def tearDown(self):
        self._tempfile.close()
