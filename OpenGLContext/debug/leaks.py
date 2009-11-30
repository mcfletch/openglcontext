"""Utility mechanism to watch for memory leaks over time"""
import gc

whole_set = {}
def init():
    for object in gc.get_objects():
        whole_set[id(object)] = True 

def delta():
    for object in gc.get_objects():
        if not whole_set.get( id(object)):
            print 'new', type( object ), object
        whole_set[id(object)] = True 