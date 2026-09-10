#! /usr/bin/env python
"""Automated test runner for OpenGLContext contexts"""

import configparser
import optparse
import sys
import os
import logging
from typing import Any, List, Optional, Sequence, Type

log = logging.getLogger("gltest")
from OpenGLContext import testingcontext, context, plugins


def readConfigs(configs: Sequence[str]) -> configparser.ConfigParser:
    """Read every named configuration file into one parser

    Later files win where two name the same option, which is what lets a
    machine-specific file be layered over a shared one.
    """
    cfg = configparser.ConfigParser()
    cfg.read(list(configs))
    return cfg


def contextClass(configs: Sequence[str]) -> Optional[Type[Any]]:
    """The context class the test should render in

    With no configuration file, the pygame VRML context is asked for, and the
    user's default backend where there is no pygame.
    """
    if configs:
        configured: Optional[Type[Any]] = context.Context.fromConfig(
            readConfigs(configs))
        return configured
    installed: Optional[Type[Any]] = (
        context.Context.getContextType("pygame", plugins.VRMLContext)
        or context.Context.getContextType(None, plugins.VRMLContext)
    )
    return installed


def saveAndExitClass(
    base: Type[Any],
    frames: int,
    template: str,
    script_name: str,
) -> Type[Any]:
    """A context class that saves a screenshot and exits after ``frames`` frames

    ``base`` is chosen at run time, from a configuration file or from the
    installed backends, so the class is built here rather than declared.
    """

    class SaveAndExit(base):
        """Context which exits after the Nth rendering pass"""

        target_frame_count = frames
        frame_count = 0

        def setupFrameRateCounter(self) -> None:
            """Don't want the frame-rate counter to mess up the diffs"""

        def OnDraw(self, *args: Any, **named: Any) -> Any:
            result = super(SaveAndExit, self).OnDraw(*args, **named)
            self.frame_count += 1
            if self.frame_count > self.target_frame_count:
                self.setCurrent()
                width, height = self.OnSaveImage(
                    template=template,
                    script=script_name,
                    overwrite=True,
                )
                self.unsetCurrent()
                if (not width) or (not height):
                    log.warning("Did not write retrying")
                sys.exit(0)
            self.triggerRedraw()
            return result

    return SaveAndExit


def parser() -> optparse.OptionParser:
    """The command's options"""
    result = optparse.OptionParser()
    result.add_option(
        "-c",
        "--config",
        action="append",
        type="string",
        dest="configs",
        default=None,
    )
    result.add_option(
        "-s",
        "--script",
        action="store",
        type="string",
        dest="script",
        default=None,
    )
    result.add_option(
        "-o",
        "--output",
        action="store",
        type="string",
        dest="output",
        default="test-results",
    )
    result.add_option(
        "-f",
        "--frame-count",
        action="store",
        type="int",
        dest="frame_count",
        default=3,
    )
    return result


def main(argv: Optional[List[str]] = None) -> int:
    """Do the test for the passed elements"""
    options, args = parser().parse_args(sys.argv[1:] if argv is None else argv)
    if not options.script:
        if args:
            options.script = args[0]
    if not options.script:
        log.error("""No script to run; pass one as an argument or with -s""")
        return 1
    script = os.path.abspath(options.script)
    log.info("Script: %s", script)
    if not os.path.exists(script):
        log.error("""Couldn't find script file: %s""", script)
        return 1
    script_name = os.path.splitext(os.path.basename(script))[0]

    # Absolute, so that the check for a reference image and the write of the
    # new one land in the same directory: a relative template is taken as a
    # name in the user's picture folder rather than in the current one.
    output = os.path.abspath(options.output)
    ref_name = os.path.join(output, "%s-ref.png" % (script_name,))
    if not os.path.exists(ref_name):
        template = ref_name
        log.warning("Recording reference image for %s", script_name)
    else:
        template = os.path.join(output, "%(script)s-new.png")

    configs = [c for c in (options.configs or []) if c]
    cls = contextClass(configs)
    if cls is None:
        log.error("""Couldn't load a context type to render in""")
        return 1

    # A checker reads CONFIGURED_BASE as None, which is what it holds until a
    # runner puts the class it wants every test context built on into it.
    testingcontext.CONFIGURED_BASE = saveAndExitClass(  # type: ignore[assignment]
        cls, options.frame_count, template, script_name,
    )
    # now, execute the script...
    os.makedirs(output, exist_ok=True)
    sys.path.insert(0, os.path.dirname(script))
    g = {}
    g["__name__"] = "__main__"
    g["__file__"] = script
    with open(script, 'rb') as f:
        exec(compile(f.read(), script, 'exec'), g)
    return 0


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    sys.exit(main())
