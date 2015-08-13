#! /usr/bin/env python
from __future__ import print_function
import numpy

def main():
    a = numpy.zeros(3, dtype=[
        ('position', [('x','1f'),('y','1f'),('z','1f')]),
        ('normal', [('x','1f'),('y','1f'),('z','1f')]),
        ('texCoord',[('s','1f'),('t','1f')])
    ])
    print(a)
    print(a['position'])
    print(a['normal'])
    print(a['texCoord'])
    print(a['position']['x'])

if __name__ == "__main__":
    main()
