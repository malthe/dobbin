import time

MARKER = object()


def make_timestamp():
    return time.time()


class marker(object):
    def __deepcopy__(self, memo):
        return self


class default_property(property):
    def __init__(self, key, value):
        def get(self, value=value):
            return self.__dict__.get(key, value)
        property.__init__(self, get)


def add_class_properties(cls, local_cls, d):
    flattened = set()
    for base in local_cls.mro():
        for key, value in base.__dict__.items():
            flattened.add((key, value))

    attrs = {}
    bases = cls.mro()
    for base in reversed(bases):
        attrs.update(base.__dict__)

    for key, value in attrs.items():
        if key == '__qualname__':
            continue

        if (key, value) in flattened:
            continue

        if not hasattr(value, '__get__'):
            value = default_property(key, value)

        d[key] = value
