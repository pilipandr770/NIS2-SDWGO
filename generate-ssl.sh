#!/bin/bash
# Run this script once to generate a self-signed SSL certificate for local development.
# For production, replace ssl/cert.pem and ssl/key.pem with a real certificate (Let's Encrypt).
mkdir -p ssl
openssl req -x509 -nodes -days 365 -newkey rsa:2048 \
  -keyout ssl/key.pem \
  -out ssl/cert.pem \
  -subj "/C=DE/ST=Hessen/L=Frankfurt/O=AndriiIT/CN=andrii-it.de"
echo "Self-signed certificate generated in ./ssl/"
echo "For production: replace ssl/cert.pem and ssl/key.pem with a valid certificate."
