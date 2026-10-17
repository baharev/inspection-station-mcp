#!/usr/bin/env bash
# Start a demo login server (Keycloak) in a container, with the users and roles of
# keycloak/inspection-realm.json.
#
#     scripts/keycloak.sh            # http://localhost:8080, this computer only
#     scripts/keycloak.sh --https    # https://<this computer>:8443, for other computers too;
#                                    # needs scripts/make_certs.sh first
#
# MCP_SERVER_URL: the inspection server's address, which its tokens are issued for
# (default http://localhost:8000/mcp). Everything is created fresh at each start and
# forgotten when it stops (Ctrl+C). Administration: /admin, user admin, with a password
# made new at each start and shown first (the users' passwords are known, for trying it
# out; the administrator's never is, since --https lets other computers reach the page).
set -euo pipefail
cd "$(dirname "$0")/.."
args=(-p 127.0.0.1:8080:8080)
options=()
admin_page=http://localhost:8080/admin
if [ "${1:-}" = "--https" ]; then
    [ -f certs/server.pem ] || { echo "No certs/server.pem: run scripts/make_certs.sh first."; exit 1; }
    args=(-p 8443:8443 -v ./certs:/opt/keycloak/conf/certs:ro,Z)
    options=(--https-certificate-file=/opt/keycloak/conf/certs/server.pem
             --https-certificate-key-file=/opt/keycloak/conf/certs/server.key --http-enabled=false)
    admin_page="https://<this computer>:8443/admin"
fi
admin_password=$(head -c 16 /dev/urandom | od -An -tx1 | tr -d ' \n')
echo "Administration: $admin_page, user admin, password $admin_password"
exec podman run --rm --name inspection-keycloak "${args[@]}" \
    -e KC_BOOTSTRAP_ADMIN_USERNAME=admin -e KC_BOOTSTRAP_ADMIN_PASSWORD="$admin_password" \
    -e MCP_SERVER_URL="${MCP_SERVER_URL:-http://localhost:8000/mcp}" \
    -v ./keycloak:/opt/keycloak/data/import:ro,Z \
    quay.io/keycloak/keycloak:26.7.4 start-dev --import-realm "${options[@]}"
