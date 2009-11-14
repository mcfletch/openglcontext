#! /bin/bash

rsync -avP -e ssh *.html mcfletch,pyopengl@web.sourceforge.net:htdocs/pydoc/
