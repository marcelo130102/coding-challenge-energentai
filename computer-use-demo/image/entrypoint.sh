#!/bin/bash
set -e

./start_all.sh
./novnc_startup.sh

python http_server.py > /tmp/server_logs.txt 2>&1 &

if [ "${AGENT_BACKEND:-fastapi}" = "streamlit" ]; then
  STREAMLIT_SERVER_PORT=8501 python -m streamlit run computer_use_demo/streamlit.py > /tmp/streamlit_stdout.log 2>&1 &
else
  uvicorn computer_use_demo.agent_service:app --host 0.0.0.0 --port 8501 > /tmp/agent_service.log 2>&1 &
fi

tail -f /dev/null
