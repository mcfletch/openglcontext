#! /bin/bash

rsync -avP -e ssh ./tutorials/* mcfletch,pyopengl@web.sourceforge.net:htdocs/context/tutorials/
