# release-script

This repository includes our Slack bot [Doof](https://phineasandferb.fandom.com/wiki/Heinz_Doofenshmirtz) whose code is primarily located in `bot.py`. Doof
accepts commands spoken in particular channels in Slack and executes various parts of the release process.
There is also  `bot_local.py` to allow developers to run these commands outside of Slack.

## Prerequisite environment variables
Doof requires these environment variables to be set. This check is done on startup so if Doof is already running you should
be all set.

  - `SLACK_ACCESS_TOKEN` - Used to communicate with Slack, for example to post a message or fetch the list of channels.
  - `BOT_ACCESS_TOKEN` - Used for Doof's communications as a Slack bot.
  - `GITHUB_ACCESS_TOKEN` - Used to access information about github repos and to create new pull requests.
  - `NPM_TOKEN` - Used to publish NPM packages
  - `SLACK_SECRET` - Used to authenticate requests from Slack to Doof (ie the finish release button, events API.)
  - `TIMEZONE` - The timezone of the team working with Doof
  - `PORT` - The port of the webserver, used for receiving webhooks from Slack
  - `PYPITEST_USERNAME` - The PyPI username to upload testing Python packages
  - `PYPITEST_PASSWORD` - The PyPI password to upload testing Python packages
  - `PYPI_USERNAME` - The PyPI username to upload production packages
  - `PYPI_PASSWORD` - The PyPI password to upload production packages

`bot_local.py` also requires these environment variables to be set, though environment
variable checks may become more fine grained in the future. Until then it may be easiest
to fill in fake values for environment variables not needed for your command.

## Deployment of Doof
Doof is a Slack bot running on heroku at `odl-release-bot`. New code will be
deployed whenever a pull request in this project is merged and tests pass. Exceptions can be viewed
in the heroku logs for `odl-release-bot`.

## Running commands
Our bot Doof helps manage the release process by automating most parts of it and providing a public view so everyone
knows when a release is happening and what state it's in.

Some Doof commands need to be run in a specific Slack channel. Doof ties each Slack channel to a project
(see `repos_info.json`). If you type `@doof release 1.2.3` in the `#micromasters-eng` channel it will do a release
for the micromasters project.

Other Doof commands can be run in any channel. If you want to run a command but don't want to clutter the channel
chat, you can communicate directly with Doof with a direct message.
(You will still need to prefix all communication with `@doof` so Doof understands you're talking to him.)

For a full listing of Doof commands type `@doof help` in Slack.

## Release process
Release lifecycle:
  - Code starts out in a pull request which is reviewed by other team members.
  - Then the pull request is merged to the `main` branch (or `master` for legacy projects). After tests pass this triggers a deployment
    to a CI (continuous integration) server for web application projects.
  - At some point, usually daily, the release manager checks if there is new code available.
  - If there is, a release candidate is created in the `release-candidate`.
    This is a pull request with the new code plus a version update. This will trigger
    a deployment to the RC (release candidate) server for web application projects.
  - Unit tests are run against the release candidate and team members check off checkboxes to verify,
    at a glance, that their code works in conjuction with other code in the release.
  - The release candidate is merged into the `release` branch. Heroku and possibly other build systems
    will detect this and trigger a deployment to a production server for web application projects.
  - Library packages may need to be published to a repository like PyPI or NPM.

### Running releases with Doof
To start a new release with `@doof`:

  - Pick a Slack channel which is tied to the project you want to make a release for. There is a list in `repos_info.json`.
  - In that channel type `@doof release notes`. This will show the PRs and commits which have been merged since the last release, if there are any.
  - Type `@doof release 4.5.6`, replacing `4.5.6` with the version number of the new release.
  - Doof will start the release. This will create a PR with checkboxes for each PR.

Library projects:
  - The release manager should check that tests have passed.
  - Publish the new release by saying `@doof publish 4.5.6`.

Web application projects:
  - Doof will wait for the deployment to finish by comparing the git hash of the release
  with the git hash from the web application. At this point Doof will tell everyone to check off their checkboxes to verify
  that basic functionality is included in the release, that it works in the RC environment and that PR functionalities don't
  conflict with each other.
  - When all checkboxes are checked off, Doof will show a button and say the release is ready to merge. Click 'Finish release'
  to merge the release and deploy it to production.
  - If there is an urgent need for a release, or an issue with the unit tests that shouldn't block the release,
    you can type `@doof finish release 4.5.6` to finish the release.
  - Doof will check the git hash for the production release to verify a successful deployment.

### Command line release process
If Slack is down you may need to run releases from a shell using `bot_local.py`. To do that:

 - Create a virtualenv for this project and install dependencies from `requirements.txt`.
 - Set environment variables listed above. Until we make environment variable checks more fine
grained it is probably easiest to fill in fake values for the values you don't need.
 - Start a release: `python3 bot_local.py micromasters-eng release 4.5.6` for example.
 - Merge the release: `python3 bot_local.py micromasters-eng finish release`.
 
Note that Doof and `bot_local.py` use temporary directories for all releases so none of your
work in progress will be affected or will affect the release.

### Dependencies

#### [Git - http://www.git-scm.org/downloads](http://www.git-scm.org/downloads)
Git is available as a precompiled binary as well as from Homebrew on OSX:

    brew install git

#### [Python 3.7+ - https://www.python.org/downloads/](https://www.python.org/downloads/)

Python 3.7+ is required.

#### Python libraries

All python dependencies are listed in `requirements.txt`. (For testing also install `test_requirements.txt`.)

Create a virtualenv and install the Python dependencies. For example:

  - `virtualenv /tmp/release_venv -p /usr/bin/python3`
  - `. /tmp/release_venv/bin/activate`
  - `pip install -r requirements.txt -r test_requirements.txt`

Make sure to also run the various scripts from within the virtualenv.

#### Javascript libraries
Make sure you have `npm` installed, then install any dependencies:

    npm install
