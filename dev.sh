#!/bin/bash
# Kill any existing server on port 5000 and restart
PORT=${1:-5000}
lsof -ti:$PORT 2>/dev/null | xargs kill -9 2>/dev/null
echo "Starting server on port $PORT..."
uv run python scraperpdf.py --serve --port $PORT
