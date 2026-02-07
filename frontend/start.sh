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

exec npx serve -s build -l 3000
