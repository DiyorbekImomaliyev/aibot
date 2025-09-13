#!/bin/bash

# Check Python
if ! command -v python3 &> /dev/null; then
    echo "no python"
    exit 1
fi

# Check FFmpeg
if ! command -v ffmpeg &> /dev/null; then
    echo "no ffmpeg."
    if [[ "$OSTYPE" == "darwin"* ]]; then
        brew install ffmpeg
    else
        sudo apt-get update && sudo apt-get install -y ffmpeg
    fi
fi

# Create virtual environment if needed
if [ ! -d "venv" ]; then
    echo "going environment"
    python3 -m venv venv
fi

# Activate and install
source venv/bin/activate
echo "packages"
pip install -q --upgrade pip
pip install -q -r requirements.txt

# Check .env
if [ ! -f ".env" ]; then
    echo ".env file"
    cp .env.example .env 2>/dev/null || {
        echo "TELEGRAM_BOT_TOKEN=your_api_key" > .env
        echo "OPENAI_API_KEY=your_api_key" >> .env
    }
    echo "no api keys "
    exit 1
fi

# Run
echo "Starting bot"
python run.py