#!/bin/sh

set -e

if which python3 > /dev/null ; then

    # Create a virtual environment if it doesn't exist.
    [ -d venv ] || python3 -m venv venv

    # Activate the virtual environment and install requirements.
    . venv/bin/activate
    pip3 install -r requirements.txt
else
    >&2 echo "Cannot find Python3. Please install it."
fi

# Create empty config.ini if it does not exist.
[ -f config.ini ] || touch config.ini
