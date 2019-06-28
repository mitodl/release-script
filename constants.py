"""Constants"""
import os


TRAVIS_SUCCESS = 'success'
TRAVIS_FAILURE = 'failure'
TRAVIS_PENDING = 'pending'
NO_PR_BUILD = 'none'


FINISH_RELEASE_ID = 'finish_release'
NEW_RELEASE_ID = 'new_release'

WEB_APPLICATION_TYPE = 'web_application'
LIBRARY_TYPE = 'library'


SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
GIT_RELEASE_NOTES_PATH = os.path.join(SCRIPT_DIR, "./node_modules/.bin/git-release-notes")
