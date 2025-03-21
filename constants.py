"""Constants"""

import os


FINISH_RELEASE_ID = "finish_release"
NEW_RELEASE_ID = "new_release"

# project types
WEB_APPLICATION_TYPE = "web_application"
LIBRARY_TYPE = "library"
VALID_PROJECT_TYPES = [WEB_APPLICATION_TYPE, LIBRARY_TYPE]

# web application types
DJANGO = "django"
HUGO = "hugo"
VALID_WEB_APPLICATION_TYPES = [DJANGO, HUGO]

# packaging tool types
NONE = "none"
NPM = "npm"
SETUPTOOLS = "setuptools"
GO = "go"
VALID_PACKAGING_TOOL_TYPES = [NONE, NPM, SETUPTOOLS, GO]

# versioning strategies
FILE_VERSION = "file"
NPM_VERSION = "npm"
PYTHON_VERSION = "python"
VALID_VERSIONING_STRATEGIES = [FILE_VERSION, NPM_VERSION, PYTHON_VERSION]

# deployment server types
RC = "rc"
CI = "ci"
PROD = "prod"
VALID_DEPLOYMENT_SERVER_TYPES = [CI, RC, PROD]

MINOR = "minor"
PATCH = "patch"
VALID_RELEASE_ALL_TYPES = [MINOR, PATCH]

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
GIT_RELEASE_NOTES_PATH = os.path.join(
    SCRIPT_DIR, "./node_modules/.bin/git-release-notes"
)
YARN_PATH = os.path.join(SCRIPT_DIR, "./node_modules/.bin/yarn")

# github labels
ALL_CHECKBOXES_CHECKED = "all checkboxes checked"
DEPLOYING_TO_RC = "deploying to rc"
WAITING_FOR_CHECKBOXES = "waiting for checkboxes"
DEPLOYING_TO_PROD = "deploying to prod"
DEPLOYED_TO_PROD = "deployed to prod"
RELEASE_LABELS = [
    ALL_CHECKBOXES_CHECKED,
    DEPLOYING_TO_RC,
    WAITING_FOR_CHECKBOXES,
    DEPLOYING_TO_PROD,
    DEPLOYED_TO_PROD,
]
FREEZE_RELEASE = "freeze release"
BLOCKER = "blocker"
BLOCKED = "blocked"
RELEASE_BLOCKER = "release blocker"
BLOCKER_LABELS = [
    FREEZE_RELEASE,
    BLOCKED,
    BLOCKER,
    RELEASE_BLOCKER,
]

# not github labels but used internally when calculating release statuses
LIBRARY_PR_WAITING_FOR_MERGE = "library PR waiting for merge"

STATUS_EMOJIS = {
    WAITING_FOR_CHECKBOXES: "🕰️",
    DEPLOYING_TO_PROD: "🕰️",
    DEPLOYING_TO_RC: "🕰️",
    ALL_CHECKBOXES_CHECKED: "🔔",
    LIBRARY_PR_WAITING_FOR_MERGE: "🔔",
}
for label in BLOCKER_LABELS:
    STATUS_EMOJIS[label] = "❌"
