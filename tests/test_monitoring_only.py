#!/usr/bin/env python3
"""
Fokussierter Test nur für das File-Monitoring-System
Simuliert das Hinzufügen neuer Transkripte und überwacht die Reaktion
"""
import os
import sys
import json
import time
import pathlib
import logging
import hashlib
import threading
from datetime import datetime
from watchdog.observers import Observer
from watchdog.events import FileSystemEventHandler

class MonitoringTestHandler(FileSystemEventHandler):
    """Test-Handler für Watchdog Events."""
    
    def __init__(self, logger):
        self.logger = logger
        self.events_received = []
    
    def on_created(self, event):
        if event.is_directory:
            return
        
        self.logger.info(f"🔔 WATCHDOG EVENT: File created: {event.src_path}")
        self.events_received.append({
            'type': 'created',
            'path': event.src_path,
            'timestamp': datetime.now().isoformat()
        })
        
        if event.src_path.endswith("_transkript.txt"):
            self.logger.info(f"✅ RELEVANT EVENT: Transcript file detected!")
    
    def on_modified(self, event):
        if not event.is_directory and event.src_path.endswith("_transkript.txt"):
            self.logger.info(f"🔄 WATCHDOG EVENT: File modified: {event.src_path}")
            self.events_received.append({
                'type': 'modified',
                'path': event.src_path,
                'timestamp': datetime.now().isoformat()
            })

