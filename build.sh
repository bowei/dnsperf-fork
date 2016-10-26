#!/bin/bash

set -e

BUILD_IMAGE="gcr.io/bowei-gke-dev/dnsperf-build"
TAG="1.0"

# Putting the commands to build here to avoid having too many files to
# look at.
cat > tmp-docker-build.sh <<END
#!/bin/sh

set -e

cd /src

if [ ! -e config.log ]; then
   ./configure
fi

make

END
chmod +x tmp-docker-build.sh

# build to target alpine systems
docker build --tag "${BUILD_IMAGE}:${TAG}" -f Dockerfile.build .
docker run -v `pwd`:/src -i "${BUILD_IMAGE}:${TAG}"
