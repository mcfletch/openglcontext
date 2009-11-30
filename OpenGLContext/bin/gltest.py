#! /usr/bin/env python
"""Automated test runner for OpenGLContext contexts"""
import optparse,sys,os, logging, ConfigParser
log = logging.getLogger( 'gltest' )
from OpenGLContext import testingcontext, context, plugins

def main():
    """Do the test for the passed elements"""
    parser = optparse.OptionParser()
    parser.add_option(
        '-c',
        '--config',
        action = "append",
        type = "string",
        dest = "configs",
        default = None,
    )
    parser.add_option(
        '-s',
        '--script',
        action = "store",
        type = "string",
        dest = "script",
        default = None,
    )
    parser.add_option(
        '-o',
        '--output',
        action = "store",
        type = "string",
        dest = "output",
        default = "test-results",
    )
    options, args = parser.parse_args( sys.argv[1:] )
    if not options.script:
        if args:
            options.script = args[0]
    script = os.path.abspath( options.script )
    log.info( 'Script: %s', script )
    if not os.path.exists( script ):
        log.error( """Couldn't find script file: %s""", script )
    script_name = os.path.splitext(os.path.basename( script ))[0]
    
    ref_name = os.path.join( options.output, '%(script_name)s-ref.png'%locals() )
    if not os.path.exists( ref_name ):
        output_name = ref_name
        log.warn( 'Recording reference image for %s', script_name )
    else:
        output_name = os.path.join( options.output, '%(script)s-new.png' )
    
    if options.configs:
        configs = [c for c in options.configs if c]
    else:
        configs = []
    if configs:
        cfg = ConfigParser.ConfigParser()
        cfg.read( *configs )
        cls = context.Context.fromConfig( cfg )
    else:
        cls = context.Context.getContextType( 'pygame', plugins.VRMLContext )
    if cls is None:
        cls = context.Context.getContextType( None, plugins.VRMLContext )
    class SaveAndExit( cls ):
        """Context which exits after the first rendering pass"""
        frame_count = 0
        def OnDraw( self, *args, **named ):
            super( SaveAndExit, self ).OnDraw( *args, **named )
            self.frame_count += 1
            if self.frame_count > 2:
                self.setCurrent()
                width,height = self.OnSaveImage(
                    template = output_name,
                    script = script_name,
                    overwrite=True,
                )
                self.unsetCurrent()
                if ((not width) or (not height)):
                    log.warn( 'Did not write retrying' )
                sys.exit( 0 )
                os._exit( 0 )
    testingcontext.CONFIGURED_BASE = SaveAndExit
    # now, execute the script...
    try:
        os.makedirs( options.output )
    except (IOError,OSError), err:
        pass
    sys.path.insert(0, os.path.dirname(script))
    g = {}
    g['__name__'] = '__main__'
    g['__file__'] = script
    execfile( script, g )
    
if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    main()