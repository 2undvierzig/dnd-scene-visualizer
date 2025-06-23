#!/bin/bash

echo "🔥 === Ollama Killer ==="

PORT=11434

# Funktion: Alle PIDs sammeln (ohne dieses Skript selbst)
collect_all_ollama_pids() {
    local all_pids=""
    local current_script_pid=$$
    
    # Methode 1: Port-basiert
    local port_pid=$(lsof -ti :$PORT 2>/dev/null)
    if [ -n "$port_pid" ]; then
        all_pids="$all_pids $port_pid"
    fi
    
    # Methode 2: Ollama Service Binary (echte Ollama-Prozesse)
    local bin_pids=$(pgrep -f "/ollama" 2>/dev/null | tr '\n' ' ')
    if [ -n "$bin_pids" ]; then
        all_pids="$all_pids $bin_pids"
    fi
    
    # Methode 3: Spezifische ollama/bin/ollama
    local specific_pids=$(pgrep -f "ollama/bin/ollama" 2>/dev/null | tr '\n' ' ')
    if [ -n "$specific_pids" ]; then
        all_pids="$all_pids $specific_pids"
    fi
    
    # Methode 4: Ollama Server Prozesse (aber nicht Skripte)
    local server_pids=$(ps aux | grep -E "ollama.*serve|ollama.*run" | grep -v grep | grep -v "kill_ollama" | awk '{print $2}' | tr '\n' ' ')
    if [ -n "$server_pids" ]; then
        all_pids="$all_pids $server_pids"
    fi
    
    # Duplikate entfernen, sortieren und aktuelles Skript ausschließen
    echo "$all_pids" | tr ' ' '\n' | sort -u | grep -E '^[0-9]+$' | grep -v "^$current_script_pid$" | tr '\n' ' '
}

# Funktion: Prozessgruppe beenden
kill_process_group() {
    local pid=$1
    local signal=$2
    
    if kill -0 $pid 2>/dev/null; then
        # Versuche die gesamte Prozessgruppe zu beenden
        local pgid=$(ps -o pgid= -p $pid 2>/dev/null | tr -d ' ')
        if [ -n "$pgid" ] && [ "$pgid" != "1" ]; then
            echo "🔫 Beende Prozessgruppe $pgid (Signal: $signal)..."
            kill $signal -$pgid 2>/dev/null
        else
            echo "🔫 Beende Prozess $pid (Signal: $signal)..."
            kill $signal $pid 2>/dev/null
        fi
    fi
}

echo "🔍 Sammle alle Ollama-Prozesse..."
ALL_PIDS=$(collect_all_ollama_pids)

if [ -z "$ALL_PIDS" ]; then
    echo "✅ Keine Ollama-Prozesse gefunden!"
    exit 0
fi

echo "📍 Gefundene Ollama-Prozesse: $ALL_PIDS"

# Zeige Prozessdetails
echo "📊 Prozessdetails:"
for pid in $ALL_PIDS; do
    if kill -0 $pid 2>/dev/null; then
        ps -p $pid -o pid,ppid,pgid,cmd 2>/dev/null || echo "   PID $pid: (Details nicht verfügbar)"
    fi
done

echo ""
echo "🔫 Phase 1: Graceful Shutdown (SIGTERM)..."

# Alle Prozesse gleichzeitig mit SIGTERM beenden
for pid in $ALL_PIDS; do
    kill_process_group $pid ""
done

echo "⏳ Warte 3 Sekunden..."
sleep 3

# Prüfe welche Prozesse noch laufen
echo "🔍 Prüfe verbleibende Prozesse..."
REMAINING_PIDS=""
for pid in $ALL_PIDS; do
    if kill -0 $pid 2>/dev/null; then
        REMAINING_PIDS="$REMAINING_PIDS $pid"
    fi
done

if [ -n "$REMAINING_PIDS" ]; then
    echo "💀 Phase 2: Force Kill (SIGKILL) für verbleibende Prozesse: $REMAINING_PIDS"
    
    for pid in $REMAINING_PIDS; do
        kill_process_group $pid "-9"
    done
    
    echo "⏳ Warte 2 Sekunden..."
    sleep 2
fi

# Finale Prüfung
echo "🔍 Finale Prüfung..."

# Port-Check
FINAL_PORT_PID=$(lsof -ti :$PORT 2>/dev/null)
if [ -n "$FINAL_PORT_PID" ]; then
    echo "⚠️  WARNUNG: Port $PORT ist immer noch besetzt von PID $FINAL_PORT_PID"
    echo "💀 Letzter Versuch: Force kill..."
    kill -9 $FINAL_PORT_PID 2>/dev/null
    sleep 1
fi

# Ollama-Prozess-Check
FINAL_OLLAMA_PIDS=$(collect_all_ollama_pids)
if [ -n "$FINAL_OLLAMA_PIDS" ]; then
    echo "⚠️  WARNUNG: Ollama-Prozesse laufen immer noch: $FINAL_OLLAMA_PIDS"
    echo "💀 Letzter Force-Kill-Versuch..."
    for pid in $FINAL_OLLAMA_PIDS; do
        kill -9 $pid 2>/dev/null
    done
    sleep 1
fi

# Endgültige Prüfung
TRULY_FINAL_PORT=$(lsof -ti :$PORT 2>/dev/null)
TRULY_FINAL_PIDS=$(collect_all_ollama_pids)

if [ -n "$TRULY_FINAL_PORT" ] || [ -n "$TRULY_FINAL_PIDS" ]; then
    echo "❌ FEHLER: Ollama konnte nicht vollständig beendet werden!"
    echo "   Port $PORT: $(lsof -ti :$PORT 2>/dev/null || echo 'frei')"
    echo "   Verbleibende Prozesse: $(collect_all_ollama_pids || echo 'keine')"
    
    echo ""
    echo "🔍 Detaillierte Prozessanalyse:"
    ps aux | grep -E "(ollama|\.ollama)" | grep -v grep || echo "   Keine ollama-Prozesse in ps aux"
    
    exit 1
else
    echo "✅ Port $PORT ist frei!"
    echo "✅ Keine Ollama-Prozesse mehr vorhanden!"
    echo "🎉 Ollama erfolgreich beendet!"
    exit 0
fi

