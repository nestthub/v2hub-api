#!/bin/sh
# Generates /etc/nginx/conf.d/00-limit-key-map.conf from the
# TRUSTED_NOLIMIT_IPS env var (comma-separated list of IPs exempt from
# rate limiting), before nginx's built-in envsubst-on-templates step runs.
#
# Runs as part of /docker-entrypoint.d/ (numbered before the built-in
# 20-envsubst-on-templates.sh so the resulting *.template files can
# `include` this generated file).
set -eu

OUT_DIR="/etc/nginx/conf.d"
OUT_FILE="$OUT_DIR/00-limit-key-map.conf"

mkdir -p "$OUT_DIR"

{
    echo "# Auto-generated from \$TRUSTED_NOLIMIT_IPS — do not edit by hand."
    echo "map \$remote_addr \$limit_key {"
    echo "    default         \$binary_remote_addr;"

    if [ -n "${TRUSTED_NOLIMIT_IPS:-}" ]; then
        # Split on commas, trim whitespace, skip empty entries.
        old_ifs="$IFS"
        IFS=','
        for ip in $TRUSTED_NOLIMIT_IPS; do
            IFS="$old_ifs"
            trimmed=$(echo "$ip" | sed 's/^[[:space:]]*//; s/[[:space:]]*$//')
            if [ -n "$trimmed" ]; then
                echo "    $trimmed  \"\";"
            fi
            IFS=','
        done
        IFS="$old_ifs"
    fi

    echo "}"
} > "$OUT_FILE"

echo "Generated $OUT_FILE:"
cat "$OUT_FILE"
