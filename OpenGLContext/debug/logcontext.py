import traceback
fh = open( 'callcontext.txt','w')

def logContext():
    """Log the calling context to the context log-file"""
    for (file,line,func,lineText) in traceback.extract_stack()[:-1]:
        fh.write( "%(func)s %(file)s:%(line)s %(lineText)s\n"%locals())
    fh.write('____________________________________________\n')
    