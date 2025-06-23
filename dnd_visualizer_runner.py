#!/usr/bin/env python3
"""
D&D Visualizer Runner - Koordiniert alle Komponenten für automatische Bildgenerierung.
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
import socket
from datetime import datetime, timedelta
from typing import Optional, Dict, Any, Tuple

# Eigene Module
import parse_transkript
import img_gen

class DnDVisualizerRunner:
    """Hauptklasse für den D&D Visualizer Runner."""
    
    def __init__(self, config_file: str = "run_config.json"):
        """Initialisiert den Runner mit Konfiguration."""
        self.config_file = config_file
        self.config = self._load_config()
        self.running = False
        self.processes = {}
        self.lock_file = pathlib.Path("dnd_runner.lock")
        self.last_generation_time = None
        
        # Logging konfigurieren
        self._setup_logging()
        
        # Signal Handler für graceful shutdown
        signal.signal(signal.SIGINT, self._signal_handler)
        signal.signal(signal.SIGTERM, self._signal_handler)
        
        self.logger.info("D&D Visualizer Runner initialisiert")
    
    def _load_config(self) -> Dict[str, Any]:
        """Lädt die Konfiguration aus der JSON-Datei."""
        try:
            config_path = pathlib.Path(self.config_file)
            if not config_path.exists():
                raise FileNotFoundError(f"Konfigurationsdatei {self.config_file} nicht gefunden")
            
            with open(config_path, 'r', encoding='utf-8') as f:
                config = json.load(f)
            
            # Konfiguration validieren
            self._validate_config(config)
            return config
            
        except Exception as e:
            print(f"Fehler beim Laden der Konfiguration: {e}")
            sys.exit(1)
    
    def _validate_config(self, config: Dict[str, Any]):
        """Validiert die Konfiguration."""
        required_keys = ['interval_minutes', 'outputs_directory', 'services', 'transcript']
        for key in required_keys:
            if key not in config:
                raise ValueError(f"Erforderlicher Konfigurationsschlüssel fehlt: {key}")
        
        # Outputs-Verzeichnis erstellen
        outputs_dir = pathlib.Path(config['outputs_directory'])
        outputs_dir.mkdir(exist_ok=True)
        
        if not outputs_dir.is_dir():
            raise ValueError(f"Outputs-Verzeichnis konnte nicht erstellt werden: {outputs_dir}")
    
    def _setup_logging(self):
        """Konfiguriert das umfassende Logging-System."""
        log_level = getattr(logging, self.config.get('log_level', 'INFO'))
        logging_config = self.config.get('logging', {})
        
        # Detailliertes Log-Format
        detailed_formatter = logging.Formatter(
            '%(asctime)s - %(name)s - %(levelname)s - %(filename)s:%(lineno)d - %(message)s'
        )
        
        # Console Format (kürzer)
        console_formatter = logging.Formatter(
            '%(asctime)s - %(levelname)s - %(message)s'
        )
        
        # === CONSOLE HANDLER ===
        console_handler = logging.StreamHandler(sys.stdout)
        console_handler.setFormatter(console_formatter)
        console_handler.setLevel(log_level)
        
        # === MAIN LOG FILE (mit Rotation) ===
        main_log_file = logging_config.get('main_log_file', 'dnd_runner.log')
        max_size = logging_config.get('max_log_size_mb', 10) * 1024 * 1024  # MB zu Bytes
        backup_count = logging_config.get('backup_count', 5)
        
        main_file_handler = logging.handlers.RotatingFileHandler(
            main_log_file,
            maxBytes=max_size,
            backupCount=backup_count,
            encoding='utf-8'
        )
        main_file_handler.setFormatter(detailed_formatter)
        main_file_handler.setLevel(log_level)
        
        # === ERROR LOG FILE (nur Errors und Critical) ===
        error_log_file = logging_config.get('error_log_file', 'dnd_errors.log')
        error_file_handler = logging.handlers.RotatingFileHandler(
            error_log_file,
            maxBytes=max_size,
            backupCount=backup_count,
            encoding='utf-8'
        )
        error_file_handler.setFormatter(detailed_formatter)
        error_file_handler.setLevel(logging.ERROR)
        
        # === OLLAMA LOG FILE ===
        ollama_log_file = logging_config.get('ollama_log_file', 'ollama_service.log')
        self.ollama_file_handler = logging.handlers.RotatingFileHandler(
            ollama_log_file,
            maxBytes=max_size,
            backupCount=backup_count,
            encoding='utf-8'
        )
        self.ollama_file_handler.setFormatter(detailed_formatter)
        
        # === MAIN LOGGER KONFIGURIEREN ===
        self.logger = logging.getLogger('DnDRunner')
        self.logger.setLevel(log_level)
        self.logger.addHandler(console_handler)
        self.logger.addHandler(main_file_handler)
        self.logger.addHandler(error_file_handler)
        
        # === SEPARATE OLLAMA LOGGER ===
        self.ollama_logger = logging.getLogger('OllamaService')
        self.ollama_logger.setLevel(log_level)
        self.ollama_logger.addHandler(self.ollama_file_handler)
        self.ollama_logger.addHandler(console_handler)  # Auch auf Console
        
        # === SUBPROCESS OUTPUT LOGGER ===
        self.subprocess_logger = logging.getLogger('SubprocessOutput')
        self.subprocess_logger.setLevel(log_level)
        self.subprocess_logger.addHandler(main_file_handler)
        
        # Logging-Konfiguration loggen
        self.logger.info(f"Logging konfiguriert:")
        self.logger.info(f"  - Haupt-Log: {main_log_file}")
        self.logger.info(f"  - Error-Log: {error_log_file}")
        self.logger.info(f"  - Ollama-Log: {ollama_log_file}")
        self.logger.info(f"  - Log-Level: {log_level}")
        self.logger.info(f"  - Rotation: {max_size // (1024*1024)}MB, {backup_count} Backups")
    
    def _signal_handler(self, signum, frame):
        """Handler für System-Signale (graceful shutdown)."""
        self.logger.info(f"Signal {signum} empfangen, starte graceful shutdown...")
        self.running = False
    
    def _check_lock_file(self) -> bool:
        """Überprüft ob bereits eine Instanz läuft."""
        if self.lock_file.exists():
            try:
                with open(self.lock_file, 'r') as f:
                    pid = int(f.read().strip())
                
                # Prüfen ob Prozess noch läuft
                try:
                    os.kill(pid, 0)  # Prüft nur Existenz, sendet kein Signal
                    return False  # Prozess läuft noch
                except OSError:
                    # Prozess existiert nicht mehr, Lock-File löschen
                    self.lock_file.unlink()
                    return True
            except (ValueError, IOError):
                # Defektes Lock-File, löschen
                self.lock_file.unlink()
                return True
        return True
    
    def _create_lock_file(self):
        """Erstellt Lock-File mit aktueller PID."""
        with open(self.lock_file, 'w') as f:
            f.write(str(os.getpid()))
    
    def _remove_lock_file(self):
        """Entfernt Lock-File."""
        if self.lock_file.exists():
            self.lock_file.unlink()
    
    def _start_subprocess_logging(self, process, name):
        """Startet separaten Thread zum Logging von Subprocess Output."""
        def log_stdout():
            try:
                for line in iter(process.stdout.readline, ''):
                    if line.strip():
                        if name == 'ollama':
                            self.ollama_logger.info(f"STDOUT: {line.rstrip()}")
                        else:
                            self.subprocess_logger.info(f"{name} STDOUT: {line.rstrip()}")
            except Exception as e:
                self.logger.error(f"Fehler beim Logging von {name} stdout: {e}")
        
        def log_stderr():
            try:
                for line in iter(process.stderr.readline, ''):
                    if line.strip():
                        if name == 'ollama':
                            self.ollama_logger.warning(f"STDERR: {line.rstrip()}")
                        else:
                            self.subprocess_logger.warning(f"{name} STDERR: {line.rstrip()}")
            except Exception as e:
                self.logger.error(f"Fehler beim Logging von {name} stderr: {e}")
        
        # Threads starten
        stdout_thread = threading.Thread(target=log_stdout, daemon=True)
        stderr_thread = threading.Thread(target=log_stderr, daemon=True)
        
        stdout_thread.start()
        stderr_thread.start()
        
        self.logger.debug(f"Subprocess Logging für {name} gestartet")
    
    def _start_ollama(self) -> bool:
        """Startet den Ollama Service."""
        self.logger.info("Starte Ollama Service...")
        
        ollama_config = self.config['services']['ollama']
        script_path = ollama_config['script_path']
        
        if not pathlib.Path(script_path).exists():
            self.logger.error(f"Ollama Script nicht gefunden: {script_path}")
            return False
        
        try:
            # Ollama starten
            process = subprocess.Popen(
                ['bash', script_path],
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                preexec_fn=os.setsid,  # Neue Prozessgruppe
                text=True,  # Text-Modus für besseres Logging
                bufsize=1   # Zeilengepuffert
            )
            
            self.processes['ollama'] = process
            self.logger.info(f"Ollama gestartet mit PID: {process.pid}")
            
            # Subprocess Output Monitoring starten
            if self.config.get('logging', {}).get('log_subprocess_output', True):
                self._start_subprocess_logging(process, 'ollama')
            
            # Warten auf Startup
            startup_wait = ollama_config.get('startup_wait_seconds', 30)
            self.logger.info(f"Warte {startup_wait} Sekunden auf Ollama startup...")
            time.sleep(startup_wait)
            
            # Health Check
            if self._health_check_ollama():
                self.logger.info("Ollama erfolgreich gestartet und bereit")
                return True
            else:
                self.logger.error("Ollama Health Check fehlgeschlagen")
                return False
                
        except Exception as e:
            self.logger.error(f"Fehler beim Starten von Ollama: {e}")
            return False
    
    def _health_check_ollama(self) -> bool:
        """Führt Health Check für Ollama durch."""
        ollama_config = self.config['services']['ollama']
        health_url = ollama_config['health_check_url']
        
        try:
            response = requests.get(health_url, timeout=10)
            if response.status_code == 200:
                # Prüfen ob erforderliches Modell verfügbar ist
                models = response.json()
                required_model = ollama_config['required_model']
                
                for model in models.get('models', []):
                    if model.get('name') == required_model:
                        self.logger.debug(f"Erforderliches Modell gefunden: {required_model}")
                        return True
                
                self.logger.warning(f"Erforderliches Modell nicht gefunden: {required_model}")
                return False
            else:
                self.logger.error(f"Ollama Health Check fehlgeschlagen: HTTP {response.status_code}")
                return False
                
        except Exception as e:
            self.logger.error(f"Ollama Health Check Fehler: {e}")
            return False
    
    def _health_check_image_service(self) -> bool:
        """Führt Health Check für Image Generation Service durch mit Retry-Logik."""
        try:
            # Versuche Socket-Verbindung zu testen
            config_file = self.config['services']['image_generation']['config_file']
            
            if not pathlib.Path(config_file).exists():
                self.logger.error(f"Image Service Konfiguration nicht gefunden: {config_file}")
                return False
            
            # Image Service Config laden
            with open(config_file, 'r') as f:
                img_config = json.load(f)
            
            # Retry-Parameter aus Konfiguration
            img_service_config = self.config['services']['image_generation']
            timeout = img_service_config.get('health_check_timeout', 30)
            max_retries = img_service_config.get('max_retries', 3)
            retry_delay = img_service_config.get('retry_delay', 10)
            
            host = img_config['host']
            port = img_config['port']
            
            self.logger.info(f"🔍 Prüfe Image Service auf {host}:{port} (Timeout: {timeout}s, Max Retries: {max_retries})")
            
            # Retry-Schleife
            for attempt in range(max_retries):
                try:
                    self.logger.info(f"📡 Verbindungsversuch {attempt + 1}/{max_retries} zu {host}:{port}...")
                    
                    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
                    sock.settimeout(timeout)
                    
                    result = sock.connect_ex((host, port))
                    sock.close()
                    
                    if result == 0:
                        self.logger.info(f"✅ Image Service erfolgreich erreicht nach {attempt + 1} Versuch(en)")
                        return True
                    else:
                        self.logger.warning(f"⚠️ Verbindung fehlgeschlagen (Attempt {attempt + 1}): {host}:{port}")
                        
                        if attempt < max_retries - 1:
                            self.logger.info(f"⏳ Warte {retry_delay}s vor nächstem Versuch...")
                            time.sleep(retry_delay)
                        
                except Exception as e:
                    self.logger.warning(f"⚠️ Verbindungsfehler (Attempt {attempt + 1}): {e}")
                    if attempt < max_retries - 1:
                        self.logger.info(f"⏳ Warte {retry_delay}s vor nächstem Versuch...")
                        time.sleep(retry_delay)
            
            self.logger.error(f"❌ Image Service nicht erreichbar nach {max_retries} Versuchen: {host}:{port}")
            return False
                
        except Exception as e:
            self.logger.error(f"❌ Image Service Health Check Fehler: {e}")
            return False
    
    def _check_transcript_changes(self) -> bool:
        """Prüft ob sich das Transkript seit der letzten Generierung geändert hat."""
        try:
            transcript_config = self.config['transcript']
            transcript_file = pathlib.Path(transcript_config['file_path'])
            
            if not transcript_file.exists():
                self.logger.warning(f"Transkript-Datei nicht gefunden: {transcript_file}")
                return False
            
            # Modification time prüfen
            mtime = datetime.fromtimestamp(transcript_file.stat().st_mtime)
            
            if self.last_generation_time is None:
                self.logger.info("Erste Ausführung - Transkript wird verarbeitet")
                return True
            
            if mtime > self.last_generation_time:
                self.logger.info(f"Transkript wurde geändert seit {self.last_generation_time}")
                return True
            else:
                self.logger.debug("Keine Änderungen im Transkript erkannt")
                return False
                
        except Exception as e:
            self.logger.error(f"Fehler beim Prüfen der Transkript-Änderungen: {e}")
            return False
    
    def _generate_image_from_transcript(self, image_service_available: bool = True) -> Tuple[bool, Optional[str]]:
        """Generiert ein Bild basierend auf dem aktuellen Transkript."""
        self.logger.info("📝 Starte Bildgenerierung aus Transkript...")
        
        try:
            # Transkript parsen
            transcript_config = self.config['transcript']
            parser = parse_transkript.TranskriptParser(transcript_config['file_path'])
            
            last_minutes = transcript_config['last_minutes']
            transcript_entries = parser.get_transkript(last_minutes)
            
            if len(transcript_entries) < transcript_config.get('min_entries_required', 1):
                self.logger.warning(f"⚠️ Zu wenige Transkript-Einträge gefunden: {len(transcript_entries)}")
                return False, "Zu wenige Transkript-Einträge"
            
            self.logger.info(f"📊 Verarbeite {len(transcript_entries)} Transkript-Einträge")
            self.logger.debug(f"📄 Erste 3 Einträge:")
            for i, entry in enumerate(transcript_entries[:3]):
                self.logger.debug(f"  {i+1}: {entry}")
            
            # LLM Analyse
            self.logger.info("🧠 Starte LLM-Analyse...")
            
            # Import hier um circular imports zu vermeiden
            from dnd_image_generator import analyze_transcript_and_generate_prompt, parse_llm_response
            
            llm_start = datetime.now()
            llm_response = analyze_transcript_and_generate_prompt(transcript_entries)
            llm_duration = (datetime.now() - llm_start).total_seconds()
            
            self.logger.info(f"🤖 LLM-Analyse abgeschlossen nach {llm_duration:.1f}s")
            
            if "Fehler" in llm_response:
                self.logger.error(f"❌ LLM-Fehler: {llm_response}")
                return False, llm_response
            
            self.logger.debug(f"📝 LLM-Antwort (erste 200 Zeichen): {llm_response[:200]}...")
            
            # Prompt und Bildname extrahieren
            self.logger.info("🔍 Parse LLM-Antwort...")
            image_prompt, image_name = parse_llm_response(llm_response)
            
            if not image_prompt or not image_name:
                self.logger.error("❌ Konnte Prompt oder Bildname nicht extrahieren")
                self.logger.debug(f"🐛 Vollständige LLM-Antwort:\n{llm_response}")
                return False, "Parsing-Fehler"
            
            self.logger.info(f"✅ Extrahiert - Bildname: '{image_name}'")
            self.logger.info(f"✅ Extrahiert - Prompt: '{image_prompt[:100]}...'")
            
            # Bildpfad in outputs/ Verzeichnis  
            # WICHTIG: img_gen_service.py erwartet nur den Dateinamen, nicht den ganzen Pfad!
            # Der Service fügt selbst sein output_dir hinzu
            if not image_name.endswith('.png'):
                image_name += '.png'
            
            # Für Logging und Verification: kompletter lokaler Pfad
            output_file = f"{self.config['outputs_directory']}/{image_name}"
            
            # Prompt in Datei speichern (als Fallback)
            prompt_filename = image_name.replace('.png', '_prompt.txt')
            prompt_file = f"{self.config['outputs_directory']}/{prompt_filename}"
            try:
                with open(prompt_file, 'w', encoding='utf-8') as f:
                    f.write(f"Bildname: {image_name}\n")
                    f.write(f"Zeitstempel: {datetime.now()}\n")
                    f.write(f"Prompt: {image_prompt}\n\n")
                    f.write(f"Vollständige LLM-Antwort:\n{llm_response}\n")
                self.logger.info(f"💾 Prompt gespeichert: {prompt_file}")
            except Exception as e:
                self.logger.warning(f"⚠️ Konnte Prompt-Datei nicht speichern: {e}")
            
            # Bildgenerierung (je nach Service-Verfügbarkeit)
            if image_service_available:
                self.logger.info(f"🎨 Generiere Bild: {output_file}")
                self.logger.debug(f"🔍 Bildpfad-Details:")
                self.logger.debug(f"   - Relativer Pfad: {output_file}")
                self.logger.debug(f"   - Absoluter Pfad: {pathlib.Path(output_file).absolute()}")
                self.logger.debug(f"   - Verzeichnis existiert: {pathlib.Path(output_file).parent.exists()}")
                self.logger.debug(f"   - Verzeichnis beschreibbar: {os.access(pathlib.Path(output_file).parent, os.W_OK)}")
                
                try:
                    # An img_gen nur den Dateinamen senden, nicht den ganzen Pfad!
                    result = img_gen.generate_img(image_prompt, image_name)
                    
                    self.logger.debug(f"🔍 img_gen.generate_img Result: {result}")
                    
                    if result and not result.get("error"):
                        # Verify file actually exists after generation
                        result_file = pathlib.Path(output_file)
                        if result_file.exists():
                            file_size = result_file.stat().st_size
                            self.logger.info(f"✅ Bildgenerierung erfolgreich: {output_file} (Größe: {file_size} bytes)")
                            return True, output_file
                        else:
                            self.logger.error(f"❌ Bildgenerierung meldet Erfolg, aber Datei nicht gefunden: {output_file}")
                            return True, f"Prompt gespeichert: {prompt_file} (Datei nicht erstellt trotz Erfolgsantwort)"
                    elif result and result.get("error"):
                        self.logger.error(f"❌ Bildgenerierung fehlgeschlagen: {result['error']}")
                        return True, f"Prompt gespeichert: {prompt_file} (Bildgenerierung-Fehler: {result['error']})"
                    else:
                        self.logger.error("❌ Bildgenerierung fehlgeschlagen (Keine/leere Antwort)")
                        return True, f"Prompt gespeichert: {prompt_file} (Bildgenerierung fehlgeschlagen)"
                        
                except Exception as e:
                    self.logger.error(f"❌ Fehler bei Bildgenerierung: {e}")
                    return True, f"Prompt gespeichert: {prompt_file} (Bildgenerierung-Fehler: {e})"
            else:
                # Fallback-Modus: Nur Prompt speichern
                fallback_mode = self.config.get('image_generation', {}).get('fallback_mode', 'prompt_only')
                
                if fallback_mode == 'prompt_only':
                    self.logger.info("💡 Fallback-Modus: Nur Prompt-Generierung")
                    return True, f"Prompt gespeichert: {prompt_file} (Image Service nicht verfügbar)"
                elif fallback_mode == 'mock':
                    self.logger.info("🎭 Mock-Modus: Simuliere Bildgenerierung")
                    # Mock-Bild erstellen (leere Datei als Platzhalter)
                    try:
                        pathlib.Path(output_file).touch()
                        return True, f"Mock-Bild erstellt: {output_file}"
                    except Exception as e:
                        return True, f"Prompt gespeichert: {prompt_file} (Mock fehlgeschlagen: {e})"
                else:
                    return False, "Unbekannter Fallback-Modus"
                
        except Exception as e:
            self.logger.error(f"💀 Fehler bei der Bildgenerierung: {e}", exc_info=True)
            return False, str(e)
    
    def _run_generation_cycle(self):
        """Führt einen kompletten Generierungszyklus durch."""
        self.logger.info("=== Starte Generierungszyklus ===")
        
        try:
            # Ollama Health Check (kritisch)
            if not self._health_check_ollama():
                self.logger.error("❌ Ollama Health Check fehlgeschlagen - überspringe Zyklus")
                return
            
            # Image Service Health Check (optional je nach Konfiguration)
            image_service_available = self._health_check_image_service()
            skip_on_failure = self.config.get('image_generation', {}).get('skip_on_service_failure', False)
            
            if not image_service_available:
                if skip_on_failure:
                    self.logger.error("❌ Image Service nicht verfügbar - überspringe Zyklus (skip_on_service_failure=true)")
                    return
                else:
                    self.logger.warning("⚠️ Image Service nicht verfügbar - fahre trotzdem fort (skip_on_service_failure=false)")
            
            # Transkript-Änderungen prüfen
            if not self._check_transcript_changes():
                self.logger.info("📋 Keine Transkript-Änderungen - überspringe Generierung")
                return
            
            # Bildgenerierung mit Fallback-Modi
            start_time = datetime.now()
            self.logger.info("🚀 Starte Bildgenerierung...")
            
            success, result = self._generate_image_from_transcript(image_service_available)
            
            end_time = datetime.now()
            duration = end_time - start_time
            
            if success:
                self.logger.info(f"✅ Zyklus erfolgreich abgeschlossen in {duration.total_seconds():.1f}s")
                self.logger.info(f"📁 Ergebnis: {result}")
                self.last_generation_time = datetime.now()
            else:
                self.logger.error(f"❌ Zyklus fehlgeschlagen nach {duration.total_seconds():.1f}s")
                self.logger.error(f"💥 Fehler: {result}")
                
        except Exception as e:
            self.logger.error(f"💀 Unerwarteter Fehler im Generierungszyklus: {e}", exc_info=True)
        
        self.logger.info("=== Generierungszyklus beendet ===")
    
    def _cleanup_processes(self):
        """Beendet alle gestarteten Prozesse."""
        self.logger.info("Beende alle Prozesse...")
        
        for name, process in self.processes.items():
            try:
                if process.poll() is None:  # Prozess läuft noch
                    self.logger.info(f"Beende {name} (PID: {process.pid})")
                    
                    # Versuche graceful shutdown
                    os.killpg(os.getpgid(process.pid), signal.SIGTERM)
                    
                    # Warte kurz
                    try:
                        process.wait(timeout=10)
                        self.logger.info(f"{name} erfolgreich beendet")
                    except subprocess.TimeoutExpired:
                        # Force kill
                        self.logger.warning(f"Force kill für {name}")
                        os.killpg(os.getpgid(process.pid), signal.SIGKILL)
                        process.wait()
                        
            except Exception as e:
                self.logger.error(f"Fehler beim Beenden von {name}: {e}")
    
    def run(self):
        """Hauptschleife des Runners."""
        self.logger.info("D&D Visualizer Runner gestartet")
        
        # Lock File prüfen
        if not self._check_lock_file():
            self.logger.error("Eine andere Instanz läuft bereits")
            return False
        
        self._create_lock_file()
        
        try:
            # Ollama starten
            if not self._start_ollama():
                self.logger.error("Ollama konnte nicht gestartet werden")
                return False
            
            # Haupt-Loop
            self.running = True
            interval_seconds = self.config['interval_minutes'] * 60
            
            self.logger.info(f"Starte Hauptschleife mit {self.config['interval_minutes']} Minuten Intervall")
            
            while self.running:
                self._run_generation_cycle()
                
                # Warten mit Unterbrechungsmöglichkeit
                for _ in range(interval_seconds):
                    if not self.running:
                        break
                    time.sleep(1)
            
            self.logger.info("Hauptschleife beendet")
            return True
            
        except Exception as e:
            self.logger.error(f"Kritischer Fehler: {e}", exc_info=True)
            return False
            
        finally:
            self._cleanup_processes()
            self._remove_lock_file()
            self.logger.info("🔻 D&D Visualizer Runner beendet")
            
            # Logging sauber beenden
            logging.shutdown()

def main():
    """Hauptfunktion."""
    print("=== D&D Visualizer Runner ===")
    
    # Konfigurationsdatei aus Kommandozeile
    config_file = sys.argv[1] if len(sys.argv) > 1 else "run_config.json"
    
    try:
        runner = DnDVisualizerRunner(config_file)
        success = runner.run()
        sys.exit(0 if success else 1)
        
    except KeyboardInterrupt:
        print("\nUnterbrochen durch Benutzer")
        sys.exit(0)
    except Exception as e:
        print(f"Kritischer Fehler: {e}")
        sys.exit(1)

if __name__ == "__main__":
    main() 