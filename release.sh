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

# Clone repository into temporary directory
create_working_dir() {
    WORKING_DIR=$(mktemp -d)
    echo "Cloning into working directory at $WORKING_DIR..."
    cd $WORKING_DIR

    # doing this instead of a git clone so we don't create another directory
    REPO_URL=$(git --git-dir "$REPO_DIR"/.git remote get-url origin)

    # from http://stackoverflow.com/questions/2411031/how-do-i-clone-into-a-non-empty-directory
    git init
    git remote add origin "$REPO_URL"
    git fetch
    git checkout -t origin/master
}

# Check that requisite programs are available
validate_dependencies () {
    echo "Validating dependencies..."
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

    if ! hash curl 2>/dev/null; then
        missing=$missing+1
        error 'Please install curl'
    fi

    if ! hash node 2>/dev/null; then
        missing=$missing+1
        error 'Please install node.js https://nodejs.org/'
    fi

    NODE_MAJOR_VERSION=$(node --version | cut -c2- | awk -F. '{print $1}')
    if [[ $NODE_MAJOR_VERSION -lt 6 ]]
    then
        missing=$missing+1
        error 'node.js must be version 6.x or higher'
    fi

    if [[ 0 -ne $missing ]]; then
        exit $missing
    fi
}

set_old_version () {
    echo "Defining old version..."
    OLD_VERSION=""
    version_files=( 'settings.py' '__init__.py' 'setup.py' )
    for file_name in "${version_files[@]}"
    do
        OLD_VERSION="$(find $WORKING_DIR -maxdepth 2 -name "$file_name" | xargs grep -i version | tr " =" " " | tr "\"" ' ' | tr "'" " " | awk 'NR==1{print $2}')"
        VERSION_FILE="$file_name"

        if [[ ! -z "$OLD_VERSION" ]]; then
            break
        fi

    done

    if [[ -z "$OLD_VERSION" ]]; then
      error "Could not determine the old version."
      exit 1
    fi
}

# Checks out the release-candidate branch
checkout_release () {
    echo "Checking out release candidate..."
    cd $WORKING_DIR
    # Create the branch if it doesn't exist. If it does, just check it out
    # git checkout -qb release-candidate 2>/dev/null || (git checkout -q release-candidate && git merge -q -m "Release $VERSION" master)
    git checkout -qb release-candidate 2>/dev/null || (git checkout -q release-candidate && git reset --hard master)
}

# Update the version numbers in canonical locations.
update_versions () {
    # maxdepth, so we don't pull things from .tox, etc
    if [ $VERSION_FILE = "settings.py" ]; then
      find $WORKING_DIR -maxdepth 2 -name 'settings.py' | xargs perl -pi -e "s/VERSION = .*/VERSION = \"$VERSION\"/g"
    elif [ $VERSION_FILE = "__init__.py" ]; then
      find $WORKING_DIR -maxdepth 2 -name '__init__.py' | xargs perl -pi -e "s/__version__\ ?=.*#\ pragma:\ no\ cover/__version__\ =\ '$VERSION'\ \ #\ pragma:\ no\ cover/g"
    elif [ $VERSION_FILE = "setup.py" ]; then
      find $WORKING_DIR -maxdepth 2 -name 'setup.py' | xargs perl -pi -e "s/version=.*/version='$VERSION',/g"
    else
      error "Could not update with new version."
      exit 1
    fi
}

# Create a section in RELEASE document describing the commits in the release
update_release_notes () {
    echo "Updating release notes..."
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
    if [[ -f RELEASE.rst ]]; then
      cat RELEASE.rst | tail -n +4 >> releases_rst.new
    fi
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
    echo "Generating PR..."
    echo "Release $VERSION" > release-notes-checklist
    echo "" >> release-notes-checklist
    git-release-notes v$OLD_VERSION..master $SCRIPT_DIR/util/release_notes.ejs >> release-notes-checklist
    hub pull-request -b release -h "release-candidate" -F release-notes-checklist
}

delete_working_dir () {
    cd
    echo "Finished, deleting $WORKING_DIR..."
    rm -rf "$WORKING_DIR"
}

main () {
    validate_dependencies
    create_working_dir
    checkout_release
    set_old_version
    update_versions
    update_release_notes
    build_release
    generate_prs
    delete_working_dir
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
