"""Provides array data to draw a "flower"
"""
from OpenGLContext.arrays import asarray, take, contiguous
points = asarray([
    [1.000,0.000,0.000],
    [0.959,0.282,0.000],
    [0.841,0.541,0.000],
    [0.655,0.756,0.000],
    [0.415,0.910,0.000],
    [0.142,0.990,0.000],
    [-0.142,0.990,0.000],
    [-0.415,0.910,0.000],
    [-0.655,0.756,0.000],
    [-0.841,0.541,0.000],
    [-0.959,0.282,0.000],
    [-1.000,0.000,0.000],
    [-0.959,-0.282,0.000],
    [-0.841,-0.541,0.000],
    [-0.655,-0.756,0.000],
    [-0.415,-0.910,0.000],
    [-0.142,-0.990,0.000],
    [0.142,-0.990,0.000],
    [0.415,-0.910,0.000],
    [0.655,-0.756,0.000],
    [0.841,-0.541,0.000],
    [0.959,-0.282,0.000],
    [0.000,0.000,0.500],
], 'd')
indices =  asarray([
    22, 1, 2, 22, 3, 4, 22, 5, 6, 22, 7, 8, 22, 9, 10, 22, 11, 12,
    22, 13, 14, 22, 15, 16, 22, 17, 18, 22, 19, 20, 22, 21, 0], 'I')

points_expanded = contiguous( take( points, indices, 0 ))

normals = asarray([
    [-0.127,-0.433,0.892],
    [0.244,0.379,0.892],
    [0.410,0.187,0.892],
    [0.000,0.451,0.892],
    [-0.244,0.379,0.892],
    [-0.410,0.187,0.892],
    [0.446,-0.064,0.892],
    [0.341,-0.295,0.892],
    [0.000,0.000,1.000],
    [-0.446,-0.064,0.892],
    [0.127,-0.433,0.892],
    [-0.341,-0.295,0.892],
], 'f')
normalIndices = asarray([
    8, 2, 2, 8, 1, 1, 8, 3, 3, 8, 4, 4, 8, 5, 5, 8, 9, 9, 8, 11,
    11, 8, 0, 0, 8, 10, 10, 8, 7, 7, 8, 6, 6], 'i')

normals_expanded = contiguous(take( normals, normalIndices, 0 ))