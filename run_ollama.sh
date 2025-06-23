export OLLAMA_KEEP_ALIVE=240m
export OLLAMA_HOST=0.0.0.0:11434
export OLLAMA_MODELS=./ollama/models
./ollama/bin/ollama serve &
