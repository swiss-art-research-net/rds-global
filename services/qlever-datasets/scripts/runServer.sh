#!/bin/bash
name="$1"
port="${2:-7001}"

cd "/index/$name" || exit 1
ServerMain --i "$name" -p "$port" -a 123 -t --memory-max-size "10 GB"