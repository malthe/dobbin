import time
import threading

def make_timestamp():
    return time.time()

class localset(threading.local):
    def __init__(self):
        self.items = set()

    def __len__(self):
        return len(self.items)

    def add(self, obj):
        self.items.add(obj)

    def clear(self):
        self.items.clear()

    def pop(self):
        return self.items.pop()

