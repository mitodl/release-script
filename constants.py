"""Constants"""
import os


FINISH_RELEASE_ID = 'finish_release'
NEW_RELEASE_ID = 'new_release'

# project types
WEB_APPLICATION_TYPE = 'web_application'
LIBRARY_TYPE = 'library'
VALID_PROJECT_TYPES = [WEB_APPLICATION_TYPE, LIBRARY_TYPE]

# web application types
DJANGO = "django"
HUGO = "hugo"
VALID_WEB_APPLICATION_TYPES = [DJANGO, HUGO]

# packaging tool types
NPM = "npm"
SETUPTOOLS = "setuptools"
VALID_PACKAGING_TOOL_TYPES = [NPM, SETUPTOOLS]

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
GIT_RELEASE_NOTES_PATH = os.path.join(SCRIPT_DIR, "./node_modules/.bin/git-release-notes")
