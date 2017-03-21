#!/usr/bin/env bash

# Quote nesting works as described here: http://stackoverflow.com/a/6612417/4972
# SCRIPT_DIR via http://www.ostricher.com/2014/10/the-right-way-to-get-the-directory-of-a-bash-script/
SCRIPT_DIR="$( cd "$( dirname "${BASH_SOURCE[0]}" )" && pwd )"

. $SCRIPT_DIR/release.sh


compare_hash() {
    git checkout "$WATCH_BRANCH"
    CURRENT_HASH=$(git rev-parse $WATCH_BRANCH)
    [[ "$CURRENT_HASH" == "$RELEASE_HASH" ]]
}

fetch_release_hash() {
    RELEASE_HASH=$(curl "$HASH_URL")
    if [[ ${#RELEASE_HASH} -ne 40 ]];
    then
        error "Error: expected release hash from $HASH_URL"
        error "but got: $RELEASE_HASH"
        exit 1
    fi
}

main() {
    fetch_release_hash
    validate_dependencies
    create_working_dir
    while ! compare_hash
    do
        sleep 30
        fetch_release_hash
    done
    echo "Hashes match, deployment was successful"
    delete_working_dir
}

if [[ $(basename $0) = "wait_for_deploy.sh" ]]; then
    set -euf -o pipefail

    # Default variables to empty if not present. Necessary due to the -u option specified above.
    # For more information on this, look here:
    # http://redsymbol.net/articles/unofficial-bash-strict-mode/#solution-positional-parameters

    # These need to be defined to something to be referenced, but ${1:-} will be empty if it's not supplied
    REPO_DIR="${1:-}"
    HASH_URL="${2:-}"
    WATCH_BRANCH="${3:-}"

    if [[ -z "$REPO_DIR" ]]; then
        error "You must specify your git repo directory as the first argument."
        exit 1
    fi

    if [[ "$HASH_URL" != https* ]]; then
        error "You must specify a hash URL to compare with the release candidate."
        error "For example, for micromasters https://micromasters-rc.herokuapp.com/static/hash.txt"
        exit 1
    fi

    if [[ -z "$WATCH_BRANCH" ]]
    then
        error "You must specify a branch whose latest commit will match the deployed hash"
        error "for example release-candidate or release"
        exit 1
    fi

    # make into absolute path
    REPO_DIR="$(cd "$REPO_DIR"; pwd)"

    main
fi