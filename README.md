# release-script
Scripts to automate the release process.

These scripts automate the release process which to-date has been 
an intricate manual process. These are the steps:

1. Check-out a current master branch
2. Create a release candidate branch
3. Generate release notes
3. Update version numbers and RELEASE.rst
4. Commit updates and push branch
6. Open PR against ``release candidate`` branch
7. Merge PR once ``travis-ci`` build succeeds
8. Generate release notes with checkboxes
8. Open PR against ``release`` branch
10. Open PR against ``master`` branch
11. Merge PRs once developers verify their commits
12. Send email notifications

## Notes
1. 
