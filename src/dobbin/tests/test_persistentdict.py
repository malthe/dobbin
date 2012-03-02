from dobbin.tests.base import BaseTestCase

import transaction

class PersistentDictTestCase(BaseTestCase):
    def _get_root(self):
        assert self.database.root is None
        from dobbin.persistent import PersistentDict
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
        from dobbin.persistent import checkout
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

        from dobbin.persistent import checkout
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

    def test_pop(self):
        d = self._get_root()

        # local
        d['bar'] = 'foo'
        self.assertEqual(d.pop('bar'), 'foo')
        self.assertRaises(KeyError, d.pop, 'bar')
        self.assertEqual(d.pop('bar', 'boo'), 'boo')

        # shared
        transaction.commit()
        self.assertFalse('bar' in d)

        # local
        from dobbin.persistent import checkout
        checkout(d)
        d['bar'] = 'foo'

        # shared
        transaction.commit()

        # local
        checkout(d)
        self.assertEqual(d.pop('bar'), 'foo')
        self.assertFalse('bar' in d)

        # shared
        transaction.commit()
        self.assertFalse('bar' in d)

    def test_popitem(self):
        d = self._get_root()

        # local
        d['bar'] = 'foo'
        self.assertEqual(d.popitem(), ('bar', 'foo'))
        self.assertRaises(KeyError, d.popitem)
        self.assertEqual(d.pop('bar', 'boo'), 'boo')

        # shared
        transaction.commit()
        self.assertFalse('bar' in d)

        # local
        from dobbin.persistent import checkout
        checkout(d)
        d['bar'] = 'foo'

        # shared
        transaction.commit()

        # local
        checkout(d)
        self.assertEqual(d.popitem(), ('bar', 'foo'))
        self.assertFalse('bar' in d)

        # shared
        transaction.commit()
        self.assertFalse('bar' in d)

    def test_setdefault(self):
        d = self._get_root()

        d.setdefault('bar', 'boo')
        self.assertEqual(d['bar'], 'boo')

    def test_update(self):
        d = self._get_root()

        # local
        d.update({'bar': 'boo'})
        self.assertEqual(d['bar'], 'boo')

        # shared
        transaction.commit()
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
        self.assertEqual(set(d.keys()), set(['foo']))
        self.assertEqual(set(d.items()), set((('foo', 'bar'),)))
        self.assertEqual(tuple(d), ('foo',))

        # local
        from dobbin.persistent import checkout
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

    def test_type(self):
        d = self._get_root()
        self.assertTrue(isinstance(d, dict))

        # shared
        transaction.commit()
        self.assertTrue(isinstance(d, dict))
