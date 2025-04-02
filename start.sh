#!/bin/bash
cd /opt/network-manager
source venv/bin/activate

# Set environment variables
export FLASK_SECRET_KEY="<my-flask-secret-code>"
export FLASK_PORT=5000
export FLASK_BIND_ADDRESS="0.0.0.0"

# Start the application
python3 network-manager.py
