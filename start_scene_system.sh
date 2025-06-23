#!/bin/bash

# Scene Visualizer System Starter
echo "🎬 === Scene Visualizer System Starter ==="

# Farben für bessere Lesbarkeit
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m' # No Color

# Funktionen
log_info() {
    echo -e "${GREEN}[INFO]${NC} $1"
}

log_warn() {
    echo -e "${YELLOW}[WARN]${NC} $1"
}

log_error() {
    echo -e "${RED}[ERROR]${NC} $1"
}

log_debug() {
    echo -e "${BLUE}[DEBUG]${NC} $1"
}

# Cleanup Funktion
cleanup() {
    log_info "🛑 Stoppe alle Services..."
    
    if [ ! -z "$IMAGE_SERVICE_PID" ]; then
        log_info "Stoppe Image Service (PID: $IMAGE_SERVICE_PID)"
        kill $IMAGE_SERVICE_PID 2>/dev/null
    fi
    
    if [ ! -z "$RUNNER_PID" ]; then
        log_info "Stoppe Scene Runner (PID: $RUNNER_PID)"
        kill $RUNNER_PID 2>/dev/null
    fi
    
    # Stoppe Ollama explizit
    log_info "🔥 Stoppe Ollama Service..."
    if [ -f "./kill_ollama.sh" ]; then
        ./kill_ollama.sh
    else
        log_warn "kill_ollama.sh nicht gefunden, versuche manuell..."
        # Fallback: direkt über Port stoppen
        OLLAMA_PID=$(lsof -ti :11434 2>/dev/null)
        if [ ! -z "$OLLAMA_PID" ]; then
            kill -9 "$OLLAMA_PID" 2>/dev/null
            log_info "Ollama Prozess (PID: $OLLAMA_PID) beendet"
        fi
    fi
    
    # Warte kurz
    sleep 2
    
    log_info "✅ Alle Services gestoppt"
    exit 0
}

# Signal Handler
trap cleanup SIGINT SIGTERM

log_info "Starte Scene Visualizer System..."

# Systeminfo für Debugging
log_debug "💻 Systeminfo:"
log_debug "   Hostname: $(hostname)"
log_debug "   Python: $(python3 --version 2>/dev/null || echo 'Nicht verfügbar')"
log_debug "   GPU: $(nvidia-smi --query-gpu=name --format=csv,noheader 2>/dev/null | head -1 || echo 'Nicht verfügbar')"
log_debug "   Arbeitsverzeichnis: $(pwd)"

# Erstelle benötigte Verzeichnisse
log_info "📁 Erstelle Verzeichnisse..."
mkdir -p web/transkripte
mkdir -p web/scene
mkdir -p outputs
log_info "✅ Verzeichnisse erstellt"

# Prüfe Abhängigkeiten
log_info "🔍 Prüfe Abhängigkeiten..."

if ! command -v python3 &> /dev/null; then
    log_error "Python3 nicht gefunden!"
    exit 1
fi

# Prüfe Python-Module
log_debug "🐍 Prüfe Python-Module..."
MISSING_MODULES=""

# Einzeln testen für bessere Fehlerdiagnose
python3 -c "import ollama" 2>/dev/null || MISSING_MODULES="$MISSING_MODULES ollama"
python3 -c "import watchdog" 2>/dev/null || MISSING_MODULES="$MISSING_MODULES watchdog"
python3 -c "import parse_scene_transkript" 2>/dev/null || MISSING_MODULES="$MISSING_MODULES parse_scene_transkript"
python3 -c "import img_gen" 2>/dev/null || MISSING_MODULES="$MISSING_MODULES img_gen"

# Für Image Service zusätzlich prüfen
python3 -c "import torch, diffusers" 2>/dev/null || MISSING_MODULES="$MISSING_MODULES torch/diffusers"

if [ -n "$MISSING_MODULES" ]; then
    log_warn "⚠️ Fehlende Python-Module:$MISSING_MODULES"
    log_warn "   Installiere mit: pip install ollama watchdog torch diffusers transformers"
else
    log_info "✅ Alle erforderlichen Python-Module verfügbar"
fi

# Prüfe/Erstelle Konfigurationsdateien
if [ ! -f "img_gen_service.json" ]; then
    log_warn "img_gen_service.json nicht gefunden - erstelle Standard-Konfiguration..."
    cat > img_gen_service.json << 'EOF'
{
    "host": "127.0.0.1",
    "port": 5555,
    "model_id": "black-forest-labs/FLUX.1-dev",
    "lora_repo": "SouthbayJay/dnd-style-flux",
    "lora_weight": "dnd_style_flux.safetensors",
    "dtype": "bfloat16",
    "output_dir": "web/scene"
}
EOF
    log_info "✅ Image Service Konfiguration erstellt"
