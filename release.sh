#!/bin/bash -x

# A script to automate the release process

# Usage
#   release working_dir version_num

set -euf -o pipefail

# SCRIPT_DIR via http://www.ostricher.com/2014/10/the-right-way-to-get-the-directory-of-a-bash-script/
SCRIPT_DIR=$( cd "$( dirname "${BASH_SOURCE[0]}" )" && pwd )
WORKING_DIR=$1
VERSION=$2
OLD_VERSION=$(find . -name 'settings.py' -maxdepth 2 | xargs grep VERSION | tr '"' ' ' | awk '{print $3}')

# Check that programs are available
EXIT_TO_INSTALL_APPS=false

if hash hub 2>/dev/null; then
  # continue
else
  EXIT_TO_INSTALL_APPS=true
  echo 'Please install hub https://hub.github.com/'
fi
if hash git 2>/dev/null; then
  @ continue
else
  EXIT_TO_INSTALL_APPS=true
  echo 'Please install git https://git-scm.com/downloads'
fi
if hash perl 2>/dev/null; then
  @ continue
else
  EXIT_TO_INSTALL_APPS=true
  echo 'Please install perl https://www.perl.org/get.html'
fi
if EXIT_TO_INSTALL_APPS=true then
  exit()
fi

cd $WORKING_DIR # change to repository working directory
git checkout master
git pull

# Create the branch if it doesn't exist. If it does, just check it out
git checkout -b release-candidate || (git checkout release-candidate && git merge master)

# maxdepth, so we don't pull things from .tox, etc
find $WORKING_DIR -name 'settings.py' -maxdepth 2 | xargs perl -pi -e "s/VERSION = .*/VERSION = \"$VERSION\"/g" 
find $WORKING_DIR -name 'setup.py' -maxdepth 2 | xargs perl -pi -e "s/version=.*/version='$VERSION',/g" 

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

# git push origin release-candidate:release-candidate
# hub pull-request -b master -h "release-candidate" -m "Update version to $VERSION"
# 
git-release-notes v$OLD_VERSION..master $SCRIPT_DIR/util/release_notes.ejs > release-notes-checklist
# hub pull-request -b release -h "release-candidate" -F release-notes-checklist

echo "Go tell engineers to check their work. PR is on the repo."
echo "After they are done, run the next script."

# Next Steps
# - make pr from rc/0.2.0 to release with git-release-notes as the PR description (the non-rst one)
# ... then instruct humans to QA
# ... when they are done, we "finish". Brandon has opinions about what this means w/r/t which branch gets merged where.
# ... we certainly tag builds and push tags up and delete some branches.
# ... What should it be doing something with PRs? *shrug*

# QUESTIONS:
# Does pushing to rc/0.2.0 create a thing on teachersportal-rc.herokuapp.com? 
# 
# Can we just make a PR from this new rc/0.2.0 branch to release now using hub? Or do we have to wait for the build to pass on this branch?
# 
#
#


