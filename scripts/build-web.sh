#!/usr/bin/env sh
# Instala dependencias de la web y la compila en web/dist (la sirve el servidor).
set -e
cd "$(dirname "$0")/../web"
npm install
npm run build
echo "Web compilada en web/dist"