fi

# Starte Ollama Service
log_info "🔮 Starte Ollama Service..."
if [ -f "./run_ollama.sh" ]; then
    ./run_ollama.sh &
    OLLAMA_PID=$!
    log_info "📍 Ollama gestartet (PID: $OLLAMA_PID)"
    
    # Warte auf Ollama
    log_info "⏳ Warte auf Ollama Service..."
    OLLAMA_READY=false
    for i in {1..12}; do  # 60 Sekunden Maximum
        if curl -s http://localhost:11434/api/tags >/dev/null 2>&1; then
            log_info "✅ Ollama Service bereit nach ${i}x5s"
            OLLAMA_READY=true
            break
        fi
        sleep 5
    done
    
    if [ "$OLLAMA_READY" = "false" ]; then
        log_error "❌ Ollama Service konnte nicht gestartet werden"
        cleanup
        exit 1
    fi
else
    log_warn "run_ollama.sh nicht gefunden - Ollama muss extern laufen!"
fi

# Starte Image Service
log_info "🎨 Starte Image Service (FLUX.1-dev + DnD LoRA)..."
log_warn "⚠️ Dies kann 30-60 Sekunden dauern (Model Loading)..."

# Prüfe ob img_gen_service.py existiert
if [ ! -f "img_gen_service.py" ]; then
    log_error "❌ img_gen_service.py nicht gefunden!"
    exit 1
fi

# Zeige Konfiguration
log_debug "📋 Image Service Konfiguration:"
cat img_gen_service.json | sed 's/^/    /'

# Starte Image Service mit Logging
log_info "🚀 Starte img_gen_service.py..."
python3 img_gen_service.py 2>&1 | tee img_gen_service.log &
IMAGE_SERVICE_PID=$!
log_info "📍 Image Service gestartet mit PID: $IMAGE_SERVICE_PID"

# Warte auf Model Loading
log_info "⏳ Warte auf Image Service Model Loading..."
IMAGE_SERVICE_READY=false
for i in {1..24}; do  # 2 Minuten Maximum
    # Prüfe ob Prozess noch läuft
    if ! kill -0 $IMAGE_SERVICE_PID 2>/dev/null; then
        log_error "❌ Image Service Prozess ($IMAGE_SERVICE_PID) ist abgestürzt!"
        log_info "🔍 Prüfe Logs für Fehlerdetails..."
        if [ -f "img_gen_service.log" ]; then
            log_error "📋 Letzte Zeilen aus img_gen_service.log:"
            tail -5 img_gen_service.log | sed 's/^/    /'
        fi
        exit 1
    fi
    
    # Prüfe Port-Verfügbarkeit
    if nc -z 127.0.0.1 5555 2>/dev/null; then
        log_info "✅ Image Service bereit nach ${i}x5s (PID: $IMAGE_SERVICE_PID)"
        IMAGE_SERVICE_READY=true
        break
    else
        if [ $((i % 6)) -eq 0 ]; then  # Alle 30s Statusupdate
            log_info "⏳ Model Loading... (${i}/24)"
        fi
        sleep 5
    fi
done

if [ "$IMAGE_SERVICE_READY" = "false" ]; then
    log_error "❌ Image Service konnte nicht gestartet werden nach 2 Minuten"
    cleanup
    exit 1
fi

# Starte Scene Visualizer Runner
log_info "🎬 Starte Scene Visualizer Runner..."
python3 scene_visualizer_runner.py &
RUNNER_PID=$!

log_info "🚀 System gestartet!"
log_info "📊 Status:"
log_info "  - Scene Runner PID: $RUNNER_PID"
log_info "  - Image Service PID: $IMAGE_SERVICE_PID"
log_info "  - Transkript-Verzeichnis: web/transkripte/"
log_info "  - Scene-Output: web/scene/"
log_info "  - Logs: scene_runner.log, scene_errors.log, img_gen_service.log"

log_info "💡 Drücke Strg+C zum Beenden"
log_info "👁️ System überwacht web/transkripte/ auf neue Dateien..."

# Warte auf Runner-Prozess
wait $RUNNER_PID

log_info "🔻 Scene Runner beendet"
cleanup 