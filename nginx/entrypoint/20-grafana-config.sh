#!/bin/sh

set -eu

mkdir -p /etc/nginx/snippets

GRAFANA_CONFIG="/etc/nginx/snippets/grafana.conf"

if [ "${MONITORING_PROFILE:-disabled}" = "enabled" ]; then
    cat > "$GRAFANA_CONFIG" <<EOF
location /grafana/ {
    auth_basic "Monitoring";
    auth_basic_user_file /etc/nginx/grafana.htpasswd;

    proxy_pass http://grafana:3000;

    proxy_set_header Host \$host;
    proxy_set_header X-Real-IP \$remote_addr;
    proxy_set_header X-Forwarded-For \$proxy_add_x_forwarded_for;
    proxy_set_header X-Forwarded-Proto \$scheme;

    proxy_http_version 1.1;

    proxy_set_header Upgrade \$http_upgrade;
    proxy_set_header Connection "upgrade";

    proxy_redirect
        http://grafana:3000/
        /grafana/;
}
EOF
else
    cat > "$GRAFANA_CONFIG" <<EOF
location /grafana/ {
    return 404;
}
EOF
fi