class MonitoringTester:
    """Spezieller Tester für das Monitoring-System."""
    
    def __init__(self):
        self.setup_logging()
        self.transkript_dir = pathlib.Path("web/transkripte")
        self.tracking_file = self.transkript_dir / "transkript_tracking.json"
        self.observer = None
        self.test_handler = None
        
    def setup_logging(self):
        """Konfiguriert detailliertes Logging."""
        logging.basicConfig(
            level=logging.DEBUG,
            format='[%(asctime)s] %(levelname)s: %(message)s',
            handlers=[
                logging.StreamHandler(sys.stdout),
                logging.FileHandler('monitoring_test.log', encoding='utf-8')
            ]
        )
        self.logger = logging.getLogger('MonitoringTester')
    
    def start_watchdog_monitoring(self):
        """Startet Watchdog-Monitoring für Tests."""
        self.logger.info("👁️ Starte Watchdog-Monitoring...")
        
        self.test_handler = MonitoringTestHandler(self.logger)
        self.observer = Observer()
        self.observer.schedule(self.test_handler, str(self.transkript_dir), recursive=False)
        self.observer.start()
        
        self.logger.info(f"✅ Watchdog aktiv für: {self.transkript_dir}")
    
    def stop_watchdog_monitoring(self):
        """Stoppt Watchdog-Monitoring."""
        if self.observer:
            self.observer.stop()
            self.observer.join()
            self.logger.info("🛑 Watchdog gestoppt")
    
    def read_tracking_json(self):
        """Liest aktuelle Tracking-Daten."""
        try:
            if self.tracking_file.exists():
                with open(self.tracking_file, 'r', encoding='utf-8') as f:
                    data = json.load(f)
                return data
            else:
                self.logger.warning("⚠️ Tracking-Datei existiert nicht")
                return None
        except Exception as e:
            self.logger.error(f"❌ Fehler beim Lesen der Tracking-Datei: {e}")
            return None
    
    def simulate_sync_tracking(self):
        """Simuliert die _sync_tracking_with_filesystem Logik."""
        self.logger.info("🔄 Simuliere Tracking-Synchronisation...")
        
        # Lade aktuelles Tracking
        tracking_data = self.read_tracking_json()
        if not tracking_data:
            tracking_data = {
                "last_updated": datetime.now().isoformat(),
                "transcripts": {},
                "status": "initialized"
            }
        
        # Scanne Dateisystem
        current_files = {}
        for file_path in self.transkript_dir.glob("*_transkript.txt"):
            file_hash = self.get_file_hash(file_path)
            file_info = {
                "filename": file_path.name,
                "size": file_path.stat().st_size,
                "modified": datetime.fromtimestamp(file_path.stat().st_mtime).isoformat(),
                "hash": file_hash,
                "status": "detected"
            }
            current_files[file_path.name] = file_info
        
        self.logger.info(f"📊 Dateisystem: {len(current_files)} Dateien gefunden")
        self.logger.info(f"📊 Tracking: {len(tracking_data['transcripts'])} Dateien verfolgt")
        
        # Vergleiche und aktualisiere
        new_files = []
        for filename, file_info in current_files.items():
            if filename not in tracking_data["transcripts"]:
                # Neue Datei
                file_info["status"] = "new"
                tracking_data["transcripts"][filename] = file_info
                new_files.append(filename)
                self.logger.info(f"🆕 NEUE DATEI ERKANNT: {filename}")
            elif tracking_data["transcripts"][filename]["hash"] != file_info["hash"]:
                # Datei geändert
                tracking_data["transcripts"][filename] = file_info
                tracking_data["transcripts"][filename]["status"] = "modified"
                self.logger.info(f"🔄 DATEI GEÄNDERT: {filename}")
        
        # Speichere Updates
        if new_files:
            tracking_data["last_updated"] = datetime.now().isoformat()
            tracking_data["status"] = "active"
            
            # Backup
            backup_file = self.tracking_file.with_suffix('.json.test_backup')
            if self.tracking_file.exists():
                import shutil
                shutil.copy2(self.tracking_file, backup_file)
            
            with open(self.tracking_file, 'w', encoding='utf-8') as f:
                json.dump(tracking_data, f, indent=2, ensure_ascii=False)
            
            self.logger.info(f"💾 Tracking aktualisiert: {len(new_files)} neue Dateien")
        
        return new_files
    
    def get_file_hash(self, file_path):
        """Berechnet MD5-Hash einer Datei."""
        try:
            with open(file_path, 'rb') as f:
                return hashlib.md5(f.read()).hexdigest()
        except Exception as e:
            self.logger.error(f"Fehler beim Hash-Berechnen für {file_path}: {e}")
            return ""
    
    def create_test_transcript(self, suffix=""):
        """Erstellt ein Test-Transkript."""
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        if suffix:
            filename = f"test_{timestamp}_{suffix}_transkript.txt"
        else:
            filename = f"test_{timestamp}_transkript.txt"
        
        test_path = self.transkript_dir / filename
        
        test_content = f"""# Test Monitoring Transkript - {timestamp}

## SZENEN-METADATEN
- **Scene Name**: test_monitoring_{timestamp}
- **Datum**: {datetime.now().strftime("%Y-%m-%d")}
- **Zeit**: {datetime.now().strftime("%H:%M:%S")}
- **Test-Zweck**: File Monitoring Test

## ZEITGESTEMPELTE SEGMENTE

### [00:00 - 02:00] - Monitoring Test Segment
**GM**: Dies ist ein Test-Segment zur Überprüfung des File-Monitoring-Systems.

**Player1**: Ich teste das Event-System.

**GM**: Das System sollte diese Datei automatisch erkennen.

### [02:00 - 04:00] - Zweites Segment
**Player2**: Weitere Inhalte zum Testen der Segmentierung.

**GM**: Der Parser sollte {len(test_content.split('###')) - 1} Segmente finden.
"""
        
        with open(test_path, 'w', encoding='utf-8') as f:
            f.write(test_content)
        
        self.logger.info(f"📝 Test-Transkript erstellt: {filename}")
        self.logger.info(f"📊 Dateigröße: {test_path.stat().st_size} bytes")
        
        return test_path
    
    def monitoring_stress_test(self, num_files=3, delay_between=5):
        """Stress-Test mit mehreren Dateien."""
        self.logger.info(f"💪 === MONITORING STRESS TEST ({num_files} Dateien) ===")
        
        # Starte Watchdog
        self.start_watchdog_monitoring()
        
        try:
            created_files = []
            
            for i in range(num_files):
                self.logger.info(f"\n--- TEST DATEI {i+1}/{num_files} ---")
                
                # Tracking vor Erstellung
                tracking_before = self.read_tracking_json()
                files_before = len(tracking_before.get('transcripts', {})) if tracking_before else 0
                
                # Erstelle Datei
                test_file = self.create_test_transcript(f"stress_{i+1}")
                created_files.append(test_file)
                
                # Warte auf Events
                self.logger.info(f"⏳ Warte {delay_between}s auf Events...")
                time.sleep(delay_between)
                
                # Prüfe Watchdog Events
                if self.test_handler:
                    recent_events = [e for e in self.test_handler.events_received 
                                   if test_file.name in e['path']]
                    if recent_events:
                        self.logger.info(f"✅ Watchdog Events für {test_file.name}: {len(recent_events)}")
                        for event in recent_events:
                            self.logger.info(f"   - {event['type']} at {event['timestamp']}")
                    else:
                        self.logger.error(f"❌ Keine Watchdog Events für {test_file.name}")
                
                # Simuliere Tracking-Update
                new_files = self.simulate_sync_tracking()
                if test_file.name in new_files:
                    self.logger.info(f"✅ Tracking hat {test_file.name} erkannt")
                else:
                    self.logger.error(f"❌ Tracking hat {test_file.name} NICHT erkannt")
            
            # Finale Zusammenfassung
            self.logger.info(f"\n📊 STRESS TEST ZUSAMMENFASSUNG:")
            self.logger.info(f"📁 Dateien erstellt: {len(created_files)}")
            
            if self.test_handler:
                total_events = len(self.test_handler.events_received)
                self.logger.info(f"🔔 Watchdog Events: {total_events}")
                
                for event in self.test_handler.events_received:
                    self.logger.info(f"   - {event['type']}: {pathlib.Path(event['path']).name}")
            
            final_tracking = self.read_tracking_json()
            if final_tracking:
                final_count = len(final_tracking.get('transcripts', {}))
                self.logger.info(f"📊 Finale Tracking-Anzahl: {final_count}")
            
            return created_files
            
        finally:
            self.stop_watchdog_monitoring()
    
    def live_monitoring_test(self, duration=60):
        """Live-Monitoring-Test."""
        self.logger.info(f"🔍 === LIVE MONITORING TEST ({duration}s) ===")
        
        self.start_watchdog_monitoring()
        
        try:
            start_time = time.time()
            last_tracking = self.read_tracking_json()
            check_interval = 3  # Sekunden
            
            self.logger.info("🔍 Live-Monitoring aktiv...")
            self.logger.info("💡 JETZT kannst du manuell neue Transkripte hinzufügen!")
            self.logger.info(f"📁 Überwachter Ordner: {self.transkript_dir.absolute()}")
            
            while (time.time() - start_time) < duration:
                # Prüfe Tracking-Änderungen
                current_tracking = self.read_tracking_json()
                if current_tracking != last_tracking:
                    self.logger.info("🔄 TRACKING HAT SICH GEÄNDERT!")
                    
                    if current_tracking and last_tracking:
                        old_count = len(last_tracking.get('transcripts', {}))
                        new_count = len(current_tracking.get('transcripts', {}))
                        self.logger.info(f"   Dateien: {old_count} → {new_count}")
                        
                        # Neue Dateien identifizieren
                        old_files = set(last_tracking.get('transcripts', {}).keys())
                        new_files = set(current_tracking.get('transcripts', {}).keys())
                        added_files = new_files - old_files
                        
                        if added_files:
                            self.logger.info(f"   ➕ Hinzugefügt: {added_files}")
                    
                    last_tracking = current_tracking
                
                # Prüfe Watchdog Events
                if self.test_handler and self.test_handler.events_received:
                    recent_events = [e for e in self.test_handler.events_received 
                                   if (time.time() - datetime.fromisoformat(e['timestamp'].replace('Z', '+00:00')).timestamp()) < check_interval]
                    if recent_events:
                        for event in recent_events:
                            self.logger.info(f"🔔 Recent Event: {event['type']} - {pathlib.Path(event['path']).name}")
                
                time.sleep(check_interval)
            
            self.logger.info("⏰ Live-Monitoring-Test beendet")
            
        except KeyboardInterrupt:
            self.logger.info("🛑 Live-Monitoring durch Benutzer unterbrochen")
        finally:
            self.stop_watchdog_monitoring()
    
    def cleanup_test_files(self):
        """Entfernt Test-Dateien."""
        test_files = list(self.transkript_dir.glob("test_*_transkript.txt"))
        
        if test_files:
            self.logger.info(f"🗑️ Entferne {len(test_files)} Test-Dateien...")
            for test_file in test_files:
                try:
                    test_file.unlink()
                    self.logger.info(f"   ✅ Entfernt: {test_file.name}")
                except Exception as e:
                    self.logger.error(f"   ❌ Fehler beim Entfernen von {test_file.name}: {e}")
        else:
            self.logger.info("✅ Keine Test-Dateien zum Entfernen gefunden")

