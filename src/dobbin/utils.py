import time

from dobbin.persistent import Persistent

marker = object()

def assert_persistent(obj):
    if not isinstance(obj, Persistent):
        raise TypeError("Only first-class persistent object may be added.")

def make_timestamp():
    return time.time()

class lazy(property):
    def __init__(self, cls):
        self.cls = cls

    def __get__(self, inst, cls):
        prop = "state%d" % id(self)
        value = inst.__dict__.get(prop, marker)
        if value is marker:
            value = inst.__dict__[prop] = self.cls()
        return value
