# release-script

[![Build Status](https://travis-ci.org/mitodl/release-script.svg?branch=master)](https://travis-ci.org/mitodl/release-script)

Scripts to automate the release process.

A full release can be performed by following the steps below:

1. Run release.sh to create a PR for the release (see details in the 
    ["release.sh"](#releasesh) section below)
1. Inform the team that a release PR is up and that they need to verify their commits
1. Once developers verify their commits, run the finish_release.sh script
(see details in the ["finish_release.sh"](#finish_releasesh) section).
1. Send email notifications

Note that these scripts use temporary directories so none of your
work in progress will be affected or will affect the release.

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

### [git-release-notes - https://www.npmjs.com/package/git-release-notes](https://www.npmjs.com/package/git-release-notes)
git-release-notes is a Node package that processes Git commit history
through .EJS templates.  It requires Node and can be installed with ``npm``.

    npm install -g git-release-notes

### [curl - https://curl.haxx.se/](https://curl.haxx.se/)
curl is a command line tool to download files from the web.
It should be already installed in OS X and most Linux distributions.

## release.sh

release.sh automates these steps:

1. Clone and checkout a current ``master`` branch
1. Create a new ``release-candidate`` branch based off of master
1. Generate release notes
1. Update version numbers and ``RELEASE.rst``
1. Commit updates and push ``release-candidate`` branch
1. Generate release notes with checkboxes
1. Open PR to merge ``release-candidate`` branch into ``release`` branch

Run the command with these arguments:

    ./release.sh <path-to-release-project> <release number>

For example if the project you want to release is located at

    ~/projects/lore

and the release version is ``0.1.0``, your command would be

    ./release.sh  ~/projects/lore  0.1.0

## finish_release.sh

finish_release.sh automates these steps:

1. Clone and checkout the current ``release`` branch
1. Merge ``release-candidate`` into ``release`` and push it to ``origin``.
This causes a deployment which will end up on production.
1. Tag the new release with the release version and push the tag to ``origin``
1. Merge ``release`` to ``master`` to update release notes.

Run the command with these arguments:

    ./finish_release.sh <path-to-release-project> <release number>

## wait_for_deploy.sh

wait_for_deploy.sh will check the ``hash.txt`` file every 30 seconds.
When the hash matches up the script will exit successfully.

Run the command with these arguments:

    ./wait_for_deploy.sh <path-to-release-project> <hash-url> <watch-branch>

- ``path-to-release-project`` - The path to the project which is being deployed
- ``hash-url`` - The URL to be polled. This should point to a text file with only
the git hash as its contents.
- ``watch-branch`` - The branch being deployed. The latest commit on this branch
will be compared with the deployment server's hash.

For example, to wait for successful deployment on micromasters to RC:
 
    ./wait_for_deploy.sh ~/Projects/micromasters https://micromasters-rc.herokuapp.com/static/hash.txt release-candidate
    
To wait for successful deployment of micromasters to production:

    ./wait_for_deploy.sh ~/Projects/micromasters https://micromasters.mit.edu/static/hash.txt release
    
## Releasing to PyPI 

For python libraries and XBlocks, once the the release is finished, it needs to be uploaded to PyPI. The easiest
way to do this is through doof, but first you need to set these environment variables:

- `PYPI_USERNAME`
- `PYPI_PASSWORD`
- `PYPITEST_USERNAME`
- `PYPITEST_PASSWORD`

To upload via Doof, run `@doof upload to pypitest 1.2.3` where `1.2.3` is an already released version. If that works
run `@doof upload to pypy 1.2.3` to upload to the production package repository.

### Manual PyPI release

1. Get the PyPI credentials from DevOps.
If you haven't already, you should set up a ``.pypirc`` file as described in 
http://peterdowns.com/posts/first-time-with-pypi.html
1. Review the metadata in ``setup.py``
Most repos should already be set up with proper metadata. If not, consult the documentation at 
https://docs.python.org/3.6/distutils/setupscript.html#meta-data
1. Check the version number in ``setup.py``. It should be the same as the release number. 

Do a test run with the pypitest repository:

    python setup.py sdist upload -r pypitest 

If this works, you should get the (final) response:

    Server response (200): OK

If the test works, upload to the real deal:

    python setup.py sdist upload -r pypi


## Notes

1.  The main development branch is ``master``, the branch of the version in
    production is ``release``.
2.  We use [Semantic Versioning](http://semver.org/) for our release numbers.
3.  The ``util`` directory contains the templates to format the release notes
    and the GitHub descriptions.
4.  The script expects to find the current release number in either the Django
    ``settings.py`` file, in ``setup.py``, or in ``__init__.py``.
    If your project has neither of these files, the script will
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
