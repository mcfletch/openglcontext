"""fonttools-based direct extraction of TTF outlines

Most of the complexity of this module has been refactored
into the ttfquery package, which provides for finding
system fonts, generating registries of available fonts,
querying metadata regarding a particular font/glyph etc.
"""
from fontTools import ttLib
from OpenGLContext.arrays import *
import weakref, sys
from ttfquery import describe, glyphquery
import logging
log = logging.getLogger( __name__ )

# don't have any specialisations as of yet, so just include it
from ttfquery.glyph import Glyph

class Font(object):
    """Holder for metadata regarding a particular font

    XXX Note: currently there is no distinction between the
        Context-specific metadata and the generic descriptions
        of the fonts.  For instance, there is no reason that
        the underlying glyph metadata needs to be queried for
        each quality level of a given font (only the outlines
        need to be regenerated), and the outlines themselves
        are not actually dependent on the context, so they can
        be shared across contexts, with only the display lists
        not being shareable.
    """
    defaultGlyphClass = Glyph
    encoding = None
    def __init__(self, filename, encoding = None, glyphClass = None, quality=3 ):
        """Initialize the font

        filename -- a file source from which to load
            the .ttf file, must be a simple local filename,
            not a URL or font-name.
        encoding -- the TrueType encoding specifier, the
            specifier is two elements, a PlatformID and
            a platform-specific ID code (sub encoding).
            http://developer.apple.com/fonts/TTRefMan/RM06/Chap6name.html#ID
            the default should be the Unicode Roman if
            I've done my homework correctly.

            (0,0) or (0,3) -- Unicode (default or Unicode 2.0
            semantics respectively), I have no fonts with which
            to test this encoding.
            (3,1) -- Latin-1 Microsoft encoding, while
            (1,0) should be the Mac-Roman encoding. You will
            almost certainly want (3,1) on windows, and I'm
            guessing (1,0) on Mac.
        glyphClass -- the class used for creating new glyphs,
            if not provided, self.defaultGlyphClass is used.
        quality -- rendering quality for the font, the number
            of integration steps for each quadratic curve in
            the font definition.
        """
        # character: Glyph instance
        self.glyphs = {}
        # glyphName: Glyph instance (short-circuits creation where == glyphs)
        self.glyphNames = {}
        self.filename = filename
        self.encoding = encoding
        self.quality = quality
        self.glyphClass = glyphClass or self.defaultGlyphClass
        self.withFont( self._generalMetadata )

    def withFont( self, callable, *arguments, **named ):
        """Call a callable while we have a .font attribute

        This method opens the font file and then calls the given
        callable object.  On exit, it eliminates the font.

        XXX Currently this is not reentrant :( 
        """
        if __debug__:
            log.info( """Opening TrueType font %r with fonttools""", self.filename)
        self.font = describe.openFont( self.filename )
        try:
            return callable( *arguments, **named )
        finally:
            try:
                del self.font
            except AttributeError:
                pass

    def _generalMetadata( self ):
        """Load general meta-data for this font (called via withFont)

        Guess the appropriate encoding, query line height,
        and character height.
        """
        try:
            self.encoding = describe.guessEncoding( self.font, self.encoding )
            self.lineHeight = glyphquery.lineHeight( self.font )
            self.charHeight = glyphquery.charHeight( self.font )
        except Exception:
            log.error( """Unable to load TrueType font from %r""", self.filename)
            raise
    def countGlyphs( self, string ):
        """Count the number of glyphs from string present in file"""
        return self.withFont( self._countGlyphs, string )
    def _countGlyphs( self, string ):
        count = 0
        set = {}
        for character in string:
            set[ glyphquery.explicitGlyph( self.font, character )] = 1
        return len(set)
    def ensureGlyphs( self, string ):
        """Retrieve set of glyphs for the string from file into local cache

        (Optimization), take all glyphs represented by the string
        and compile each glyph not currently available with a
        single opening of the font file.
        """
        needed = []
        for character in string:
            if not character in self.glyphs:
                needed.append( character )
        if needed:
            self.withFont( self._createGlyphs, needed )
        return len(needed)
    def _createGlyphs( self, set ):
        """Create glyphs for the sequence of passed characters (called via withFont)"""
        for character in set:
            self._createGlyph( character, self.quality )
    def getGlyph( self, character ):
        """Retrieve the appropriate glyph for this character

        Returns a compiled glyph for the given character in
        this font.
        """
        if not character in self.glyphs:
            self.withFont( self._createGlyph, character, self.quality )
        return self.glyphs.get (character)
    def _createGlyph( self, character, quality ):
        """Load glyph outlines from font-file (called via withFont)"""
        if __debug__:
            log.info( """Retrieving glyph for character %r""", character)
        glyphName = glyphquery.glyphName( self.font, character, self.encoding )
        if glyphName in self.glyphNames:
            # whadda-ya-know, it's the same glyph as another character
            glyph = self.glyphNames[ glyphName ]
            self.glyphs[character] = glyph
            return glyph
        glyph = self.glyphClass(
            glyphName
        )
        glyph.compile( self.font, steps = quality )
        self.glyphs[character] = glyph
        self.glyphNames[ glyphName ] = glyph
        return glyph
        
    def __repr__( self ):
        """Provide a representation of the Font"""
        return """%s( %r, %r )"""% (
            self.__class__.__name__,
            self.filename,
            self.encoding,
        )



if __name__ == "__main__":
    import os, glob, traceback
    testText = [ unicode(chr(x),'latin-1') for x in range(32,256)]
    def scan( directory = os.path.join( os.environ['windir'], 'fonts')):
        files = glob.glob( os.path.join(directory, "*.ttf"))
        errors = []
        for file in files:
            error = (file, [])
            print '\nFile', file
            try:
                font = Font(
                    file,
                )
            except Exception, err:
                traceback.print_exc()
                error[1].append( (file, "Couldn't load"))
            else:
                for character in testText:
                    try:
                        font.getGlyph(character)
                    except Exception, err:
                        traceback.print_exc()
                        error[1].append( (file, "Character %r failed, aborting font %r"%(character,file)))
                        break
            if error[1]:
                errors.append( error )
        return errors

    errors = scan()
    print '__________________________'
    for file,msgs in errors:
        print 'File', file
        print "\n".join(msgs)

    
