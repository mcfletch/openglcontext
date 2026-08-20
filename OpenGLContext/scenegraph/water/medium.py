"""What a substance does to a body inside it.

Water is a *medium*, not a texture. What it looks like from outside and what it
does to something in it are two views of one substance, and keeping them apart
is why every game that has water ends up writing the second half itself.

A :class:`Medium` is that second half: how far you can see through it, what
colour the view closes to, how much of the mix's high end it takes, and what it
costs per second to be there. It is deliberately small -- four numbers and a
name -- because it is the part a *game* has to be able to write, and a table it
cannot read is a table it will replace.

**Being inside something is not a coloured pane over the screen.** It is a
medium with depth in it: what is in your hands is clear and the far wall is
not, and a flat tint treats them alike. That is why the visibility is a
distance and why :mod:`OpenGLContext.scenegraph.water.submersion` spends it on
a :class:`~OpenGLContext.scenegraph.fog.Fog` rather than on an overlay.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Dict, Iterable, Optional, Tuple

__all__ = ['Medium', 'MEDIA', 'WATER', 'SLIME', 'LAVA', 'UNKNOWN',
           'medium_for', 'worst_of', 'SEVERITY']

#: The three substances the games have. Spelled as a Quake III shader's
#: ``surfaceparm`` spells them, because that is where one game reads them from
#: and a second spelling would be a translation table nobody maintains.
WATER = 'water'
SLIME = 'slime'
LAVA = 'lava'


@dataclass(frozen=True)
class Medium:
    """One substance, from the inside.

    ``color`` is what the view closes to and ``visibility`` how many metres it
    takes to close, both in **linear** terms: the fog blends in linear HDR
    before tone mapping, so a colour that reads as a pleasant mid-blue written
    down arrives on screen far brighter than the level around it. A fog that
    makes distant walls *brighter* is a fog lamp and not a body of water, so
    these numbers are much darker than the surface of water looks from above.

    ``muffle`` is how much of the mix's high end goes, 0 clear to 1 fully
    damped -- never 1, because total silence reads as the sound having broken
    rather than as being under water. ``harm`` is health per second, and a
    substance that does not hurt says so with a zero rather than by being
    absent from the table.
    """

    name: str
    color: Tuple[float, float, float]
    visibility: float
    muffle: float
    harm: float = 0.0


#: What each substance does. These numbers are the games' own -- nothing in any
#: specification says how far you can see through slime -- and they are meant to
#: be looked at and adjusted.
#:
#: Water is dark and close rather than a pale haze: a long range and a light
#: colour give *fog*, which is air with something in it, and the difference is
#: that water **absorbs** -- it takes the light out of what you are looking at
#: rather than adding a veil in front of it. Slime is thicker and sicklier
#: still. Lava is opaque and closer than arm's length, because you cannot see
#: through molten rock and somebody who has fallen into it should be in no
#: doubt which of the three they are in.
MEDIA: Dict[str, Medium] = {
    WATER: Medium(name=WATER, color=(0.004, 0.022, 0.030), visibility=9.0,
                  muffle=0.75, harm=0.0),
    SLIME: Medium(name=SLIME, color=(0.012, 0.030, 0.006), visibility=4.5,
                  muffle=0.85, harm=12.0),
    LAVA: Medium(name=LAVA, color=(0.55, 0.12, 0.03), visibility=2.0,
                 muffle=0.90, harm=32.0),
}

#: What a substance nobody declared is taken to be. A world may name one this
#: table has no entry for, and reading that as dry air is the one wrong answer:
#: whatever it is, the body is inside something.
UNKNOWN = MEDIA[WATER]

#: The substances **worst first**. A body may span several, and whoever is in
#: them needs to hear about the one that will hurt them rather than the one
#: that happened to be found first.
SEVERITY: Tuple[str, ...] = (LAVA, SLIME, WATER)


def medium_for(name: Optional[str]) -> Optional[Medium]:
    """The substance ``name`` is, or None for dry air.

    An empty name is air and is the only thing that is; anything else is
    something, even if this table has never heard of it.
    """
    if not name:
        return None
    return MEDIA.get(str(name), UNKNOWN)


def worst_of(names: Iterable[str]) -> str:
    """Whichever of several substances matters most, or ``''`` for none.

    One nobody declared is taken seriously rather than discarded: it ranks
    after the ones that are known, because there is nothing to say it is worse
    and something to say it is not air.
    """
    found = [name for name in names if name]
    if not found:
        return ''
    for known in SEVERITY:
        if known in found:
            return known
    return found[0]
