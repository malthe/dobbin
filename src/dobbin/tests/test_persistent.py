from dobbin.tests.base import BaseTestCase

class PersistentTestCase(BaseTestCase):
    def _get_root(self, cls):
        assert self.database.root is None
        root = cls()
        self.database.elect(root)
        return root

    def test_class_attribute(self):
        from dobbin.persistent import Persistent
        class Dummy(Persistent):
            dummy = 0

        from dobbin.tests import test_persistent as module
        module.Dummy = Dummy

        try:
            inst = self._get_root(Dummy)

            # local
            self.assertEqual(inst.dummy, 0)

            # shared
            import transaction
            transaction.commit()
            self.assertEqual(inst.dummy, 0)

            # local
            from dobbin.persistent import checkout
            checkout(inst)
            inst.dummy += 1
            self.assertEqual(inst.dummy, 1)

            # shared
            transaction.commit()
            self.assertEqual(inst.dummy, 1)
        finally:
            del module.Dummy

    def test_custom_setattr(self):
        marker = []
        from dobbin.persistent import Persistent
        class Dummy(Persistent):
            def __setattr__(self, key, value):
                marker.append(key)
                super(Dummy, self).__setattr__(key, value)

        from dobbin.tests import test_persistent as module
        module.Dummy = Dummy

        try:
            inst = self._get_root(Dummy)

            # local
            inst.dummy = 1
            self.assertEqual(inst.dummy, 1)
            self.assertEqual(marker[-1], 'dummy')
            del marker[:]

            # shared
            import transaction
            transaction.commit()
            self.assertEqual(inst.dummy, 1)

            # local
            from dobbin.persistent import checkout
            checkout(inst)
            inst.dummy += 1
            self.assertEqual(inst.dummy, 2)
            self.assertEqual(marker[-1], 'dummy')
            del marker[:]

            # shared
            transaction.commit()
            self.assertEqual(inst.dummy, 2)
        finally:
            del module.Dummy
