#!/bin/bash

HASH_UPDATE_COUNT=0
TOTAL_WHEEL_COUNT=0

WHEEL_PATH="$1"
REQUIREMENTS_FILE="$2"

for whl in "${WHEEL_PATH}"/*.whl; do
  TOTAL_WHEEL_COUNT=$((TOTAL_WHEEL_COUNT + 1))

  whl_file="${whl##*/}"
  pkg_name="${whl_file%%-[0-9]*}"
  pkg_name="${pkg_name//_/-}"
  pkg_name="${pkg_name,,}"
  hash_line="$(sha256sum "${whl}")"
  new_hash="${hash_line%% *}"
  
  if ! grep -q "^${pkg_name}==" "${REQUIREMENTS_FILE}"; then
    echo "Package ${pkg_name} not found in ${REQUIREMENTS_FILE}, skipping..."
    continue
  fi

  if grep -q "${new_hash}" "${REQUIREMENTS_FILE}"; then
    continue
  fi
  
  # Wheel was built from source (hash mismatch)

  # Check the requirements entry for the package is multiline
  HASH_UPDATE_COUNT=$((HASH_UPDATE_COUNT + 1))
  if ! grep -q "^${pkg_name}==.*\\\\$" "${REQUIREMENTS_FILE}"; then
    # Single line entry, convert to multiline with the new hash
    sed -i "/^${pkg_name}==/s/\$/ \\\\/" "${REQUIREMENTS_FILE}"
  fi
  sed -i "/^${pkg_name}==/a    --hash=sha256:${new_hash} # built from source\\\\" "${REQUIREMENTS_FILE}"
  echo "Updated hash for package: ${pkg_name}"
done

echo "Updated hashes: ${HASH_UPDATE_COUNT}/${TOTAL_WHEEL_COUNT}"
