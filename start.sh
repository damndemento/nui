#!/bin/bash
cd /opt/network-manager
source venv/bin/activate

# Set environment variables
export FLASK_SECRET_KEY="c5521ab2e51b07b079aad5258ffb8ff719f40e6925f19e8d184c059b1f25bd68"
export FLASK_PORT=5000
export FLASK_BIND_ADDRESS="0.0.0.0"

# Start the application
python3 network-manager.py
