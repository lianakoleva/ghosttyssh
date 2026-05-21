#!/bin/bash    
if [ ! -d ".venv" ]; then
    echo "Creating virtual environment..."
    python3 -m venv .venv
else
    echo "Virtual environment already exists."
fi
rm -rf build ghosttyssh.egg-info
source .venv/bin/activate
brew install pipx
pipx ensurepath
pipx install . --force
echo "Installed ghosttyssh to ~/.local/bin/ghosttyssh"
