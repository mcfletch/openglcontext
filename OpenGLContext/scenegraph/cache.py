"""Caching mechanism for scene graph

Basically, the scenegraph Cache allows you to associate
data with particular nodes in the scene graph without
actually attaching the information to the particular
node being annotated.

This allows us to store cached information such as:
	display list objects
	texture objects
	compiled array geometry

The cache uses weak reference key dictionaries to clear
the cache of data associated with deleted nodes within
the scene graph.  similarly, cache is cleared when node
fields which are dependencies of the cache are changed.

The cache is based on the vrml.field and dispatch.dispatcher
modules.  All field objects by default provide dispatcher
notifications on set and delete, and can provide
notification on get as well.  The cache watches for these
notifications for dependent nodes where the dispatcher
messages are (type, fieldObject) for type in ("set","del").

There is a per-context cache, and a global cache, display-
lists, textures, etceteras should be stored in the per-
context cache, while data with dependencies only on the
node can be stored in the global cache.

Note:
	The cache makes extensive use of weak references, and
	was the failure case which exposed a number of problems
	with the Python 2.2.2 weakref and weakkeydictionary
	mechanisms.
"""
from vrml import field, protofunctions
import weakref
#from vrml.weakkeydictfix import WeakKeyDictionary
from pydispatch import dispatcher
import weakref, traceback

class Cache (dict):
	"""Trivial sub-class of a dict which has some convenience methods

	Maps id(client): {
		key="": CacheHolder()
	}

	That is, for each client node, a dictionary
	holds opaque key(normally strings) to CacheHolder
	instances.  The CacheHolder is responsible for
	most of the implementation of the cache.
	"""
	def getHolder( self, client, key = ""):
		"""Return the cache holder for the given client and key"""
		current = self.get(id(client))
		if current is not None:
			return current.get( key)
		return None
	def getData( self, client, key="", default=None):
		"""Return the data for given client and key, default otherwise"""
		current = self.get( id(client) )
		if current is not None:
			current = current.get( key )
			if current is not None:
				return current.data
		return default
	def holder(
		self, 
		client,
		data,
		key="",
	):
		"""Create a new CacheHolder in this cache"""
		return CacheHolder(
			client,
			data,
			key,
			self,
		)

CACHE = Cache()
getData = CACHE.getData

def cleaner( cache, id ):
	"""Return callback function that cleans the given id from cache"""
	def clean_id( weak ):
		try:
			del cache[id]
		except Exception, err:
			pass 
	return clean_id


class CacheHolder( object ):
	"""Holder for data values within a cache

	The CacheHolder provides the bulk of the cache
	implementation.  It associates an opaque data value
	with a client node and an opaque key.  The key
	value allows multiple dimensions of storage, to
	allow, for instance storing compiled shadow
	information separate from compiled geometry
	information.

	The depend method uses the dispatcher module
	to invalidate this CacheHolder when the given
	fields for the given nodes are changed.

	Attributes:
		client -- weak reference to the client node
		key -- strong reference to the opaque key value
		data -- strong reference to the opaque data value
		cache -- weak reference to the cache in which
			we are storing ourselves
	"""
	#__slots__ = ('client','data','key','cache','nodeDependencies','__weakref__','notifier')
	def __init__(
		self,
		client, data,
		key="",
		cache = CACHE,
	):
		"""Initialise the cache-deletion callable
		
		client -- the node doing the caching, if gc'd,
			then the entire cache for the node is deleted
		key -- opaque key into the cache's per-node storage
		cache -- the particular cache in which to store
			ourselves.
		"""
		client_id = id(client)
		self.client = weakref.ref(client, cleaner( cache,client_id) )
		self.key = key
		self.data = data
		self.cache = weakref.ref( cache )
		self.nodeDependencies = []

		# get the cached values for this client node
		set = cache.get(client_id, None)
		if set is None:
			cache[ client_id ] = set = {}
		set[key] = self
	
	def depend( self, node, field=None ):
		"""Add a dependency on given node's field value

		source -- the node being watched
		field -- the field on the node being watched

		Dependency on the node means that this cache
		holder will be invalidated if the field value
		changes.  This does not create a dependency
		on the existence of node, so you should set
		the dependency for the field holding any
		nodes which should invalidate this CacheHolder

		Note:
			This does not affect any other CacheHolder
			for our client node.
		"""
		if field is not None:
			if isinstance( field, (str,unicode)):
				field = protofunctions.getField(node, field)
			dispatcher.connect(
				self, # receiver
				('set', field),#signal
				node, # sender
			)
			dispatcher.connect(
				self, # receiver
				('del', field),#signal
				node, # sender
			)
			dispatcher.connect(
				self, # receiver
				('route', field),#signal
				node, # sender
			)
		else:
			# dependency on the mere existence of the node
			self.nodeDependencies.append(
				weakref.ref(
					node,
					self,
				)
			)
	def __call__( self, signal=None, sender=None ):
		"""Delete the cached value (this object)

		This de-registers ourselves from our cache object,
		with suitable checks for whether our cache is still
		alive itself, and whether it still has an entry
		for our client and our key.

		If this is the last registered cache object
		for our client, deletes the overall cache dictionary
		for the client.
		"""
		try:
			cache = self.cache()
			if cache is None:
				return 0
			client = self.client()
			if client is None:
				return 0
			client_id = id(client)
			current = cache.get( client_id )
			if current is None:
				return 0
			try:
				del current[ self.key ]
				if not current:
					try:
						del cache[ client_id ]
					except KeyError:
						pass
				try:
					del self.nodeDependencies[:]
				except:
					pass
				return 1
			except KeyError:
				return 0
		except RuntimeError, err:
			traceback.print_exc()
			
