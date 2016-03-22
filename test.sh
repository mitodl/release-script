#! /bin/bash
. ./release.sh 

WORKING_DIR=test-repo

testVersion() {
    set_old_version
    assertEquals "0.2.0" "$OLD_VERSION"
}

testSetVersion() {
    VERSION="0.3.0"
    update_versions
    set_old_version  # aka 'what version does the settings file say?'
    assertEquals "0.3.0" "$OLD_VERSION"
}


# load shunit2
. shunit2/source/2.1/src/shunit2
