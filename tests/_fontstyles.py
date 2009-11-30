from OpenGLContext.scenegraph.basenodes import FontStyle
majorAlign = [
    FontStyle(
        family = ["Arial Bold", "Arial", "SANS"],
        justify = ["BEGIN"],
        size = 1.0,
    ),
    FontStyle(
        justify = ["MIDDLE"],
    ),
    FontStyle(
        justify = ["END"],
    ),
    FontStyle(
        justify = ["BEGIN"],
        topToBottom=0,
    ),
    FontStyle(
        justify = ["MIDDLE"],
        topToBottom=0,
    ),
    FontStyle(
        justify = ["END"],
        topToBottom=0,
    ),
##	FontStyle(
##		justify = ["BEGIN"],
##		leftToRight=0,
##	),
##	FontStyle(
##		justify = ["MIDDLE"],
##		leftToRight=0,
##	),
##	FontStyle(
##		justify = ["END"],
##		leftToRight=0,
##	),
]
minorAlign = [
    FontStyle(
        justify = ["BEGIN", "BEGIN"],
        spacing = 2.0,
    ),
    FontStyle(
        justify = ["BEGIN", "FIRST"],
        spacing = 2.0,
    ),
    FontStyle(
        justify = ["BEGIN", "MIDDLE"],
        spacing = 2.0,
    ),
    FontStyle(
        justify = ["BEGIN", "END"],
        spacing = 2.0,
    ),
]
minorAlignReverse = [
    FontStyle(
        justify = ["BEGIN", "BEGIN"],
        spacing = 2.0,
        topToBottom=0,
    ),
    FontStyle(
        justify = ["BEGIN", "FIRST"],
        spacing = 2.0,
        topToBottom=0,
    ),
    FontStyle(
        justify = ["BEGIN", "MIDDLE"],
        spacing = 2.0,
        topToBottom=0,
    ),
    FontStyle(
        justify = ["BEGIN", "END"],
        spacing = 2.0,
        topToBottom=0,
    ),
]