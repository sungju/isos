#!/bin/bash

if [ "$1" == "clean" ]; then
	sh ./make_clean.sh
fi

python isos.py
