export BLAZEGRAPH_RUNNER_RELEASE_URL=https://github.com/balhoff/blazegraph-runner/releases/download/v1.7/blazegraph-runner-1.7.tgz

# Download and extract the blazegraph-runner
wget -O blazegraph-runner.tgz ${BLAZEGRAPH_RUNNER_RELEASE_URL}
# Extract the blazegraph-runner in the ../utils directory
tar -xzf blazegraph-runner.tgz -C ../utils
# Remove the version number from the directory name
mv ../utils/blazegraph-runner-1.7 ../utils/blazegraph-runner
# Remove the downloaded tarball
rm blazegraph-runner.tgz

