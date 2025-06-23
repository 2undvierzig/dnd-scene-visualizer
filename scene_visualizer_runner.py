#!/usr/bin/env python3
"""
Scene Visualizer Runner - Überwacht Transkripte und generiert automatisch Bilder
"""
import os
import sys
import json
import time
import signal
import subprocess
import threading
import logging
import logging.handlers
import pathlib
import requests
from datetime import datetime
from typing import Optional, Dict, Any, Tuple
from watchdog.observers import Observer
from watchdog.events import FileSystemEventHandler

# Eigene Module
import parse_scene_transkript
import img_gen
import ollama

class TranscriptEventHandler(FileSystemEventHandler):
    """Handler für neue Transkript-Dateien."""
    
    def __init__(self, runner):
        self.runner = runner
        self.logger = runner.logger
    
    def on_created(self, event):
        if event.is_directory:
            return
        
        if event.src_path.endswith("_transkript.txt"):
            self.logger.info(f"🎭 Neues Transkript erkannt: {event.src_path}")
            # Verzögerung um sicherzustellen, dass Datei vollständig geschrieben wurde
            time.sleep(2)
            self.runner.process_new_transcript(event.src_path)

class SceneVisualizerRunner:
    """Hauptklasse für den Scene Visualizer Runner."""
    
    def __init__(self, config_file: str = "scene_config.json"):
        """Initialisiert den Runner mit Konfiguration."""
        self.config_file = config_file
        self.config = self._load_config()
        self.running = False
        self.observer = None
        
        # Tracking-Thread
        self.tracking_thread = None
        
        # Verzeichnisse
        self.transkript_dir = pathlib.Path(self.config['transkript_directory'])
        self.scene_dir = pathlib.Path(self.config['scene_directory'])
        
        # JSON-Tracking
        self.tracking_file = self.transkript_dir / "transkript_tracking.json"
        
        # Logging konfigurieren
        self._setup_logging()
        
        # Signal Handler für graceful shutdown
        signal.signal(signal.SIGINT, self._signal_handler)
        signal.signal(signal.SIGTERM, self._signal_handler)
        
        self.logger.info("🎬 Scene Visualizer Runner initialisiert")
    
    def _load_config(self) -> Dict[str, Any]:
        """Lädt die Konfiguration aus der JSON-Datei."""
        # Standard-Konfiguration
        default_config = {
            "transkript_directory": "web/transkripte",
            "scene_directory": "web/scene",
            "outputs_directory": "outputs",
            "log_level": "DEBUG",
            "logging": {
                "main_log_file": "scene_runner.log",
                "error_log_file": "scene_errors.log"
            },
            "services": {
                "ollama": {
                    "model": "deepseek-r1:8b",
                    "temperature": 0.7,
                    "max_tokens": 1000
                },
                "image_generation": {
                    "config_file": "img_gen_service.json",
                    "timeout_seconds": 300
                }
            }
        }
        
        try:
            config_path = pathlib.Path(self.config_file)
            if config_path.exists():
                with open(config_path, 'r', encoding='utf-8') as f:
                    config = json.load(f)
                # Merge mit Default-Config
                default_config.update(config)
            else:
                # Speichere Default-Config
                with open(config_path, 'w', encoding='utf-8') as f:
                    json.dump(default_config, f, indent=4, ensure_ascii=False)
                self.logger.info(f"✅ Standard-Konfiguration erstellt: {config_path}")
            
            return default_config
            
        except Exception as e:
            print(f"Fehler beim Laden der Konfiguration: {e}")
            return default_config
    
    def _setup_logging(self):
        """Konfiguriert das Logging-System."""
        log_level = getattr(logging, self.config.get('log_level', 'INFO'))
        logging_config = self.config.get('logging', {})
        
        # Formatter
        formatter = logging.Formatter(
            '%(asctime)s - %(levelname)s - %(message)s'
        )
        
        # Console Handler
        console_handler = logging.StreamHandler(sys.stdout)
        console_handler.setFormatter(formatter)
        console_handler.setLevel(log_level)
        
        # File Handler
        main_log_file = logging_config.get('main_log_file', 'scene_runner.log')
        file_handler = logging.handlers.RotatingFileHandler(
            main_log_file,
            maxBytes=10*1024*1024,  # 10MB
            backupCount=5,
            encoding='utf-8'
        )
        file_handler.setFormatter(formatter)
        file_handler.setLevel(log_level)
        
        # Error Handler
        error_log_file = logging_config.get('error_log_file', 'scene_errors.log')
        error_handler = logging.handlers.RotatingFileHandler(
            error_log_file,
            maxBytes=10*1024*1024,
            backupCount=5,
            encoding='utf-8'
        )
        error_handler.setFormatter(formatter)
        error_handler.setLevel(logging.ERROR)
        
        # Logger konfigurieren
        self.logger = logging.getLogger('SceneVisualizer')
        self.logger.setLevel(log_level)
        self.logger.addHandler(console_handler)
        self.logger.addHandler(file_handler)
        self.logger.addHandler(error_handler)
    
    def _signal_handler(self, signum, frame):
        """Handler für System-Signale (graceful shutdown)."""
        self.logger.info(f"Signal {signum} empfangen, starte graceful shutdown...")
        self.running = False
        if self.observer:
            self.observer.stop()
    
    def _ensure_directories(self):
        """Stellt sicher, dass alle benötigten Verzeichnisse existieren."""
        directories = [
            self.transkript_dir,
            self.scene_dir,
            pathlib.Path(self.config['outputs_directory'])
        ]
        
        for directory in directories:
            directory.mkdir(parents=True, exist_ok=True)
            self.logger.info(f"✅ Verzeichnis bereitgestellt: {directory}")
        
        # Initialisiere JSON-Tracking
        self._initialize_tracking()
    
    def _initialize_tracking(self):
        """Initialisiert das JSON-Tracking-System."""
        try:
            if not self.tracking_file.exists():
                # Erstelle neue Tracking-Datei
                tracking_data = {
                    "last_updated": datetime.now().isoformat(),
                    "transcripts": {},
                    "status": "initialized"
                }
                
                with open(self.tracking_file, 'w', encoding='utf-8') as f:
                    json.dump(tracking_data, f, indent=2, ensure_ascii=False)
                
                self.logger.info(f"📄 Tracking-System initialisiert: {self.tracking_file}")
            
            # WICHTIG: Sync mit vorhandenen Dateien beim Start
            self.logger.info("🔄 Synchronisiere mit vorhandenen Dateien...")
            self._sync_tracking_with_filesystem()
            
            # Prüfe ob alle Dateien erfasst wurden
            with open(self.tracking_file, 'r', encoding='utf-8') as f:
                tracking_data = json.load(f)
            
            actual_files = list(self.transkript_dir.glob("*_transkript.txt"))
            tracked_count = len(tracking_data.get('transcripts', {}))
            actual_count = len(actual_files)
            
            if tracked_count == actual_count:
                self.logger.info(f"✅ Alle {actual_count} Transkripte im Tracking erfasst")
            else:
                self.logger.warning(f"⚠️ Tracking unvollständig: {tracked_count}/{actual_count} Dateien")
            
        except Exception as e:
            self.logger.error(f"Fehler beim Initialisieren des Tracking-Systems: {e}")
    
    def _sync_tracking_with_filesystem(self):
        """Synchronisiert Tracking-JSON mit dem Dateisystem (alle 3 Sekunden)."""
        try:
            sync_start_time = time.time()
            self.logger.debug("🔄 Sync gestartet...")
            
            # Lade aktuelle Tracking-Daten
            if not self.tracking_file.exists():
                self.logger.warning(f"⚠️ Tracking-Datei nicht gefunden: {self.tracking_file}")
                self.logger.info("🔧 Erstelle neue Tracking-Datei...")
                self._initialize_tracking()
                return
                
            with open(self.tracking_file, 'r', encoding='utf-8') as f:
                tracking_data = json.load(f)
            
            tracked_count = len(tracking_data.get('transcripts', {}))
            self.logger.debug(f"📊 Tracking-Daten geladen: {tracked_count} Einträge")
            
            # Scanne Dateisystem
            current_files = {}
            file_count = 0
            for file_path in self.transkript_dir.glob("*_transkript.txt"):
                file_count += 1
                self.logger.debug(f"📄 Verarbeite Datei {file_count}: {file_path.name}")
                
                file_hash = self._get_file_hash(file_path)
                file_info = {
                    "filename": file_path.name,
                    "size": file_path.stat().st_size,
                    "modified": datetime.fromtimestamp(file_path.stat().st_mtime).isoformat(),
                    "hash": file_hash,
                    "status": "detected",
                    "last_seen": datetime.now().isoformat()
                }
                current_files[file_path.name] = file_info
            
            actual_count = len(current_files)
            self.logger.debug(f"📊 Dateisystem-Scan: {actual_count} Dateien gefunden")
            
            # DEBUG: Erkenne Diskrepanzen sofort
            if tracked_count != actual_count:
                self.logger.warning(f"⚠️ DISKREPANZ ERKANNT: {tracked_count} tracked vs {actual_count} actual")
                tracked_names = set(tracking_data.get('transcripts', {}).keys())
                actual_names = set(current_files.keys())
                missing_in_tracking = actual_names - tracked_names
                missing_in_filesystem = tracked_names - actual_names
                
                if missing_in_tracking:
                    self.logger.warning(f"❌ Fehlen im Tracking: {missing_in_tracking}")
                if missing_in_filesystem:
                    self.logger.warning(f"❌ Fehlen im Dateisystem: {missing_in_filesystem}")
            
            # Vergleiche und aktualisiere Tracking
            updated = False
            new_files_found = []
            changed_files = []
            
            for filename, file_info in current_files.items():
                if filename not in tracking_data["transcripts"]:
                    # Neue Datei
                    has_output = self._check_for_existing_output(filename)
                    file_info["status"] = "completed" if has_output else "new"
                    file_info["detected_at"] = datetime.now().isoformat()
                    if has_output:
                        file_info["details"] = "Output bereits vorhanden"
                        self.logger.info(f"🔄 Neue Datei mit vorhandenem Output: {filename}")
                    else:
                        file_info["details"] = "Bereit zur Verarbeitung"
                        self.logger.info(f"🆕 NEUE DATEI ZUR VERARBEITUNG: {filename}")
                        # Verarbeite neue Datei sofort
                        if self.running:
                            self.logger.info(f"🚀 Starte sofortige Verarbeitung: {filename}")
                            threading.Thread(
                                target=self._process_file_safely,
                                args=(str(self.transkript_dir / filename),),
                                daemon=True
                            ).start()
                    
                    tracking_data["transcripts"][filename] = file_info
                    new_files_found.append(filename)
                    updated = True
                    
                elif tracking_data["transcripts"][filename]["hash"] != file_info["hash"]:
                    # Datei geändert
                    old_status = tracking_data["transcripts"][filename].get("status", "unknown")
                    file_info["status"] = "modified"
                    file_info["previous_status"] = old_status
                    file_info["modified_at"] = datetime.now().isoformat()
                    tracking_data["transcripts"][filename] = file_info
                    changed_files.append(filename)
                    updated = True
                    self.logger.info(f"📝 Datei geändert: {filename} (war: {old_status})")
                    
                    # Verarbeite geänderte Datei
                    if self.running and old_status != "completed":
                        self.logger.info(f"🔄 Verarbeite geänderte Datei: {filename}")
                        threading.Thread(
                            target=self._process_file_safely,
                            args=(str(self.transkript_dir / filename),),
                            daemon=True
                        ).start()
                else:
                    # Datei unverändert - update last_seen
                    tracking_data["transcripts"][filename]["last_seen"] = datetime.now().isoformat()
            
            # Entferne veraltete Einträge
            removed_files = []
            current_names = set(current_files.keys())
            for filename in list(tracking_data["transcripts"].keys()):
                if filename not in current_names:
                    del tracking_data["transcripts"][filename]
                    removed_files.append(filename)
                    updated = True
                    self.logger.warning(f"🗑️ Datei aus Tracking entfernt: {filename} (nicht mehr im Dateisystem)")
            
            # Speichere wenn Änderungen
            if updated:
                tracking_data["last_updated"] = datetime.now().isoformat()
                tracking_data["status"] = "active"
                tracking_data["sync_count"] = tracking_data.get("sync_count", 0) + 1
                
                with open(self.tracking_file, 'w', encoding='utf-8') as f:
                    json.dump(tracking_data, f, indent=2, ensure_ascii=False)
                
                sync_time = time.time() - sync_start_time
                self.logger.info(f"💾 Tracking aktualisiert in {sync_time:.2f}s:")
                if new_files_found:
                    self.logger.info(f"   ➕ Neue Dateien: {len(new_files_found)}")
                if changed_files:
                    self.logger.info(f"   🔄 Geänderte Dateien: {len(changed_files)}")
                if removed_files:
                    self.logger.info(f"   🗑️ Entfernte Dateien: {len(removed_files)}")
            else:
                # Auch bei "keine Änderungen" gelegentlich Status loggen
                sync_count = tracking_data.get("sync_count", 0)
                if sync_count % 20 == 0:  # Alle 60 Sekunden (20 * 3s)
                    self.logger.info(f"✅ Tracking stabil: {actual_count} Dateien überwacht")
                
                sync_time = time.time() - sync_start_time
                self.logger.debug(f"✅ Keine Änderungen in {sync_time:.2f}s")
                
        except Exception as e:
            import traceback
            self.logger.error(f"❌ Kritischer Fehler beim Synchronisieren des Tracking-Systems: {e}")
            self.logger.error(f"📋 Traceback: {traceback.format_exc()}")
            
            # Versuche Tracking zu reparieren
            try:
                self.logger.info("🔧 Versuche Tracking-Reparatur...")
                self._repair_tracking()
            except Exception as repair_error:
                self.logger.error(f"❌ Tracking-Reparatur fehlgeschlagen: {repair_error}")
    
    def _process_file_safely(self, transcript_path: str):
        """Verarbeitet eine Datei sicher in separatem Thread."""
        try:
            self.logger.info(f"🔄 [THREAD] Starte Verarbeitung: {transcript_path}")
            self.process_new_transcript(transcript_path)
        except Exception as e:
            self.logger.error(f"❌ [THREAD] Fehler bei Verarbeitung von {transcript_path}: {e}")
            import traceback
            self.logger.error(f"📋 [THREAD] Traceback: {traceback.format_exc()}")
    
    def _repair_tracking(self):
        """Repariert das Tracking-System bei Fehlern."""
        self.logger.info("🔧 Repariere Tracking-System...")
        
        # Backup der aktuellen Tracking-Datei
        if self.tracking_file.exists():
            backup_file = self.tracking_file.with_suffix('.json.error_backup')
            import shutil
            shutil.copy2(self.tracking_file, backup_file)
            self.logger.info(f"💾 Backup erstellt: {backup_file}")
        
        # Neu initialisieren
        self._initialize_tracking()
        self.logger.info("✅ Tracking-System repariert")
    
    def _get_file_hash(self, file_path: pathlib.Path) -> str:
        """Berechnet Hash für Datei-Inhalt."""
        import hashlib
        try:
            with open(file_path, 'rb') as f:
                return hashlib.md5(f.read()).hexdigest()
        except Exception as e:
            self.logger.error(f"Fehler beim Hash-Berechnen für {file_path}: {e}")
            return ""
    
    def _check_for_existing_output(self, transcript_name: str) -> bool:
        """Prüft ob bereits Output-Dateien für dieses Transkript existieren."""
        base_name = transcript_name.replace("_transkript.txt", "")
        image_file = self.scene_dir / f"{base_name}_image.png"
        metadata_file = self.scene_dir / f"{base_name}_metadata.json"
        return image_file.exists() and metadata_file.exists()
    
    def _check_initial_transcripts(self):
        """Prüft beim Start, ob für das neueste Transkript bereits ein Bild existiert."""
        latest_transcript = parse_scene_transkript.get_latest_transkript(str(self.transkript_dir))
        
        if not latest_transcript:
            self.logger.info("📄 Keine Transkripte gefunden")
            return
        
        self.logger.info(f"📄 Neuestes Transkript: {latest_transcript.name}")
        
        # Prüfe ob Bild bereits existiert
        scene_name = latest_transcript.stem.replace("_transkript", "")
        image_path = self.scene_dir / f"{scene_name}_image.png"
        error_path = self.scene_dir / f"{scene_name}_error.json"
        
        if image_path.exists():
            self.logger.info(f"✅ Bild existiert bereits: {image_path.name}")
        elif error_path.exists():
            self.logger.info(f"🔄 Wiederhole fehlgeschlagene Generierung für: {scene_name}")
            # Warte kurz um sicherzustellen, dass Image Service Zeit zum Starten hat
            self.logger.info("⏳ Warte 5 Sekunden für Image Service...")
            time.sleep(5)
            self.process_new_transcript(str(latest_transcript))
        else:
            self.logger.info(f"🎨 Erstelle fehlendes Bild für: {scene_name}")
            # Warte kurz um sicherzustellen, dass Image Service Zeit zum Starten hat
            self.logger.info("⏳ Warte 5 Sekunden für Image Service...")
            time.sleep(5)
            self.process_new_transcript(str(latest_transcript))
    
    def _generate_scene_prompt(self, transkript_text: str) -> Tuple[Dict[str, Any], str]:
        """Generiert einen Scene-Prompt mit Ollama."""
        try:
            system_prompt = """Du bist ein kreativer Assistent für die Visualisierung von Dungeons & Dragons Szenen.
            
Deine Aufgabe ist es, basierend auf einem Transkript-Ausschnitt:
1. Eine detaillierte deutsche Szenenbeschreibung zu erstellen
2. Einen englischen DNDSTYLE Prompt für die Bildgenerierung zu erstellen

Antworte IMMER im folgenden JSON-Format:
{
    "szenenbeschreibung": "Detaillierte Beschreibung der Szene auf Deutsch, die die Atmosphäre, Charaktere und wichtige visuelle Elemente erfasst",
    "dndstyle_prompt": "dndstyle illustration of [englische Bildbeschreibung mit Details zu Charakteren, Umgebung, Beleuchtung und Atmosphäre]",
    "wichtige_elemente": ["Element 1", "Element 2", "Element 3"],
    "stimmung": "Die vorherrschende Stimmung der Szene"
}

Wichtig: Der dndstyle_prompt MUSS mit "dndstyle illustration of" beginnen und auf Englisch sein!"""

            user_prompt = f"""Analysiere folgendes D&D Session-Transkript und erstelle eine Visualisierung:

{transkript_text}

Erstelle basierend auf diesem Transkript eine detaillierte Szenenbeschreibung und einen Bildgenerierungs-Prompt."""

            self.logger.info("🤖 Sende Anfrage an Ollama...")
            
            response = ollama.generate(
                model=self.config['services']['ollama']['model'],
                prompt=user_prompt,
                system=system_prompt,
                format='json'
            )
            
            # Parse die Antwort
            full_response = response['response']
            self.logger.debug(f"Ollama Antwort: {full_response}")
            
            try:
                result = json.loads(full_response)
                return result, full_response
            except json.JSONDecodeError:
                self.logger.error("❌ Fehler beim Parsen der Ollama-Antwort")
                # Fallback
                return {
                    "szenenbeschreibung": "Eine mysteriöse D&D Szene",
                    "dndstyle_prompt": "dndstyle illustration of a mysterious dungeon scene",
                    "wichtige_elemente": ["Unbekannt"],
                    "stimmung": "Mysteriös"
                }, full_response
                
        except Exception as e:
            self.logger.error(f"❌ Fehler bei Ollama-Anfrage: {e}")
            # Fallback
            return {
                "szenenbeschreibung": "Eine epische D&D Szene",
                "dndstyle_prompt": "dndstyle illustration of an epic fantasy adventure scene",
                "wichtige_elemente": ["Abenteuer"],
                "stimmung": "Episch"
            }, str(e)
    
    def process_new_transcript(self, transcript_path: str):
        """Verarbeitet ein neues Transkript und generiert ein Bild."""
        try:
            self.logger.info(f"🔄 Verarbeite Transkript: {transcript_path}")
            
            # Parse Transkript
            parser = parse_scene_transkript.SceneTranskriptParser(transcript_path)
            scene_name = parser.get_scene_name()
            segmente_text = parser.get_segmente_als_text()
            
            self.logger.info(f"📝 Scene: {scene_name}")
            self.logger.info(f"📝 Segmente: {len(parser.get_zeitgestempelte_segmente())} gefunden")
            
            # Generiere Prompt mit Ollama
            llm_result, full_response = self._generate_scene_prompt(segmente_text)
            
            # Extrahiere DNDSTYLE Prompt
            dndstyle_prompt = llm_result.get('dndstyle_prompt', 'dndstyle illustration of a fantasy scene')
            szenenbeschreibung = llm_result.get('szenenbeschreibung', 'Keine Beschreibung verfügbar')
            
            self.logger.info(f"🎨 DNDSTYLE Prompt: {dndstyle_prompt}")
            
            # Generiere Bild
            image_filename = f"{scene_name}_image.png"
            image_path = self.scene_dir / image_filename
            
            self.logger.info("🖼️ Starte Bildgenerierung...")
            start_time = time.time()
            
            # Versuche Bildgenerierung mit Retry-Mechanismus
            max_retries = 3
            retry_delay = 10  # Sekunden
            
            for attempt in range(max_retries):
                try:
                    self.logger.info(f"🖼️ Bildgenerierung Versuch {attempt + 1}/{max_retries}...")
                    
                    # Sende nur den Dateinamen, da img_gen_service bereits output_dir verwendet
                    result = img_gen.generate_img(dndstyle_prompt, image_filename)
                    generation_time = time.time() - start_time
                    
                    self.logger.info(f"✅ Bild generiert in {generation_time:.1f}s: {image_path}")
                    
                    # Speichere JSON mit allen Informationen
                    json_path = self.scene_dir / f"{scene_name}_metadata.json"
                    metadata = {
                        "scene_name": scene_name,
                        "transcript_file": os.path.basename(transcript_path),
                        "generation_timestamp": datetime.now().isoformat(),
                        "generation_time_seconds": round(generation_time, 2),
                        "transcript_metadata": parser.get_metadata(),
                        "segmente_count": len(parser.get_zeitgestempelte_segmente()),
                        "segmente_text": segmente_text,
                        "llm_result": llm_result,
                        "llm_full_response": full_response,
                        "dndstyle_prompt": dndstyle_prompt,
                        "szenenbeschreibung": szenenbeschreibung,
                        "image_file": image_filename,
                        "image_generation_result": result,
                        "generation_attempts": attempt + 1
                    }
                    
                    with open(json_path, 'w', encoding='utf-8') as f:
                        json.dump(metadata, f, indent=4, ensure_ascii=False)
                    
                    self.logger.info(f"💾 Metadaten gespeichert: {json_path}")
                    
                    # Lösche eventuell vorhandene Error-Datei
                    error_json_path = self.scene_dir / f"{scene_name}_error.json"
                    if error_json_path.exists():
                        error_json_path.unlink()
                        self.logger.info(f"🗑️ Error-Datei gelöscht: {error_json_path}")
                    
                    return  # Erfolgreich, verlasse die Funktion
                    
                except ConnectionError as e:
                    if "Connection refused" in str(e):
                        self.logger.warning(f"⚠️ Image Service noch nicht bereit (Versuch {attempt + 1}/{max_retries})")
                        if attempt < max_retries - 1:
                            self.logger.info(f"⏳ Warte {retry_delay}s vor nächstem Versuch...")
                            time.sleep(retry_delay)
                            continue
                    else:
                        self.logger.error(f"❌ Verbindungsfehler: {e}")
                        break
                except Exception as e:
                    self.logger.error(f"❌ Fehler bei Bildgenerierung: {e}")
                    break
            
            # Alle Versuche fehlgeschlagen - speichere Error-Metadata
            self.logger.error(f"❌ Bildgenerierung nach {max_retries} Versuchen fehlgeschlagen")
            error_json_path = self.scene_dir / f"{scene_name}_error.json"
            error_metadata = {
                "scene_name": scene_name,
                "error": str(e) if 'e' in locals() else "Unbekannter Fehler",
                "timestamp": datetime.now().isoformat(),
                "dndstyle_prompt": dndstyle_prompt,
                "szenenbeschreibung": szenenbeschreibung,
                "llm_result": llm_result,
                "failed_attempts": max_retries
            }
            with open(error_json_path, 'w', encoding='utf-8') as f:
                json.dump(error_metadata, f, indent=4, ensure_ascii=False)
                
        except Exception as e:
            self.logger.error(f"❌ Fehler bei Transkript-Verarbeitung: {e}")
            import traceback
            self.logger.error(traceback.format_exc())
    
    def _tracking_loop(self):
        """Tracking-Loop läuft alle 3 Sekunden."""
        self.logger.info("🔄 Tracking-Loop gestartet (alle 3 Sekunden)")
        consecutive_errors = 0
        last_successful_sync = time.time()
        
        while self.running:
            try:
                loop_start = time.time()
                self._sync_tracking_with_filesystem()
                
                # Erfolgreicher Sync
                consecutive_errors = 0
                last_successful_sync = time.time()
                
                # Adaptive Pause basierend auf Systemlast
                loop_time = time.time() - loop_start
                if loop_time > 1.0:  # Langsamer Sync
                    pause_time = 5  # Längere Pause
                    self.logger.debug(f"⏳ Langsamer Sync ({loop_time:.2f}s), pause {pause_time}s")
                else:
                    pause_time = 3  # Standard-Pause
                
                time.sleep(pause_time)
                
            except Exception as e:
                consecutive_errors += 1
                error_pause = min(30, 5 + (consecutive_errors * 2))  # Max 30s
                
                self.logger.error(f"❌ Tracking-Loop Fehler #{consecutive_errors}: {e}")
                
                # Nach 5 Fehlern in Folge: Detailliertes Debugging
                if consecutive_errors >= 5:
                    self.logger.error("🚨 KRITISCH: 5+ aufeinanderfolgende Tracking-Fehler!")
                    self.logger.error(f"⏰ Letzter erfolgreicher Sync: {time.time() - last_successful_sync:.1f}s her")
                    
                    # Versuche System-Diagnose
                    try:
                        self._diagnose_tracking_problems()
                    except:
                        pass
                
                # Exponentiell längere Pausen bei wiederholten Fehlern
                self.logger.info(f"⏳ Pause {error_pause}s vor nächstem Versuch...")
                time.sleep(error_pause)
        
        self.logger.info("🛑 Tracking-Loop beendet")
    
    def _diagnose_tracking_problems(self):
        """Diagnostiziert Tracking-Probleme für besseres Debugging."""
        self.logger.error("🔍 === TRACKING PROBLEM DIAGNOSE ===")
        
        # 1. Dateisystem-Zugriff prüfen
        try:
            if self.transkript_dir.exists() and self.transkript_dir.is_dir():
                file_count = len(list(self.transkript_dir.glob("*_transkript.txt")))
                self.logger.error(f"📁 Transkript-Verzeichnis: OK ({file_count} Dateien)")
            else:
                self.logger.error(f"📁 Transkript-Verzeichnis: PROBLEM - {self.transkript_dir}")
        except Exception as e:
            self.logger.error(f"📁 Transkript-Verzeichnis: FEHLER - {e}")
        
        # 2. Tracking-Datei prüfen  
        try:
            if self.tracking_file.exists():
                stat = self.tracking_file.stat()
                self.logger.error(f"📄 Tracking-Datei: OK ({stat.st_size} bytes)")
            else:
                self.logger.error(f"📄 Tracking-Datei: FEHLT - {self.tracking_file}")
        except Exception as e:
            self.logger.error(f"📄 Tracking-Datei: FEHLER - {e}")
        
        # 3. Speicher und Systemressourcen
        try:
            import psutil
            memory = psutil.virtual_memory()
            disk = psutil.disk_usage('.')
            self.logger.error(f"💾 Speicher: {memory.percent}% belegt")
            self.logger.error(f"💿 Festplatte: {disk.percent}% belegt")
        except:
            pass
        
        # 4. Thread-Status
        thread_count = threading.active_count()
        self.logger.error(f"🧵 Aktive Threads: {thread_count}")
        
        self.logger.error("🔍 === DIAGNOSE ENDE ===")
    
    def get_tracking_status(self) -> Dict[str, Any]:
        """Gibt detaillierte Tracking-Status-Informationen zurück."""
        try:
            if not self.tracking_file.exists():
                return {"status": "no_tracking_file", "details": "Tracking-Datei nicht vorhanden"}
            
            with open(self.tracking_file, 'r', encoding='utf-8') as f:
                tracking_data = json.load(f)
            
            # Dateisystem scannen
            actual_files = list(self.transkript_dir.glob("*_transkript.txt"))
            tracked_files = tracking_data.get('transcripts', {})
            
            # Status berechnen
            actual_names = {f.name for f in actual_files}
            tracked_names = set(tracked_files.keys())
            
            new_status_counts = {}
            for file_info in tracked_files.values():
                status = file_info.get('status', 'unknown')
                new_status_counts[status] = new_status_counts.get(status, 0) + 1
            
            return {
                "status": "active" if tracking_data.get('status') == 'active' else "inactive",
                "last_updated": tracking_data.get('last_updated'),
                "sync_count": tracking_data.get('sync_count', 0),
                "files": {
                    "tracked": len(tracked_files),
                    "actual": len(actual_files),
                    "missing_in_tracking": list(actual_names - tracked_names),
                    "missing_in_filesystem": list(tracked_names - actual_names)
                },
                "status_breakdown": new_status_counts,
                "synchronized": len(actual_names - tracked_names) == 0 and len(tracked_names - actual_names) == 0
            }
            
        except Exception as e:
            return {"status": "error", "error": str(e)}
    
    def run(self):
        """Startet den Scene Visualizer."""
        self.logger.info("🚀 Starte Scene Visualizer Runner...")
        
        # Startup-Checks
        startup_success = self._startup_checks()
        if not startup_success:
            self.logger.error("❌ Startup-Checks fehlgeschlagen, beende...")
            return False
        
        # Stelle sicher, dass Verzeichnisse existieren
        self._ensure_directories()
        
        # Prüfe initiale Transkripte
        self._check_initial_transcripts()
        
        # Starte Tracking-Thread NACH dem self.running = True
        self.running = True  # MUSS VOR dem Thread-Start sein!
        
        self.tracking_thread = threading.Thread(target=self._tracking_loop, daemon=True)
        self.tracking_thread.start()
        self.logger.info("📊 JSON-Tracking-Thread gestartet")
        
        # Warte kurz bis Tracking-Thread läuft
        time.sleep(1)
        if not self.tracking_thread.is_alive():
            self.logger.error("❌ Tracking-Thread konnte nicht gestartet werden!")
            return False
        
        # Starte Datei-Überwachung
        self.logger.info(f"👁️ Überwache Verzeichnis: {self.transkript_dir}")
        
        try:
            event_handler = TranscriptEventHandler(self)
            self.observer = Observer()
            self.observer.schedule(event_handler, str(self.transkript_dir), recursive=False)
            self.observer.start()
            
            # Prüfe ob Observer wirklich läuft
            time.sleep(0.5)
            if not self.observer.is_alive():
                self.logger.error("❌ Watchdog Observer konnte nicht gestartet werden!")
                return False
            
        except Exception as e:
            self.logger.error(f"❌ Fehler beim Starten des Watchdog Observers: {e}")
            return False
        
        # Starte Healthcheck-Thread
        self.healthcheck_thread = threading.Thread(target=self._healthcheck_loop, daemon=True)
        self.healthcheck_thread.start()
        self.logger.info("💚 Healthcheck-Thread gestartet")
        
        self._start_time = time.time()  # Für Laufzeit-Tracking
        
        # Startup-Status anzeigen
        status = self.get_tracking_status()
        self.logger.info("✅ Scene Visualizer läuft!")
        self.logger.info(f"📊 Initial Status: {status['files']['tracked']} tracked, {status['files']['actual']} actual")
        if not status['synchronized']:
            self.logger.warning("⚠️ System nicht synchronisiert beim Start!")
        
        self.logger.info(f"📄 JSON-Tracking aktiv: {self.tracking_file}")
        self.logger.info("🔍 Warte auf neue Transkripte...")
        
        try:
            # Hauptschleife mit periodischen Status-Updates
            last_status_log = time.time()
            
            while self.running:
                time.sleep(1)
                
                # Alle 5 Minuten Status loggen
                if time.time() - last_status_log > 300:
                    self._log_system_status()
                    last_status_log = time.time()
                    
        except KeyboardInterrupt:
            self.logger.info("🛑 Beende Scene Visualizer...")
        finally:
            self._shutdown_gracefully()
            
        return True
    
    def _startup_checks(self) -> bool:
        """Führt Startup-Checks durch."""
        self.logger.info("🔍 Führe Startup-Checks durch...")
        
        # 1. Python-Module prüfen
        try:
            import watchdog, ollama
            self.logger.info("✅ Erforderliche Module verfügbar")
        except ImportError as e:
            self.logger.error(f"❌ Fehlende Module: {e}")
            return False
        
        # 2. Verzeichnisse prüfen/erstellen
        try:
            self.transkript_dir.mkdir(parents=True, exist_ok=True)
            self.scene_dir.mkdir(parents=True, exist_ok=True)
            self.logger.info("✅ Verzeichnisse verfügbar")
        except Exception as e:
            self.logger.error(f"❌ Verzeichnis-Fehler: {e}")
            return False
        
        # 3. Schreibberechtigung prüfen
        try:
            test_file = self.transkript_dir / ".write_test"
            test_file.write_text("test")
            test_file.unlink()
            self.logger.info("✅ Schreibberechtigung OK")
        except Exception as e:
            self.logger.error(f"❌ Keine Schreibberechtigung: {e}")
            return False
        
        self.logger.info("✅ Alle Startup-Checks erfolgreich")
        return True
    
    def _healthcheck_loop(self):
        """Healthcheck-Loop läuft alle 30 Sekunden."""
        self.logger.info("💚 Healthcheck-Loop gestartet (alle 30 Sekunden)")
        
        while self.running:
            try:
                # Prüfe Threads
                tracking_alive = self.tracking_thread and self.tracking_thread.is_alive()
                observer_alive = self.observer and self.observer.is_alive()
                
                if not tracking_alive:
                    self.logger.error("🚨 HEALTHCHECK: Tracking-Thread ist tot!")
                if not observer_alive:
                    self.logger.error("🚨 HEALTHCHECK: Observer-Thread ist tot!")
                
                # Prüfe Tracking-Status
                status = self.get_tracking_status()
                if not status['synchronized']:
                    missing_in_tracking = status['files']['missing_in_tracking']
                    if missing_in_tracking:
                        self.logger.warning(f"💚 HEALTHCHECK: {len(missing_in_tracking)} Dateien nicht im Tracking: {missing_in_tracking}")
                
                # Alle 2 Minuten detaillierteren Status
                if int(time.time()) % 120 == 0:
                    self.logger.info(f"💚 HEALTHCHECK: System läuft stabil")
                    self.logger.info(f"   📊 Sync Count: {status.get('sync_count', 0)}")
                    self.logger.info(f"   📁 Dateien: {status['files']['tracked']} tracked / {status['files']['actual']} actual")
                
                time.sleep(30)
                
            except Exception as e:
                self.logger.error(f"❌ Healthcheck Fehler: {e}")
                time.sleep(60)  # Längere Pause bei Fehlern
        
        self.logger.info("💚 Healthcheck-Loop beendet")
    
    def _log_system_status(self):
        """Loggt detaillierten System-Status."""
        try:
            status = self.get_tracking_status()
            self.logger.info("📊 === SYSTEM STATUS ===")
            self.logger.info(f"   🕐 Laufzeit: {time.time() - self._start_time:.0f}s" if hasattr(self, '_start_time') else "   🕐 Laufzeit: unbekannt")
            self.logger.info(f"   📁 Dateien: {status['files']['tracked']} tracked / {status['files']['actual']} actual")
            self.logger.info(f"   🔄 Syncs: {status.get('sync_count', 0)}")
            self.logger.info(f"   ✅ Synchronisiert: {status['synchronized']}")
            
            if status['status_breakdown']:
                self.logger.info(f"   📈 Status-Verteilung: {status['status_breakdown']}")
            
            if not status['synchronized']:
                if status['files']['missing_in_tracking']:
                    self.logger.warning(f"   ⚠️ Fehlen im Tracking: {status['files']['missing_in_tracking']}")
                    
        except Exception as e:
            self.logger.error(f"❌ Fehler beim Status-Logging: {e}")
    
    def _shutdown_gracefully(self):
        """Graceful Shutdown aller Komponenten."""
        self.logger.info("🛑 Starte graceful shutdown...")
        
        self.running = False
        
        # Stoppe Observer
        if self.observer:
            try:
                self.observer.stop()
                self.observer.join(timeout=5)
                self.logger.info("✅ Observer gestoppt")
            except Exception as e:
                self.logger.error(f"❌ Fehler beim Stoppen des Observers: {e}")
        
        # Warte auf Tracking-Thread
        if self.tracking_thread and self.tracking_thread.is_alive():
            try:
                self.tracking_thread.join(timeout=10)
                self.logger.info("✅ Tracking-Thread gestoppt")
            except Exception as e:
                self.logger.error(f"❌ Fehler beim Stoppen des Tracking-Threads: {e}")
        
        # Warte auf Healthcheck-Thread
        if hasattr(self, 'healthcheck_thread') and self.healthcheck_thread and self.healthcheck_thread.is_alive():
            try:
                self.healthcheck_thread.join(timeout=5)
                self.logger.info("✅ Healthcheck-Thread gestoppt")
            except Exception as e:
                self.logger.error(f"❌ Fehler beim Stoppen des Healthcheck-Threads: {e}")
        
        self.logger.info("👋 Scene Visualizer vollständig beendet")

def main():
    """Hauptfunktion."""
    runner = SceneVisualizerRunner()
    runner.run()

if __name__ == "__main__":
    main() 