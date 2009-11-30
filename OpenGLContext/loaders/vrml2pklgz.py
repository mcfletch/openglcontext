"""Convert a VRML97 file to a gzpickle file"""

usage = """vrml2pklgz.py sourcefile destfile

Loads the sourcefile as VRML97 and writes the
result to destfile as a gzipped pickle file.
"""

if __name__ == "__main__":
    import sys, time
    try:
        source, destination = sys.argv[1:]
    except ValueError:
        print usage
        print 'Got arguments', sys.argv[1:]
    else:
        from OpenGLContext.loaders import vrml97, gzpickle
        print 'loading from', source
        sg = vrml97.load( source )
        if not sg:
            print """Loaded a NULL scenegraph %s from %s, not writing target"""%( sg, source )
        else:
            print 'Loaded', sg
            print 'Pausing for a while to let images load'
            time.sleep( 3 )
            print 'Saving to', destination
            gzpickle.dump( sg, destination )
    print 'Exiting'