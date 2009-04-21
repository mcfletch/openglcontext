"""Utilities for processing arrays of vectors"""
from OpenGLContext.arrays import *
import math

def crossProduct( set1, set2):
	"""Compute element-wise cross-product of two arrays of vectors.
	
	set1, set2 -- sequence objects with 1 or more
		3-item vector values.  If both sets are
		longer than 1 vector, they must be the same
		length.
	
	returns a double array with x elements,
	where x is the number of 3-element vectors
	in the longer set
	"""
	set1 = asarray( set1, 'f')
	set1 = reshape( set1, (-1, 3))
	set2 = asarray( set2, 'f')
	set2 = reshape( set2, (-1, 3))
	ux = set1[:,0]
	uy = set1[:,1]
	uz = set1[:,2]
	vx = set2[:,0]
	vy = set2[:,1]
	vz = set2[:,2]
	result = zeros( (len(set1),3), typeCode(set1))
	result[:,0] = (uy*vz)-(uz*vy)
	result[:,1] = (uz*vx)-(ux*vz)
	result[:,2] = (ux*vy)-(uy*vx)
	return result

def crossProduct4( set1, set2 ):
	"""Cross-product of 3D vectors stored in 4D arrays

	Identical to crossProduct otherwise.
	"""
	set1 = asarray( set1, 'f',)
	set1 = reshape( set1, (-1, 4))
	set2 = asarray( set2, 'f',)
	set2 = reshape( set2, (-1, 4))
	ux = set1[:,0]
	uy = set1[:,1]
	uz = set1[:,2]
	uw = set1[:,3]
	vx = set2[:,0]
	vy = set2[:,1]
	vz = set2[:,2]
	vw = set1[:,3]
	result = zeros( (len(set1),4), typeCode(set1))
	result[:,0] = (uy*vz)-(uz*vy)
	result[:,1] = (uz*vx)-(ux*vz)
	result[:,2] = (ux*vy)-(uy*vx)
	return result
	

def magnitude( vectors ):
	"""Calculate the magnitudes of the given vectors
	
	vectors -- sequence object with 1 or more
		3-item vector values.
	
	returns a double array with x elements,
	where x is the number of 3-element vectors
	"""
	vectors = asarray( vectors,'f')
	if not (len(shape(vectors))==2 and shape(vectors)[1] in (3,4)):
		vectors = reshape( vectors, (-1,3))
	vectors = vectors*vectors
	# should just use sum?
	result = vectors[:,0]
	add( result, vectors[:,1], result )
	add( result, vectors[:,2], result )
	sqrt( result, result )
	return result
def normalise( vectors ):
	"""Get normalised versions of the vectors.
	
	vectors -- sequence object with 1 or more
		3-item vector values.
	
	returns a double array with x 3-element vectors,
	where x is the number of 3-element vectors in "vectors"

	Will raise ZeroDivisionError if there are 0-magnitude
	vectors in the set.
	"""
	vectors = asarray( vectors, 'f')
	vectors = reshape( vectors, (-1,3)) # Numpy 23.7 and 64-bit machines fail here, upgrade to 23.8
	mags = reshape( magnitude( vectors ), (-1, 1))
	mags = where( mags, mags, 1.0)
	return divide_safe( vectors, mags)

def colinear( points ):
	"""Given 3 points, determine if they are colinear

	Uses the definition which says that points are collinear
	iff the distance from the line for point c to line a-b
	is non-0 (that is, point c does not lie on a-b).

	returns None or the first 
	"""
	if len(points) >= 3:
		a,b,c = points[:3]
		cp = crossProduct(
			(b-a),
			(a-c),
		)
		if magnitude( cp )[0] < 1e-6:
			return (a,b,c)
	return None


