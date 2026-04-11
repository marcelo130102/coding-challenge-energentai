#!/bin/bash
set -e

./start_all.sh
./novnc_startup.sh

python http_server.py > /tmp/server_logs.txt 2>&1 &

# FastAPI agent WebSocket (same port as legacy Streamlit). Override with AGENT_BACKEND=streamlit
if [ "${AGENT_BACKEND:-fastapi}" = "streamlit" ]; then
  echo "Starting agent UI: Streamlit on port 8501 (WebSocket relay to FastAPI will NOT work)."
  STREAMLIT_SERVER_PORT=8501 python -m streamlit run computer_use_demo/streamlit.py > /tmp/streamlit_stdout.log &
else
  echo "Starting agent UI: uvicorn computer_use_demo.agent_service on port 8501 (for API WebSocket relay)."
  uvicorn computer_use_demo.agent_service:app --host 0.0.0.0 --port 8501 > /tmp/agent_service.log 2>&1 &
fi

echo "✨ Computer Use Demo is ready!"
echo "➡️  Open http://localhost:8080 in your browser to begin"

# Keep the container running
tail -f /dev/null
