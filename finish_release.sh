#!/usr/bin/env bash

. ./release.sh

merge_release_candidate (){
    echo "Merge release-candidate into release"
    git checkout -t origin/release
    git merge origin/release-candidate
    git push
}

tag_release () {
    echo "Tag release..."
    git tag -a -m "Release $VERSION" v$VERSION
    git push --follow-tags
}

merge_release () {
    echo "Merge release to master"
    git checkout -q master
    git pull
    git merge release
    git push
}

main () {
    validate_dependencies
    create_working_dir
    merge_release_candidate
    tag_release
    delete_working_dir
}

if [[ $(basename $0) = "finish_release.sh" ]]; then
    set -euf -o pipefail

    # Default variables to empty if not present. Necessary due to the -u option specified above.
    # For more information on this, look here:
    # http://redsymbol.net/articles/unofficial-bash-strict-mode/#solution-positional-parameters

    # These need to be defined to something to be referenced, but ${1:-} will be empty if it's not supplied
    REPO_DIR="${1:-}"
    VERSION="${2:-}"

    if [[ -z "$REPO_DIR" ]]; then
        error "You must specify your git repo directory as the first argument."
        exit 1
    fi

    if [[ -z "$VERSION" ]]; then
        error "You must specify a version as the second argument."
        exit 1
    fi

    # make into absolute path
    REPO_DIR="$(cd "$REPO_DIR"; pwd)"

    main
fi