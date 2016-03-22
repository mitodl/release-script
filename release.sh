#!/bin/bash

# A script to automate the release process

# Usage
#   release working_dir version_num

[[ "${TRACE:-}" ]] && set -x

error () {  # error that writes to stderr, not stdout.
    >&2 echo $@
}

# Quote nesting works as described here: http://stackoverflow.com/a/6612417/4972
# SCRIPT_DIR via http://www.ostricher.com/2014/10/the-right-way-to-get-the-directory-of-a-bash-script/
SCRIPT_DIR="$( cd "$( dirname "${BASH_SOURCE[0]}" )" && pwd )"

# Default variables to empty if not present. Necessary due to the -u option specified above.
# For more information on this, look here:
# http://redsymbol.net/articles/unofficial-bash-strict-mode/#solution-positional-parameters
WORKING_DIR="${1:-}"  # default $1 to empty if it's not supplied 
VERSION="${2:-}"
OLD_VERSION=   # set later.

# Ensures the current working directory doesn't have tracked but uncommitted files in git.
clean_working_dir () {
    if [[ "$(git status -s | grep -m1 "^ ")" ]]; then
        error "Not checking out release. You have uncommitted files in your working directory."
        exit 1
    fi
}

# Check that requisite programs are available
validate_dependencies () {
    local -i missing=0
    if ! hash hub 2>/dev/null; then
        missing=$missing+1
        error 'Please install hub https://hub.github.com/'
    fi
    if ! hash git 2>/dev/null; then
        missing=$missing+1
        error 'Please install git https://git-scm.com/downloads'
    fi
    if ! hash perl 2>/dev/null; then
        missing=$missing+1
        error 'Please install perl https://www.perl.org/get.html'
    fi

    if ! hash git-release-notes 2>/dev/null; then
        missing=$missing+1
        error 'Please install git-release-notes https://www.npmjs.com/package/git-release-notes'
    fi

    if [[ 0 -ne $missing ]]; then
        exit $missing
    fi
}

# Updates the local repo
update_copy () {
    cd $WORKING_DIR # change to repository working directory
    clean_working_dir
    git checkout  master -q
    git pull -q
}

set_old_version () {
    OLD_VERSION="$(find $WORKING_DIR -maxdepth 2 -name 'settings.py' | xargs grep VERSION | tr "\"" ' ' | tr "'" " " | awk '{print $3}')"
    if [[ -z "$OLD_VERSION" ]]; then
        error "Could not determine the old version."
        exit 1
    fi
}

# Checks out the release-candidate branch
checkout_release () {
    cd $WORKING_DIR
    clean_working_dir
    # Create the branch if it doesn't exist. If it does, just check it out
    # git checkout -qb release-candidate 2>/dev/null || (git checkout -q release-candidate && git merge -q -m "Release $VERSION" master)
    git checkout -qb release-candidate 2>/dev/null || (git checkout -q release-candidate && git reset --hard master)
}


update_versions () {
    # maxdepth, so we don't pull things from .tox, etc
    find $WORKING_DIR -maxdepth 2 -name 'settings.py' | xargs perl -pi -e "s/VERSION = .*/VERSION = \"$VERSION\"/g"
    find $WORKING_DIR -maxdepth 2 -name 'setup.py' | xargs perl -pi -e "s/version=.*/version='$VERSION',/g"
}

update_release_notes () {
    cd $WORKING_DIR
    # Create/Update RELEASE.rst
    # +4 is to offset the header of the template we don't want yet.
    IFS=$'\n'  # sets separator to only newlines. see http://askubuntu.com/a/344418
    NEW_RELEASE_NOTES=$(git-release-notes v$OLD_VERSION..master $SCRIPT_DIR/util/release_notes_rst.ejs)

    echo 'Release Notes' > releases_rst.new
    echo '=============' >> releases_rst.new
    echo '' >> releases_rst.new
    VERSION_LINE="Version $VERSION"
    echo $VERSION_LINE >> releases_rst.new
    # start at 2, because we actually want len(versionline)-1, but that's hard to do in bash, so just start from 2.
    for i in $(seq 2 $(echo $VERSION_LINE | wc -c)); do
      echo -n '-' >> releases_rst.new
    done
    echo '' >> releases_rst.new
    echo '' >> releases_rst.new

    # we do this because, without it, bash ignores newlines in between the bullets.
    for line in $NEW_RELEASE_NOTES; do
        echo $line >> releases_rst.new
    done;
    echo '' >> releases_rst.new
    cat RELEASE.rst | tail -n +4 >> releases_rst.new
    mv releases_rst.new RELEASE.rst
    # explicit add, because we know the location & we will need it for the first release
    git add RELEASE.rst
    git commit -q --all --message "Release $VERSION"
}


build_release () {
    echo "Building release..."
    git push --force -q origin release-candidate:release-candidate
}

generate_prs () {
    echo "Release $VERSION" > release-notes-checklist
    echo "" >> release-notes-checklist 
    git-release-notes v$OLD_VERSION..master $SCRIPT_DIR/util/release_notes.ejs >> release-notes-checklist
    hub pull-request -b release -h "release-candidate" -F release-notes-checklist
}

main () {
    validate_dependencies
    update_copy
    checkout_release
    set_old_version
    update_versions
    update_release_notes
    build_release
    generate_prs
    echo "version $OLD_VERSION has been updated to $VERSION"
    echo "Go tell engineers to check their work. PR is on the repo."
    echo "After they are done, run the next script."
}


# Next script:
# - tag build
# - push tags
# - merge release-candidate to release
# - merge release to master

# This runs if the script was executed as ./release.sh but not sourced.
if [[ $(basename $0) = "release.sh" ]]; then
    set -euf -o pipefail

    if [[ -z "$WORKING_DIR" ]]; then
        error "You must specify a working directory as the first argument."
        exit 1
    fi

    if [[ -z "$VERSION" ]]; then
        error "You must specify a version as the second argument."
        exit 1
    fi

    main
fi
