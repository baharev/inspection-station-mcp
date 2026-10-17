#!/usr/bin/env bash
# Make HTTPS certificates for this computer, for running across two computers on one
# network: a private certificate authority (CA) and a certificate signed by it, in certs/
# (kept out of git). The other computer trusts certs/ca.pem.
#
#     scripts/make_certs.sh <address>...   e.g. scripts/make_certs.sh 192.168.0.20 camera-pc
#
# Every address the other computer uses to reach this one must be listed (IP addresses
# and host names). The CA's private key is deleted once it has signed: a CA the other
# computer trusts could otherwise vouch for any website, in the hands of whoever got the key.
# Run it again to replace both; the other computer then needs the new certs/ca.pem.
set -euo pipefail
[ $# -ge 1 ] || { sed -n '2,11p' "$0"; exit 1; }
cd "$(dirname "$0")/.."
mkdir -p certs && cd certs
trap 'rm -f ca.key ca.srl server.csr' EXIT   # also if a step fails
openssl req -x509 -newkey rsa:2048 -nodes -days 365 -subj "/CN=Inspection camera demo CA" \
    -addext "basicConstraints=critical,CA:TRUE" -addext "keyUsage=critical,keyCertSign,cRLSign" \
    -keyout ca.key -out ca.pem 2>/dev/null
names="DNS:localhost,IP:127.0.0.1"
for address in "$@"; do
    if [[ $address =~ ^[0-9.]+$ ]]; then names+=",IP:$address"; else names+=",DNS:$address"; fi
done
openssl req -newkey rsa:2048 -nodes -subj "/CN=$1" -keyout server.key -out server.csr 2>/dev/null
openssl x509 -req -in server.csr -CA ca.pem -CAkey ca.key -CAcreateserial -days 365 \
    -extfile <(printf '%s\n' "subjectAltName=$names" "basicConstraints=CA:FALSE" \
        "keyUsage=critical,digitalSignature,keyEncipherment" "extendedKeyUsage=serverAuth" \
        "subjectKeyIdentifier=hash" "authorityKeyIdentifier=keyid") \
    -out server.pem 2>/dev/null
chmod 644 server.key   # the login server's container runs as another user and must read it
echo "certs/server.pem is valid for: $names"
echo "The other computer trusts certs/ca.pem (new: copy it there again)."
