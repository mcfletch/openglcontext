"""Object which manages the registration and deregistration of timed event generators"""
import systemtime

class TimeEventGeneratorManager(object):
    """TimeEventGenerator EventManager object

    This object conforms to the EventManager interface,
    although it doesn't actually inherit from that class.

    It provides support for the InternalTime generators
    on which the Timer object is based.
    """
    def __init__( self ):
        """Initialize the TimeEventGeneratorManager"""
        self.__generators = []
    def addEventGenerator( self, generator ):
        """Add a new generator to the list of generators

        This adds the event generator to the internal list of
        generators, which will keep the generator alive.
        """
        if generator not in self.__generators:
            self.__generators.append( generator )
    def removeEventGenerator( self, generator ):
        """Remove a generator from the list of generators"""
        while generator in self.__generators:
            self.__generators.remove( generator )
    def __call__( self, client ):
        """Poll each event-generator with a simulation time value
        
        Each generator dispatches resulting events.

        Return value is total number of events generated.
        """
        realTime = systemtime.systemTime()
        total = 0
        for generator in self.__generators:
            total = total + generator.poll( realTime )
        return total
        