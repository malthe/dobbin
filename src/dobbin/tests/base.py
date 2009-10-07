import unittest
import tempfile
import transaction

class BaseTestCase(unittest.TestCase):
    def setUp(self):
        from dobbin.database import Database
        self._tempfile = tempfile.NamedTemporaryFile()
        self.database = Database(self._tempfile.name)

    def tearDown(self):
        self._tempfile.close()
        transaction.abort()
