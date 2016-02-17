#!/bin/bash

# A script to automate the release process

# Usage
#   release working_dir version_num

set -euf -o pipefail

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

if [[ -z "$WORKING_DIR" ]]; then
    error "You must specify a working directory as the first argument."
    exit 1
fi

if [[ -z "$VERSION" ]]; then
    error "You must specify a version as the second argument."
    exit 1
fi

# Check that programs are available
# Ensures the current working directory doesn't have tracked but uncommitted files in git.
clean_working_dir () {
    if [[ "$(git status -s | grep -m1 "^ ")" ]]; then
        error "Not checking out release. You have uncommitted files in your working directory."
        exit 1
    fi
}

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

    if [[ 0 -ne $missing ]]; then
        exit $missing
    fi
}

update_copy () {
    cd $WORKING_DIR # change to repository working directory
    git checkout master
    git pull

}

checkout_release () {
    # Create the branch if it doesn't exist. If it does, just check it out
    git checkout -b release-candidate || (git checkout release-candidate && git merge master)
}

update_versions () {
    # maxdepth, so we don't pull things from .tox, etc
    find $WORKING_DIR -maxdepth 2 -name 'settings.py' | xargs perl -pi -e "s/VERSION = .*/VERSION = \"$VERSION\"/g"
    find $WORKING_DIR -maxdepth 2 -name 'setup.py' | xargs perl -pi -e "s/version=.*/version='$VERSION',/g"
}

update_release_notes () {
    # Create/Update RELEASE.rst
    # +4 is to offset the header of the template we don't want yet.
    IFS=$'\n'  # sets separator to only newlines. see http://askubuntu.com/a/344418
    NEW_RELEASE_NOTES=$(git-release-notes v$OLD_VERSION..master $SCRIPT_DIR/util/release_notes_rst.ejs | tail +4)

    echo 'Release Notes' > releases_rst.new
    echo '=============' >> releases_rst.new
    echo '' >> releases_rst.new
    echo "Version $VERSION" >> releases_rst.new
    echo '-------------' >> releases_rst.new
    echo '' >> releases_rst.new

    # we do this because, without it, bash ignores newlines in between the bullets.
    for line in $NEW_RELEASE_NOTES; do
        echo $line >> releases_rst.new
    done;
    echo '' >> releases_rst.new
    echo RELEASE.rst | tail +4 >> releases_rst.new
    mv releases_rst.new RELEASE.rst
    # explicit add, because we know the location & we will need it for the first release
    git add RELEASE.rst
    git commit --all --message "Release $VERSION"
}


build_release () {
    # git push origin release-candidate:release-candidate
    echo "Building release"
}

generate_prs () {
    # hub pull-request -b master -h "release-candidate" -m "Update version to $VERSION"
    #
    git-release-notes v$OLD_VERSION..master $SCRIPT_DIR/util/release_notes.ejs > release-notes-checklist
    # hub pull-request -b release -h "release-candidate" -F release-notes-checklist
}

main () {
    validate_dependencies
    update_copy
    checkout_release
    update_versions
    update_release_notes
    build_release
    generate_prs
    echo "Go tell engineers to check their work. PR is on the repo."
    echo "After they are done, run the next script."
}


# Next script:
# - tag build
# - push tags

main
