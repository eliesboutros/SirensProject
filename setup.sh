#!/usr/bin/env bash
# Sirens — one-shot setup. Run once:   bash setup.sh
# Creates a local environment and installs everything, including the models.
set -e
cd "$(dirname "$0")"
echo "==> Creating virtual environment (.venv)"
python3 -m venv .venv || { echo "Installing python venv support (may ask for password)"; sudo apt-get install -y python3-venv && python3 -m venv .venv; }
echo "==> Activating and installing dependencies"
# shellcheck disable=SC1091
source .venv/bin/activate
pip install --upgrade pip
pip install -r requirements.txt
echo "==> Installing spaCy models (NER + word vectors)"
pip install https://github.com/explosion/spacy-models/releases/download/en_core_web_sm-3.8.0/en_core_web_sm-3.8.0-py3-none-any.whl
pip install https://github.com/explosion/spacy-models/releases/download/en_core_web_md-3.8.0/en_core_web_md-3.8.0-py3-none-any.whl
echo "==> Offline street map (one-time download; Sirens works without it)"
bash scripts/map/get_map.sh || true
echo ""
echo "==> Done. To use Sirens:"
echo "      source .venv/bin/activate"
echo "      python app.py            # web console: http://127.0.0.1:5000"
echo ""
echo "   Optional local AI: install Ollama and pull the model named by"
echo "   DEFAULT_MODEL in linker/ai.py. No API keys are needed."
