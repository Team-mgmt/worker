#!/bin/bash

SCRIPT_DIRECTORY="$(dirname "$0")"
CURRENT_DIRECTORY="$(realpath "${PWD}/${SCRIPT_DIRECTORY}")"
PROJECT_DIRECTORY="$(realpath "${CURRENT_DIRECTORY}"/../)"

if [[ ! -d "${PROJECT_DIRECTORY}/build" ]]; then
  mkdir -p "${PROJECT_DIRECTORY}/build"
fi

if [[ ! -d "${PROJECT_DIRECTORY}/build/shelfalign-web" ]]; then
  git clone git@github.com/ShelfAlign-tech/web.git "${PROJECT_DIRECTORY}/build/shelfalign-web"
  # We always check out to develop - this script is only used in develop builds
  git checkout develop
else
  cd "${PROJECT_DIRECTORY}/build/shelfalign-web" || exit 1
  git pull
fi
