# release-script

[![Build Status](https://travis-ci.org/mitodl/release-script.svg?branch=master)](https://travis-ci.org/mitodl/release-script)

Scripts to automate the release process.

A full release can be performed by following the steps below:

1. Run release.sh to create a PR for the release (see details in the "How to use release.sh" section below)
1. Inform the team that a release PR is up and that they need to verify their commits
1. Once developers verify their commits, merge the 'release-candidate' branch into 'release', and push
    the release branch.
    *(NOTE: This can be done using the 'Merge Pull Request' button in the Github PR issue. Do not 
    delete the branch after merging)*
1. Tag the ``release`` branch with the version number and push the tag to
    the remote. For example, these commands create an annotated tag for
    version 0.3.0 and push the tag to the remote. (You don't need to specify
    the sha of the commit if you're on the branch you want to tag.)
    ```
    git tag -a -m "Release 0.3.0" v0.3.0 <sha of commit>
    git push --follow-tags
    ```
1. Merge the ``release`` branch into the ``master`` branch,
    and push ``master`` to ``origin``.
1. Send email notifications

## Dependencies

release.sh is dependent on these applications.

### [Hub - https://hub.github.com/](https://hub.github.com/)

Hub is a command-line wrapper for Git.  It is available as a precompiled
binary as well as from Homebrew on OSX:

    brew install hub

### [Perl - https://www.perl.org/get.html](https://www.perl.org/get.html)  

Perl is already installed on your OS unless you're running Windows.  
If you need it, refer to instructions at the above URL.

### [Git - http://www.git-scm.org/downloads](http://www.git-scm.org/downloads)
Git is a distributed source control system.  If you don't have Git installed,
we're ashamed of you.  (Though if you use Mecurial instead, we'll go easy.)
Git is available as a precompiled binary as well as from Homebrew on OSX:

    brew install git

### [git-release-notes - https://www.npmjs.com/package/git-release-notes]
(https://www.npmjs.com/package/git-release-notes)
git-release-notes is a Node package that processes Git commit history
through .EJS templates.  It requires Node and can be installed with ``npm``.

    npm install -g git-release-notes

## What does release.sh do?

release.sh automates the following 8 steps:

1. Check-out a current ``master`` branch
2. Create a ``release-candidate`` branch
3. Hard reset ``release-candidate`` to ``master``
4. Generate release notes
5. Update version numbers and ``RELEASE.rst``
6. Commit updates and push ``release-candidate`` branch
7. Generate release notes with checkboxes
8. Open PR to merge ``release-candidate`` branch into ``release`` branch

## How to use release.sh

Clone this repository to your local machine. Before each use remember to
update the repository so you use the latest version of the ``master`` branch.

You must run the script from directory of the release project.  

    <path-to-release.sh>/release.sh <path-to-release-project> <release number>

For example, if your ``release-script`` repository is located at

    ~/projects/release-script

the project you want to release is located at

    ~/projects/lore

and the release version is ``0.1.0``, your command line would be

    ~/projects/release-script/release.sh  ~/projects/lore  0.1.0

or just this

    ~/projects/release-script/release.sh  .  0.1.0

since you must run the script from the release project's directory.

## Notes

1.  The main development branch is ``master``, the branch of the version in
    production is ``release``.
2.  We use [Semantic Versioning](http://semver.org/) for our release numbers.
3.  The ``utils`` directory contains the templates to format the release notes
    and the Github descriptions.
4.  The script expects to find the current release number in either the Django
    ``settings.py`` file or in the ``setup.py`` file in the project root
    directory. If your project has neither of these files, the script will
    fail.
5.  You can confirm that the release-candidate deployed successfully by
    checking this end point on the release-candidate server.  

        <the-release-candidate-server-URL>/static/hash.txt

    The endpoint will return the hash for the branch that is running on the
    server.  For example,

        https://micromasters-rc.herokuapp.com/static/hash.txt

    returns the branch hash for the deployed Micromasters release-candidate.
6.  There are three deployment servers, ci, rc, and production.

## Troubleshooting

1.  You can get debugging information by prefacing the command with
    ``TRACE=1`` so the command would begin with ``TRACE=1 release.sh ...``.
2.  The most common problem is that the version tag for the previous version
    doesn't exist.  Determine the previous version tag numbers with this
    command:

        git tag -l

    Version tags start with the letter "v" followed by the version number.
