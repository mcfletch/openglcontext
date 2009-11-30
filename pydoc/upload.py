if __name__ == "__main__":
    import os
    os.system( 'tar -cvf site.tar *.html')
    os.system( 'gzip site.tar' )
    os.system( 'scp site.tar.gz mcfletch@shell.sourceforge.net:/home/groups/p/py/pyopengl/htdocs/pydoc' )
    os.remove( 'site.tar.gz' )
    print "ssh -l mcfletch pyopengl.sourceforge.net"
    print "cd /home/groups/p/py/pyopengl/htdocs/pydoc/"