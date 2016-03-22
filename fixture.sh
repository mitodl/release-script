#!/bin/bash
# Extract test repo for fixture purposes.
set -e

if [ -x test-repo ]; then
    rm -rf test-repo
fi

(
    mkdir test-repo
    cd test-repo
    git init
    cat ../test-repo.gz | gunzip | git fast-import --quiet
    git checkout --quiet master
)
