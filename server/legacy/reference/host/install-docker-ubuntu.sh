#!/usr/bin/env bash
# Installs Docker Engine and Compose on Ubuntu Server from Docker's own repository (docs/21 step 1, docs/33 section 4).
#   bash install-docker-ubuntu.sh
# Ubuntu 22.04, 24.04 and 26.04 LTS. Safe to run again: it stops at once if Docker with Compose is already there.
# Why not Ubuntu's own `docker.io` package: it trails Docker's releases and lacks the `docker compose` plugin this stack uses.
set -euo pipefail

if docker compose version >/dev/null 2>&1 || sudo -n docker compose version >/dev/null 2>&1; then
  echo "Docker with Compose is already installed:"
  docker compose version 2>/dev/null || sudo docker compose version
  exit 0
fi

# shellcheck disable=SC1091
. /etc/os-release
if [[ ${ID:-} != ubuntu ]]; then
  echo "This helper is for Ubuntu. For ${PRETTY_NAME:-this system} follow https://docs.docker.com/engine/install/"
  exit 1
fi
case "${VERSION_ID:-}" in
  22.04 | 24.04 | 26.04) ;;
  *)
    echo "Ubuntu ${VERSION_ID:-?} is not one of the long-term releases this was tested on (22.04, 24.04, 26.04)."
    echo "Install Docker from https://docs.docker.com/engine/install/ubuntu/ instead."
    exit 1
    ;;
esac

SUDO=""
[[ $EUID -ne 0 ]] && SUDO="sudo"

echo "Installing Docker from docker.com for Ubuntu ${VERSION_ID} (${VERSION_CODENAME}) ..."
$SUDO apt-get update -qq
$SUDO apt-get install -y -qq ca-certificates curl
$SUDO install -m 0755 -d /etc/apt/keyrings
$SUDO curl -fsSL https://download.docker.com/linux/ubuntu/gpg -o /etc/apt/keyrings/docker.asc
$SUDO chmod a+r /etc/apt/keyrings/docker.asc
$SUDO tee /etc/apt/sources.list.d/docker.sources >/dev/null <<EOF
Types: deb
URIs: https://download.docker.com/linux/ubuntu
Suites: ${UBUNTU_CODENAME:-$VERSION_CODENAME}
Components: stable
Architectures: $(dpkg --print-architecture)
Signed-By: /etc/apt/keyrings/docker.asc
EOF
$SUDO apt-get update -qq
$SUDO apt-get install -y -qq docker-ce docker-ce-cli containerd.io docker-buildx-plugin docker-compose-plugin

# Let this account use Docker without typing sudo (takes effect at the next login).
$SUDO usermod -aG docker "${SUDO_USER:-$USER}"

echo
$SUDO docker compose version
echo "Docker is installed. Log out and back in once so you can use it without sudo (setup.sh works either way)."
