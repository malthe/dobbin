from dobbin.tests.base import BaseTestCase
from dobbin.persistent import PersistentDict
from dobbin.persistent import checkout

import transaction

class PersistentDictTestCase(BaseTestCase):
    def _get_root(self):
        assert self.database.root is None
        root = PersistentDict()
        self.database.elect(root)
        return root

    def test_assignment(self):
        d = self._get_root()

        # local
        d['foo'] = 'bar'
        self.assertEqual(d['foo'], 'bar')

        # shared
        transaction.commit()
        self.assertEqual(d['foo'], 'bar')

        # local
        checkout(d)
        d['bar'] = 'boo'
        self.assertEqual(d['foo'], 'bar')
        self.assertEqual(d['bar'], 'boo')

        # shared
        transaction.commit()
        self.assertEqual(d['foo'], 'bar')
        self.assertEqual(d['bar'], 'boo')

    def test_clear(self):
        d = self._get_root()

        # local
        d['bar'] = 'foo'
        transaction.commit()
        checkout(d)
        d.clear()
        self.assertEqual(d.get('bar'), None)

        # shared
        transaction.commit()
        self.assertEqual(d.get('bar'), None)

        # local
        checkout(d)
        d.clear()
        self.assertEqual(d.get('boo'), None)
        d['boo'] = 'foo'
        self.assertEqual(d.get('boo'), 'foo')

        # shared
        transaction.commit()
        self.assertEqual(d.get('boo'), 'foo')

    def test_get(self):
        d = self._get_root()

        self.assertEqual(d.get('bar'), None)
        self.assertEqual(d.get('bar', 'boo'), 'boo')

        d['bar'] = 'foo'
        self.assertEqual(d.get('bar'), 'foo')
        self.assertEqual(d.get('bar', 'boo'), 'foo')

    def test_setdefault(self):
        d = self._get_root()

        d.setdefault('bar', 'boo')
        self.assertEqual(d['bar'], 'boo')

    def test_iteration(self):
        d = self._get_root()

        # local
        d['foo'] = 'bar'
        self.assertEqual(d.keys(), ['foo'])
        self.assertEqual(d.items(), [('foo', 'bar')])
        self.assertEqual(tuple(d), ('foo',))

        # shared
        transaction.commit()
        self.assertEqual(d.keys(), ['foo'])
        self.assertEqual(d.items(), [('foo', 'bar')])
        self.assertEqual(tuple(d), ('foo',))

        # local
        checkout(d)
        d['bar'] = 'boo'
        self.assertEqual(sorted(d.keys()), ['bar', 'foo'])
        self.assertEqual(sorted(d.items()), [('bar', 'boo'), ('foo', 'bar')])
        self.assertEqual(tuple(sorted(d)), ('bar', 'foo',))

        # shared
        transaction.commit()
        self.assertEqual(sorted(d.keys()), ['bar', 'foo'])
        self.assertEqual(sorted(d.items()), [('bar', 'boo'), ('foo', 'bar')])
        self.assertEqual(tuple(sorted(d)), ('bar', 'foo',))
