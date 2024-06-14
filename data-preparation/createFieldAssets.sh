#!/bin/bash

while getopts u:p: flag
do
    case "${flag}" in
        u) username=${OPTARG};;
        p) password=${OPTARG};;
    esac
done

curl -u $username:$password -X POST "https://rds-smartup.swissartresearch.net/container/importResource?repository=assets&force=true&containerIRI=http%3A%2F%2Fwww.metaphacts.com%2Fontologies%2Fplatform%23rootContainer" -d @rds-local-field-definitions.trig --header "Content-Type: application/trig"