#!/usr/bin/env python3
"""
Schnelle System-Status-Prüfung für das Scene Visualizer System
"""
import os
import sys
import json
import pathlib
import psutil
import socket
import subprocess
from datetime import datetime

def check_port(host, port, timeout=2):
    """Prüft ob ein Port offen ist."""
    try:
        sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        sock.settimeout(timeout)
        result = sock.connect_ex((host, port))
        sock.close()
        return result == 0
    except:
        return False

def find_processes(name_pattern):
    """Findet Prozesse mit Namen-Pattern."""
    processes = []
    for proc in psutil.process_iter(['pid', 'name', 'cmdline']):
        try:
            cmdline = ' '.join(proc.info['cmdline']) if proc.info['cmdline'] else ''
            if name_pattern.lower() in proc.info['name'].lower() or name_pattern in cmdline:
                processes.append({
                    'pid': proc.info['pid'],
                    'name': proc.info['name'],
                    'cmdline': cmdline
                })
        except (psutil.NoSuchProcess, psutil.AccessDenied):
            pass
    return processes

def get_log_tail(log_file, lines=5):
    """Holt die letzten Zeilen einer Log-Datei."""
    try:
        if pathlib.Path(log_file).exists():
            with open(log_file, 'r', encoding='utf-8') as f:
                all_lines = f.readlines()
            return all_lines[-lines:] if len(all_lines) >= lines else all_lines
    except:
        pass
    return []

def main():
    print("🔍 === SCENE VISUALIZER SYSTEM STATUS ===")
    print(f"📅 {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print()
    
    # 1. Verzeichnisse und Dateien
    print("📁 DATEISYSTEM:")
    transkript_dir = pathlib.Path("web/transkripte")
    scene_dir = pathlib.Path("web/scene")
    tracking_file = transkript_dir / "transkript_tracking.json"
    
    print(f"   📂 Transkript-Verzeichnis: {'✅' if transkript_dir.exists() else '❌'} {transkript_dir}")
    print(f"   📂 Scene-Verzeichnis: {'✅' if scene_dir.exists() else '❌'} {scene_dir}")
    print(f"   📄 Tracking-Datei: {'✅' if tracking_file.exists() else '❌'} {tracking_file}")
    
    if transkript_dir.exists():
        transcripts = list(transkript_dir.glob("*_transkript.txt"))
        print(f"   📊 Transkripte: {len(transcripts)} gefunden")
        for t in transcripts:
            print(f"      - {t.name}")
    
    print()
    
    # 2. Services und Prozesse
    print("🔧 SERVICES:")
    
    # Ollama
    ollama_port = check_port("127.0.0.1", 11434)
    ollama_procs = find_processes("ollama")
    print(f"   🤖 Ollama:")
    print(f"      Port 11434: {'✅' if ollama_port else '❌'}")
    print(f"      Prozesse: {len(ollama_procs)}")
    for proc in ollama_procs:
        print(f"         PID {proc['pid']}: {proc['name']}")
    
    # Image Service
    img_port = check_port("127.0.0.1", 5555)
    img_procs = find_processes("img_gen_service.py")
    print(f"   🎨 Image Service:")
    print(f"      Port 5555: {'✅' if img_port else '❌'}")
    print(f"      Prozesse: {len(img_procs)}")
    for proc in img_procs:
        print(f"         PID {proc['pid']}: {proc['name']}")
    
    # Scene Visualizer Runner
    runner_procs = find_processes("scene_visualizer_runner.py")
    print(f"   🎬 Scene Visualizer:")
    print(f"      Prozesse: {len(runner_procs)}")
    for proc in runner_procs:
        print(f"         PID {proc['pid']}: {proc['name']}")
    
    print()
    
    # 3. Tracking Status
    print("📊 TRACKING:")
    if tracking_file.exists():
        try:
            with open(tracking_file, 'r', encoding='utf-8') as f:
                tracking_data = json.load(f)
            
            tracked_files = tracking_data.get('transcripts', {})
            print(f"   📄 Erfasste Dateien: {len(tracked_files)}")
            print(f"   🕐 Letzte Aktualisierung: {tracking_data.get('last_updated', 'Unbekannt')}")
            print(f"   📈 Status: {tracking_data.get('status', 'Unbekannt')}")
            
            # Status der einzelnen Dateien
            for filename, info in tracked_files.items():
                status_icon = "🆕" if info.get('status') == 'new' else "✅" if info.get('status') == 'completed' else "🔄"
                print(f"      {status_icon} {filename}: {info.get('status', 'unbekannt')}")
        except Exception as e:
            print(f"   ❌ Fehler beim Lesen: {e}")
    else:
        print("   ❌ Tracking-Datei nicht gefunden")
    
    print()
    
    # 4. Log-Dateien
    print("📋 LOGS (letzte 3 Zeilen):")
    log_files = [
        "scene_runner.log",
        "scene_errors.log", 
        "img_gen_service.log"
    ]
    
    for log_file in log_files:
        print(f"   📄 {log_file}:")
        if pathlib.Path(log_file).exists():
            lines = get_log_tail(log_file, 3)
            if lines:
                for line in lines:
                    print(f"      {line.strip()}")
            else:
                print("      (leer)")
        else:
            print("      ❌ Datei nicht gefunden")
        print()
    
    # 5. Gesamtstatus
    print("🏆 GESAMTSTATUS:")
    issues = []
    
    if not ollama_port:
        issues.append("Ollama Service nicht erreichbar")
    if not img_port:
        issues.append("Image Service nicht erreichbar")
    if not runner_procs:
        issues.append("Scene Visualizer läuft nicht")
    if not tracking_file.exists():
        issues.append("Tracking-System nicht initialisiert")
    
    if issues:
        print("   ❌ PROBLEME GEFUNDEN:")
        for issue in issues:
            print(f"      - {issue}")
        print()
        print("💡 EMPFOHLENE AKTIONEN:")
        if not ollama_port:
            print("   1. Starte Ollama: ./run_ollama.sh")
        if not img_port:
            print("   2. Starte Image Service: python img_gen_service.py")
        if not runner_procs:
            print("   3. Starte Scene Visualizer: python scene_visualizer_runner.py")
        if not tracking_file.exists():
            print("   4. Repariere Tracking: python fix_tracking.py")
        print()
        print("   ODER starte das komplette System: ./start_scene_system.sh")
    else:
        print("   ✅ SYSTEM LÄUFT VOLLSTÄNDIG!")
        
        # Zusätzliche Info bei funktionierendem System
        if transkript_dir.exists():
            transcripts = list(transkript_dir.glob("*_transkript.txt"))
            if tracking_file.exists():
                with open(tracking_file, 'r', encoding='utf-8') as f:
                    tracking_data = json.load(f)
                tracked_count = len(tracking_data.get('transcripts', {}))
                
                if len(transcripts) != tracked_count:
                    print("   ⚠️ Tracking nicht synchronisiert!")
                    print(f"      Dateien im Verzeichnis: {len(transcripts)}")
                    print(f"      Dateien im Tracking: {tracked_count}")
                    print("      → Führe 'python fix_tracking.py' aus")

if __name__ == "__main__":
    main() 