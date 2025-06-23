#!/usr/bin/env python3
"""
Umfassendes Debug-System für Scene Visualizer
Testet alle Komponenten und bietet Live-Monitoring
"""
import os
import sys
import json
import time
import signal
import psutil
import pathlib
import logging
import hashlib
import threading
import subprocess
from datetime import datetime
from typing import Dict, List, Optional

class SceneSystemDebugger:
    """Debugger für das gesamte Scene-System."""
    
    def __init__(self):
        self.setup_logging()
        self.transkript_dir = pathlib.Path("web/transkripte")
        self.scene_dir = pathlib.Path("web/scene")
        self.tracking_file = self.transkript_dir / "transkript_tracking.json"
        self.monitoring = False
        
    def setup_logging(self):
        """Konfiguriert detailliertes Logging."""
        logging.basicConfig(
            level=logging.DEBUG,
            format='[%(asctime)s] %(levelname)s: %(message)s',
            handlers=[
                logging.StreamHandler(sys.stdout),
                logging.FileHandler('debug_scene_system.log', encoding='utf-8')
            ]
        )
        self.logger = logging.getLogger('SceneDebugger')
    
    def test_environment(self) -> Dict[str, bool]:
        """Testet die grundlegende Umgebung."""
        self.logger.info("🧪 === ENVIRONMENT TEST ===")
        
        results = {}
        
        # Python und Module
        try:
            import watchdog, ollama
            results['modules'] = True
            self.logger.info("✅ Required modules available")
        except ImportError as e:
            results['modules'] = False
            self.logger.error(f"❌ Missing modules: {e}")
        
        # Verzeichnisse
        dirs_exist = all([
            self.transkript_dir.exists(),
            self.scene_dir.exists()
        ])
        results['directories'] = dirs_exist
        self.logger.info(f"{'✅' if dirs_exist else '❌'} Directories: {dirs_exist}")
        
        # Tracking-Datei
        tracking_exists = self.tracking_file.exists()
        results['tracking'] = tracking_exists
        self.logger.info(f"{'✅' if tracking_exists else '❌'} Tracking file: {tracking_exists}")
        
        # Transkripte
        transcripts = list(self.transkript_dir.glob("*_transkript.txt"))
        results['transcripts'] = len(transcripts) > 0
        self.logger.info(f"📄 Found {len(transcripts)} transcripts")
        
        return results
    
    def test_services(self) -> Dict[str, Dict[str, any]]:
        """Testet alle Services."""
        self.logger.info("🧪 === SERVICES TEST ===")
        
        results = {}
        
        # Ollama Service
        ollama_status = self.check_ollama_service()
        results['ollama'] = ollama_status
        
        # Image Generation Service
        img_service_status = self.check_image_service()
        results['image_service'] = img_service_status
        
        # Scene Visualizer Runner
        runner_status = self.check_runner_process()
        results['scene_runner'] = runner_status
        
        return results
    
    def check_ollama_service(self) -> Dict[str, any]:
        """Prüft Ollama Service detailliert."""
        result = {
            'running': False,
            'port_open': False,
            'responding': False,
            'model_available': False,
            'details': {}
        }
        
        # Port Check
        try:
            import socket
            sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            sock.settimeout(2)
            port_result = sock.connect_ex(('127.0.0.1', 11434))
            result['port_open'] = port_result == 0
            sock.close()
        except Exception as e:
            result['details']['port_error'] = str(e)
        
        # Process Check
        ollama_processes = []
        for proc in psutil.process_iter(['pid', 'name', 'cmdline']):
            try:
                if 'ollama' in proc.info['name'].lower():
                    ollama_processes.append({
                        'pid': proc.info['pid'],
                        'name': proc.info['name'],
                        'cmdline': ' '.join(proc.info['cmdline']) if proc.info['cmdline'] else ''
                    })
            except (psutil.NoSuchProcess, psutil.AccessDenied):
                pass
        
        result['running'] = len(ollama_processes) > 0
        result['details']['processes'] = ollama_processes
        
        # API Test
        if result['port_open']:
            try:
                import requests
                response = requests.get('http://127.0.0.1:11434/api/version', timeout=5)
                result['responding'] = response.status_code == 200
                if result['responding']:
                    result['details']['version'] = response.json()
            except Exception as e:
                result['details']['api_error'] = str(e)
        
        # Model Check
        if result['responding']:
            try:
                import ollama
                models = ollama.list()
                model_names = [m['name'] for m in models.get('models', [])]
                result['model_available'] = 'deepseek-r1:8b' in model_names
                result['details']['models'] = model_names
            except Exception as e:
                result['details']['model_error'] = str(e)
        
        status = "✅" if all([result['running'], result['port_open'], result['responding']]) else "❌"
        self.logger.info(f"{status} Ollama: running={result['running']}, port={result['port_open']}, responding={result['responding']}")
        
        return result
    
    def check_image_service(self) -> Dict[str, any]:
        """Prüft Image Generation Service."""
        result = {
            'running': False,
            'port_open': False,
            'responding': False,
            'details': {}
        }
        
        # Port Check (Standard: 5555)
        try:
            import socket
            sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            sock.settimeout(2)
            port_result = sock.connect_ex(('127.0.0.1', 5555))
            result['port_open'] = port_result == 0
            sock.close()
        except Exception as e:
            result['details']['port_error'] = str(e)
        
        # Process Check
        img_processes = []
        for proc in psutil.process_iter(['pid', 'name', 'cmdline']):
            try:
                cmdline = ' '.join(proc.info['cmdline']) if proc.info['cmdline'] else ''
                if 'img_gen_service.py' in cmdline:
                    img_processes.append({
                        'pid': proc.info['pid'],
                        'name': proc.info['name'],
                        'cmdline': cmdline
                    })
            except (psutil.NoSuchProcess, psutil.AccessDenied):
                pass
        
        result['running'] = len(img_processes) > 0
        result['details']['processes'] = img_processes
        
        # API Test
        if result['port_open']:
            try:
                import requests
                response = requests.post('http://127.0.0.1:5555/health', timeout=5)
                result['responding'] = response.status_code == 200
            except Exception as e:
                result['details']['api_error'] = str(e)
        
        status = "✅" if all([result['running'], result['port_open']]) else "❌"
        self.logger.info(f"{status} Image Service: running={result['running']}, port={result['port_open']}")
        
        return result
    
    def check_runner_process(self) -> Dict[str, any]:
        """Prüft Scene Visualizer Runner Process."""
        result = {
            'running': False,
            'details': {}
        }
        
        runner_processes = []
        for proc in psutil.process_iter(['pid', 'name', 'cmdline']):
            try:
                cmdline = ' '.join(proc.info['cmdline']) if proc.info['cmdline'] else ''
                if 'scene_visualizer_runner.py' in cmdline:
                    runner_processes.append({
                        'pid': proc.info['pid'],
                        'name': proc.info['name'],
                        'cmdline': cmdline
                    })
            except (psutil.NoSuchProcess, psutil.AccessDenied):
                pass
        
        result['running'] = len(runner_processes) > 0
        result['details']['processes'] = runner_processes
        
        status = "✅" if result['running'] else "❌"
        self.logger.info(f"{status} Scene Runner: running={result['running']}")
        
        return result
    
    def test_tracking_system(self) -> Dict[str, any]:
        """Testet das Tracking-System detailliert."""
        self.logger.info("🧪 === TRACKING SYSTEM TEST ===")
        
        result = {
            'file_exists': False,
            'valid_json': False,
            'synchronized': False,
            'details': {}
        }
        
        # Datei existiert?
        result['file_exists'] = self.tracking_file.exists()
        
        if result['file_exists']:
            try:
                with open(self.tracking_file, 'r', encoding='utf-8') as f:
                    tracking_data = json.load(f)
                result['valid_json'] = True
                result['details']['tracking_data'] = tracking_data
                
                # Synchronisations-Check
                actual_files = list(self.transkript_dir.glob("*_transkript.txt"))
                tracked_files = tracking_data.get('transcripts', {})
                
                actual_names = {f.name for f in actual_files}
                tracked_names = set(tracked_files.keys())
                
                missing_in_tracking = actual_names - tracked_names
                missing_in_filesystem = tracked_names - actual_names
                
                result['synchronized'] = len(missing_in_tracking) == 0 and len(missing_in_filesystem) == 0
                result['details']['actual_count'] = len(actual_files)
                result['details']['tracked_count'] = len(tracked_files)
                result['details']['missing_in_tracking'] = list(missing_in_tracking)
                result['details']['missing_in_filesystem'] = list(missing_in_filesystem)
                
                self.logger.info(f"📊 Tracking: {len(tracked_files)} tracked, {len(actual_files)} actual")
                if missing_in_tracking:
                    self.logger.warning(f"⚠️ Missing in tracking: {missing_in_tracking}")
                if missing_in_filesystem:
                    self.logger.warning(f"⚠️ Missing in filesystem: {missing_in_filesystem}")
                
            except json.JSONDecodeError as e:
                result['details']['json_error'] = str(e)
                self.logger.error(f"❌ Invalid JSON in tracking file: {e}")
            except Exception as e:
                result['details']['error'] = str(e)
                self.logger.error(f"❌ Error reading tracking file: {e}")
        else:
            self.logger.warning("⚠️ Tracking file does not exist")
        
        return result
    
    def test_file_events(self) -> bool:
        """Testet File-Event-System mit echten Dateien."""
        self.logger.info("🧪 === FILE EVENTS TEST ===")
        
        # Erstelle Test-Datei
        timestamp = datetime.now().strftime("%H%M%S")
        test_file = self.transkript_dir / f"test_event_{timestamp}_transkript.txt"
        
        test_content = f"""# Test Event Transkript - {timestamp}

## SZENEN-METADATEN
- **Scene Name**: test_event_{timestamp}
- **Datum**: {datetime.now().strftime("%Y-%m-%d")}

## ZEITGESTEMPELTE SEGMENTE

### [00:00 - 01:00] - Test Segment
**GM**: Dies ist ein Test-Segment für Event-Erkennung.
**Player**: Verstanden!
"""
        
        try:
            # Schreibe Test-Datei
            with open(test_file, 'w', encoding='utf-8') as f:
                f.write(test_content)
            
            self.logger.info(f"📝 Test-Datei erstellt: {test_file.name}")
            
            # Warte und prüfe ob Tracking reagiert
            initial_tracking = self.read_tracking_data()
            self.logger.info("⏳ Warte 10 Sekunden auf Tracking-Update...")
            time.sleep(10)
            
            updated_tracking = self.read_tracking_data()
            
            # Vergleiche
            if initial_tracking and updated_tracking:
                initial_count = len(initial_tracking.get('transcripts', {}))
                updated_count = len(updated_tracking.get('transcripts', {}))
                
                if updated_count > initial_count:
                    self.logger.info("✅ Tracking hat neue Datei erkannt!")
                    return True
                else:
                    self.logger.error("❌ Tracking hat neue Datei NICHT erkannt!")
                    return False
            else:
                self.logger.error("❌ Konnte Tracking-Daten nicht lesen")
                return False
                
        except Exception as e:
            self.logger.error(f"❌ Fehler bei File-Event-Test: {e}")
            return False
        finally:
            # Cleanup
            if test_file.exists():
                test_file.unlink()
                self.logger.info(f"🗑️ Test-Datei entfernt: {test_file.name}")
    
    def read_tracking_data(self) -> Optional[Dict]:
        """Liest Tracking-Daten."""
        try:
            if self.tracking_file.exists():
                with open(self.tracking_file, 'r', encoding='utf-8') as f:
                    return json.load(f)
        except Exception as e:
            self.logger.error(f"Fehler beim Lesen der Tracking-Daten: {e}")
        return None
    
    def monitor_live(self, duration_seconds: int = 30):
        """Live-Monitoring für debugging."""
        self.logger.info(f"🔍 === LIVE MONITORING ({duration_seconds}s) ===")
        
        self.monitoring = True
        start_time = time.time()
        initial_tracking = self.read_tracking_data()
        
        def monitor_worker():
            last_tracking = initial_tracking
            
            while self.monitoring and (time.time() - start_time) < duration_seconds:
                try:
                    # Check tracking changes
                    current_tracking = self.read_tracking_data()
                    if current_tracking != last_tracking:
                        self.logger.info("🔄 TRACKING CHANGED!")
                        if current_tracking:
                            current_count = len(current_tracking.get('transcripts', {}))
                            last_count = len(last_tracking.get('transcripts', {})) if last_tracking else 0
                            self.logger.info(f"   Files: {last_count} → {current_count}")
                        last_tracking = current_tracking
                    
                    # Check for new files in filesystem
                    current_files = set(f.name for f in self.transkript_dir.glob("*_transkript.txt"))
                    if hasattr(self, '_last_files'):
                        new_files = current_files - self._last_files
                        removed_files = self._last_files - current_files
                        
                        if new_files:
                            self.logger.info(f"📁 NEW FILES DETECTED: {new_files}")
                        if removed_files:
                            self.logger.info(f"📁 FILES REMOVED: {removed_files}")
                    
                    self._last_files = current_files
                    
                    time.sleep(2)
                    
                except Exception as e:
                    self.logger.error(f"Monitor error: {e}")
                    time.sleep(5)
        
        monitor_thread = threading.Thread(target=monitor_worker, daemon=True)
        monitor_thread.start()
        
        self.logger.info("🔍 Live monitoring gestartet... (Strg+C zum Beenden)")
        self.logger.info("💡 Jetzt ist der perfekte Zeitpunkt, um manuell ein neues Transkript hinzuzufügen!")
        
        try:
            monitor_thread.join(timeout=duration_seconds + 5)
        except KeyboardInterrupt:
            self.logger.info("🛑 Monitoring unterbrochen")
        finally:
            self.monitoring = False
    
    def comprehensive_test(self):
        """Führt alle Tests durch."""
        self.logger.info("🚀 === COMPREHENSIVE SCENE SYSTEM TEST ===")
        
        # 1. Environment
        env_results = self.test_environment()
        
        # 2. Services
        service_results = self.test_services()
        
        # 3. Tracking
        tracking_results = self.test_tracking_system()
        
        # 4. File Events
        file_event_success = self.test_file_events()
        
        # Summary
        self.logger.info("\n" + "="*60)
        self.logger.info("📊 TEST SUMMARY")
        self.logger.info("="*60)
        
        self.logger.info("🌍 ENVIRONMENT:")
        for test, result in env_results.items():
            status = "✅" if result else "❌"
            self.logger.info(f"   {status} {test}: {result}")
        
        self.logger.info("\n🔧 SERVICES:")
        for service, data in service_results.items():
            main_status = "✅" if data.get('running', False) else "❌"
            self.logger.info(f"   {main_status} {service}: {data}")
        
        self.logger.info(f"\n📊 TRACKING: {'✅' if tracking_results['synchronized'] else '❌'}")
        self.logger.info(f"   Details: {tracking_results}")
        
        self.logger.info(f"\n📁 FILE EVENTS: {'✅' if file_event_success else '❌'}")
        
        # Hauptprobleme identifizieren
        self.logger.info("\n🔍 IDENTIFIED ISSUES:")
        issues = []
        
        if not service_results.get('scene_runner', {}).get('running', False):
            issues.append("Scene Visualizer Runner ist nicht aktiv")
        
        if not tracking_results['synchronized']:
            issues.append("Tracking-System ist nicht synchronisiert")
        
        if not file_event_success:
            issues.append("File-Event-System funktioniert nicht")
        
        if not service_results.get('ollama', {}).get('responding', False):
            issues.append("Ollama Service antwortet nicht")
        
        if not service_results.get('image_service', {}).get('port_open', False):
            issues.append("Image Service ist nicht verfügbar")
        
        if issues:
            for issue in issues:
                self.logger.error(f"❌ {issue}")
        else:
            self.logger.info("✅ Keine kritischen Probleme gefunden!")
        
        return len(issues) == 0

def main():
    """Hauptfunktion."""
    debugger = SceneSystemDebugger()
    
    if len(sys.argv) > 1:
        if sys.argv[1] == "monitor":
            duration = int(sys.argv[2]) if len(sys.argv) > 2 else 60
            debugger.monitor_live(duration)
        elif sys.argv[1] == "services":
            debugger.test_services()
        elif sys.argv[1] == "tracking":
            debugger.test_tracking_system()
        elif sys.argv[1] == "events":
            debugger.test_file_events()
        else:
            print("Usage: python debug_scene_system.py [monitor|services|tracking|events] [duration]")
    else:
        debugger.comprehensive_test()

if __name__ == "__main__":
    main() 