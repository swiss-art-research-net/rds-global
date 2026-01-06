#!/bin/bash
name="$1"

cd "/index/$name" || exit 1
ServerMain -i "$name" -p 7001 -a 123 -t