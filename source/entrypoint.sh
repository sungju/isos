#!/bin/bash

if [ "$1" == "clean" ]; then
	sh ./make_clean.sh
fi

python3 -m venv .
MYOS="$OSTYPE"
if ( test "$MYOS" = "msys" ); then
	source Scripts/activate.bat
else
	. bin/activate
fi

pip3 install wheel > /dev/zero 2>&1
python3 setup.py bdist_wheel  > /dev/zero 2>&1

pip3 install -r requirements.txt > /dev/zero 2>&1

python3 isos.py
