# release-script

[![Build Status](https://travis-ci.org/mitodl/release-script.svg?branch=master)](https://travis-ci.org/mitodl/release-script)

This repository includes our bot Doof as well as command line scripts to manage various parts of the release process.

## Prerequisite environment variables
Doof and other scripts require these environment variables to be set. This check is done on startup so if Doof is already running you should
be all set.

  - `SLACK_ACCESS_TOKEN` - Used to communicate with Slack, for example to post a message or fetch the list of channels.
  - `BOT_ACCESS_TOKEN` - Used for Doof's communications as a Slack bot.
  - `GITHUB_ACCESS_TOKEN` - Used to access information about github repos and to create new pull requests.
  - `SLACK_WEBHOOK_TOKEN` - Used to authenticate requests from Slack to Doof (ie the finish release button.)
  - `TIMEZONE` - The timezone of the team working with Doof
  - `PORT` - The port of the webserver, used for receiving webhooks from Slack
  - `PYPITEST_USERNAME` - The PyPI username to upload testing Python packages
  - `PYPITEST_PASSWORD` - The PyPI password to upload testing Python packages
  - `PYPI_USERNAME` - The PyPI username to upload production packages
  - `PYPI_PASSWORD` - The PyPI password to upload production packages

## Doof
Our bot Doof helps manage the release process by automating most parts of it and providing a public view so everyone
knows when a release is happening and what state it's in.

Some Doof commands need to be run in a specific Slack channel. Doof ties each Slack channel to a project
(see `repos_info.json`). If you type `@doof release 1.2.3` in the `#micromasters-eng` channel it will do a release
for the micromasters project.

Other Doof commands can be run in any channel. If you want to run a command but don't want to clutter the channel
chat, you can communicate directly with Doof with a direct message.
(You will still need to prefix all communication with `@doof` so Doof understands you're talking to him.)
For a full listing of Doof commands type `@doof help` in Slack.

### Release process
To start a new release with `@doof`:

  - Pick a Slack channel which is tied to the project you want to make a release for. There is a list in `repos_info.json`.
  - In that channel type `@doof release notes`. This will show the PRs and commits which have been merged since the last release, if there are any.
  - Type `@doof release 4.5.6`, replacing `4.5.6` with the version number of the new release.
  - Doof will start the release. This will create a PR with checkboxes for each PR.

Library projects:
  - For library projects you are pretty much done. Doof will wait for Travis tests to pass for the PR build, then
  doof will merge the release and tell you that the release was merged.
  - Optionally you can upload a new release to pypi by saying `@doof upload to pypitest 4.5.6`.
   If that worked, say `@doof upload to pypi 4.5.6` to make a production release.

Web application projects:
  - For web application projects, Doof will wait for the deployment to finish by comparing the git hash of the release
  with the git hash from the web application. At this point Doof will tell everyone to check off their checkboxes to verify
  that basic functionality is included in the release, that it works in the RC environment and that PR functionalities don't
  conflict with each other.
  - When all checkboxes are checked off, Doof will show a button and say the release is ready to merge. Click 'Finish release'
  to merge the release and deploy it to production. (You can also type `@doof finish release 4.5.6` instead of clicking the button.)
  - Doof should wait for the production release to go out and say that it all went successfully.

### Other Doof commands

 - `@doof karma 1993-01-01` - Calculates PR karma (number of PR reviews by a user) between the given date and today.
 - `@doof what needs review` - Searches for pull requests which do not have an assigned reviewer.
 - `@doof help` - List all Doof commands currently supported

### Command line release process
A full release can be performed by following the steps below:

1. Run release.sh to create a PR for the release (see details in the 
    ["release.sh"](#releasesh) section below)
1. Inform the team that a release PR is up and that they need to verify their commits
1. Once developers verify their commits, run the finish_release.sh script
(see details in the ["finish_release.sh"](#finish_releasesh) section).

Note that these scripts use temporary directories so none of your
work in progress will be affected or will affect the release.

### Dependencies

#### [Git - http://www.git-scm.org/downloads](http://www.git-scm.org/downloads)
Git is available as a precompiled binary as well as from Homebrew on OSX:

    brew install git

#### [Python 3.6+ - https://www.python.org/downloads/](https://www.python.org/downloads/)

Python 3.6+ is required. (Python 3.5 might work, earlier versions will be missing async functionality.)

#### Python libraries

All python dependencies are listed in `requirements.txt`. (For testing also install `test_requirements.txt`.)

Create a virtualenv and install the Python dependencies. For example:

  - `virtualenv /tmp/release_venv -p /usr/bin/python3`
  - `. /tmp/release_venv/bin/activate`
  - `pip install -r requirements.txt -r test_requirements.txt`

Make sure to also run the various scripts from within the virtualenv.

#### Javascript libraries
At the moment there is only one Javascript library, git-release-notes. It is a Node package that processes Git commit history
through .EJS templates.  It requires Node and can be installed with ``npm``.

    npm install

The scripts will look in the `node_modules` directory in this folder so you should not need to install it globally.


### Command line scripts

#### release.sh

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

#### finish_release.sh

finish_release.sh automates these steps:

1. Clone and checkout the current ``release`` branch
1. Merge ``release-candidate`` into ``release`` and push it to ``origin``.
This causes a deployment which will end up on production.
1. Tag the new release with the release version and push the tag to ``origin``
1. Merge ``release`` to ``master`` to update release notes.

Run the command with these arguments:

    ./finish_release.sh <path-to-release-project> <release number>

#### wait_for_deploy.sh

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

For python libraries and XBlocks, once the the release is finished, it needs to be uploaded to PyPI. The easiest
way to do this is through doof, but first you need to set these environment variables:

- `PYPI_USERNAME`
- `PYPI_PASSWORD`
- `PYPITEST_USERNAME`
- `PYPITEST_PASSWORD`

#### wait_for_checked.py

wait_for_checked.py will check the release PR for the given repo and ping it every 60 seconds until all checkboxes are checked.

    ./wait_for_checked.py micromasters --org mitodl

## PyPI release

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

## Tests

To run unit tests, install the Python dependencies in `requirements.txt` and `test_requirements.txt`, then run unit tests via `tox`.

## Misc notes

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
