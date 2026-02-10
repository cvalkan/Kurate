#!/bin/bash
# Ensure frontend build exists before starting serve
cd /app/frontend

if [ ! -f "build/index.html" ]; then
    echo "Build directory missing — rebuilding..."
    yarn build
    echo "Build complete."
else
    echo "Build exists — starting serve."
fi

# Copy serve.json to build directory for headers config
cp /app/frontend/serve.json /app/frontend/build/serve.json 2>/dev/null || true

exec npx serve -s build -l 3000
