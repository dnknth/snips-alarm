#!/bin/sh

set -e

VENV="venv"

if which python3 > /dev/null ; then

    # Create a virtual environment if it doesn't exist.
    [ -d $VENV ] || $PYTHON -m venv $VENV

    # Activate the virtual environment and install requirements.
    . $VENV/bin/activate
    pip3 install -r requirements.txt
else
    >&2 echo "Cannot find Python3. Please install it."
fi

# Create empty config.ini if it does not exist.
[ -f config.ini ] || touch config.ini
