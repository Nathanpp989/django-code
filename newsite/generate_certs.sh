#!/bin/bash
# =============================================================================
# Certificate Generation Script for Django LLM
# Generates:
#   - Certificate Authority (CA)
#   - Server certificate (signed by CA)
#   - Client certificate (signed by CA) for mTLS
#
# Usage:
#   chmod +x generate_certs.sh
#   ./generate_certs.sh
#
# For production, replace this with Let's Encrypt:
#   sudo certbot --nginx -d your_domain.com
# =============================================================================

set -e  # Exit on any error

# -------------------------
# Configuration
# -------------------------
CERT_DIR="/etc/nginx/ssl"
DAYS_VALID=365
KEY_SIZE=4096
COUNTRY="US"
STATE="Local"
CITY="Local"
ORG="DjangoLLM"
DOMAIN="localhost"

echo "Creating certificate directory at $CERT_DIR..."
sudo mkdir -p "$CERT_DIR"
sudo chmod 755 "$CERT_DIR"

# -------------------------
# Step 1: Generate Certificate Authority (CA)
# The CA signs both server and client certificates
# -------------------------
echo ""
echo "=== Step 1: Generating Certificate Authority (CA) ==="

# CA private key
sudo openssl genrsa -out "$CERT_DIR/ca.key" $KEY_SIZE
echo "✓ CA private key generated"

# CA certificate (self-signed)
sudo openssl req -new -x509 \
    -days $DAYS_VALID \
    -key "$CERT_DIR/ca.key" \
    -out "$CERT_DIR/ca.crt" \
    -subj "/C=$COUNTRY/ST=$STATE/L=$CITY/O=$ORG CA/CN=$ORG Root CA"
echo "✓ CA certificate generated"

# -------------------------
# Step 2: Generate Server Certificate
# Used by NGINX to serve HTTPS
# -------------------------
echo ""
echo "=== Step 2: Generating Server Certificate ==="

# Server private key
sudo openssl genrsa -out "$CERT_DIR/server.key" $KEY_SIZE
echo "✓ Server private key generated"

# Server Certificate Signing Request (CSR)
sudo openssl req -new \
    -key "$CERT_DIR/server.key" \
    -out "$CERT_DIR/server.csr" \
    -subj "/C=$COUNTRY/ST=$STATE/L=$CITY/O=$ORG/CN=$DOMAIN"
echo "✓ Server CSR generated"

# Create server certificate extensions file
sudo bash -c "cat > $CERT_DIR/server_ext.cnf << EOF
[req]
req_extensions = v3_req
distinguished_name = req_distinguished_name

[req_distinguished_name]

[v3_req]
basicConstraints = CA:FALSE
keyUsage = nonRepudiation, digitalSignature, keyEncipherment
extendedKeyUsage = serverAuth
subjectAltName = @alt_names

[alt_names]
DNS.1 = localhost
DNS.2 = *.localhost
IP.1 = 127.0.0.1
IP.2 = ::1
EOF"

# Sign server certificate with CA
sudo openssl x509 -req \
    -days $DAYS_VALID \
    -in "$CERT_DIR/server.csr" \
    -CA "$CERT_DIR/ca.crt" \
    -CAkey "$CERT_DIR/ca.key" \
    -CAcreateserial \
    -out "$CERT_DIR/server.crt" \
    -extfile "$CERT_DIR/server_ext.cnf" \
    -extensions v3_req
echo "✓ Server certificate signed by CA"

# -------------------------
# Step 3: Generate Client Certificate
# Used for mutual TLS (mTLS) authentication
# Clients must present this certificate to access the server
# -------------------------
echo ""
echo "=== Step 3: Generating Client Certificate ==="

# Client private key
sudo openssl genrsa -out "$CERT_DIR/client.key" $KEY_SIZE
echo "✓ Client private key generated"

# Client CSR
sudo openssl req -new \
    -key "$CERT_DIR/client.key" \
    -out "$CERT_DIR/client.csr" \
    -subj "/C=$COUNTRY/ST=$STATE/L=$CITY/O=$ORG/CN=django-llm-client"
echo "✓ Client CSR generated"

# Create client certificate extensions file
sudo bash -c "cat > $CERT_DIR/client_ext.cnf << EOF
[req]
req_extensions = v3_req
distinguished_name = req_distinguished_name

[req_distinguished_name]

[v3_req]
basicConstraints = CA:FALSE
keyUsage = nonRepudiation, digitalSignature, keyEncipherment
extendedKeyUsage = clientAuth
EOF"

# Sign client certificate with CA
sudo openssl x509 -req \
    -days $DAYS_VALID \
    -in "$CERT_DIR/client.csr" \
    -CA "$CERT_DIR/ca.crt" \
    -CAkey "$CERT_DIR/ca.key" \
    -CAcreateserial \
    -out "$CERT_DIR/client.crt" \
    -extfile "$CERT_DIR/client_ext.cnf" \
    -extensions v3_req
echo "✓ Client certificate signed by CA"

# -------------------------
# Step 4: Package client certificate for browser import
# Creates a .p12 file that can be imported into browsers
# -------------------------
echo ""
echo "=== Step 4: Packaging Client Certificate for Browser ==="

sudo openssl pkcs12 -export \
    -out "$CERT_DIR/client.p12" \
    -inkey "$CERT_DIR/client.key" \
    -in "$CERT_DIR/client.crt" \
    -certfile "$CERT_DIR/ca.crt" \
    -passout pass:djangollm \
    -legacy
echo "✓ Client certificate packaged as client.p12 (password: djangollm)"

# -------------------------
# Step 5: Set correct permissions
# Private keys must not be world-readable
# -------------------------
echo ""
echo "=== Step 5: Setting Permissions ==="

sudo chmod 600 "$CERT_DIR"/*.key
sudo chmod 644 "$CERT_DIR"/*.crt
sudo chmod 644 "$CERT_DIR"/*.p12
sudo chmod 644 "$CERT_DIR"/*.csr
echo "✓ Permissions set"

# -------------------------
# Step 6: Verify certificates
# -------------------------
echo ""
echo "=== Step 6: Verifying Certificates ==="

echo "Verifying server certificate against CA..."
sudo openssl verify -CAfile "$CERT_DIR/ca.crt" "$CERT_DIR/server.crt"

echo "Verifying client certificate against CA..."
sudo openssl verify -CAfile "$CERT_DIR/ca.crt" "$CERT_DIR/client.crt"

# -------------------------
# Summary
# -------------------------
echo ""
echo "============================================="
echo "Certificate generation complete!"
echo "============================================="
echo ""
echo "Files generated in $CERT_DIR:"
echo "  ca.crt        - Certificate Authority certificate"
echo "  ca.key        - Certificate Authority private key (keep secret)"
echo "  server.crt    - Server certificate"
echo "  server.key    - Server private key (keep secret)"
echo "  client.crt    - Client certificate"
echo "  client.key    - Client private key"
echo "  client.p12    - Client certificate bundle for browser import"
echo ""
echo "Next steps:"
echo "  1. Copy client.p12 to your local machine"
echo "  2. Import client.p12 into your browser (password: djangollm)"
echo "  3. Add ca.crt to your browser's trusted CAs"
echo "  4. Run: sudo nginx -t && sudo service nginx restart"
echo ""
echo "To copy client.p12 to your local machine:"
echo "  scp user@server:/etc/nginx/ssl/client.p12 ~/Downloads/"