def main():
    """Hauptfunktion."""
    tester = MonitoringTester()
    
    if len(sys.argv) > 1:
        command = sys.argv[1]
        
        if command == "stress":
            num_files = int(sys.argv[2]) if len(sys.argv) > 2 else 3
            delay = int(sys.argv[3]) if len(sys.argv) > 3 else 5
            created_files = tester.monitoring_stress_test(num_files, delay)
            
            # Cleanup
            input("\nDrücke Enter um Test-Dateien zu entfernen...")
            for f in created_files:
                if f.exists():
                    f.unlink()
                    
        elif command == "live":
            duration = int(sys.argv[2]) if len(sys.argv) > 2 else 60
            tester.live_monitoring_test(duration)
            
        elif command == "cleanup":
            tester.cleanup_test_files()
            
        else:
            print("Usage:")
            print("  python test_monitoring_only.py stress [num_files] [delay_seconds]")
            print("  python test_monitoring_only.py live [duration_seconds]")
            print("  python test_monitoring_only.py cleanup")
    else:
        # Standard: Kurzer Stress-Test
        print("🧪 Standard-Test: 2 Dateien mit 5s Verzögerung")
        created_files = tester.monitoring_stress_test(2, 5)
        
        # Cleanup
        print("\n🗑️ Entferne Test-Dateien...")
        for f in created_files:
            if f.exists():
                f.unlink()
                print(f"   ✅ {f.name} entfernt")

if __name__ == "__main__":
    main() 