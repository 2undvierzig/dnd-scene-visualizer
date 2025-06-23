#!/usr/bin/env python3
"""
Test-Skript für das Transkript-Trigger-System
Simuliert das Hinzufügen eines neuen Transkripts und testet das Monitoring
"""
import os
import sys
import json
import time
import shutil
import pathlib
import logging
from datetime import datetime

def setup_logging():
    """Konfiguriert das Logging für Tests."""
    logging.basicConfig(
        level=logging.DEBUG,
        format='%(asctime)s - %(levelname)s - %(message)s',
        handlers=[
            logging.StreamHandler(sys.stdout),
            logging.FileHandler('test_trigger.log', encoding='utf-8')
        ]
    )
    return logging.getLogger('TriggerTest')

def analyze_current_state(logger):
    """Analysiert den aktuellen Zustand des Systems."""
    logger.info("🔍 Analysiere aktuellen Zustand...")
    
    transkript_dir = pathlib.Path("web/transkripte")
    tracking_file = transkript_dir / "transkript_tracking.json"
    
    # 1. Dateien im Verzeichnis
    actual_files = list(transkript_dir.glob("*_transkript.txt"))
    logger.info(f"📄 Dateien im Verzeichnis: {len(actual_files)}")
    for f in actual_files:
        logger.info(f"  - {f.name} ({f.stat().st_size} bytes)")
    
    # 2. Tracking-JSON Status
    if tracking_file.exists():
        with open(tracking_file, 'r', encoding='utf-8') as f:
            tracking_data = json.load(f)
        
        tracked_files = tracking_data.get('transcripts', {})
        logger.info(f"📊 Dateien im Tracking: {len(tracked_files)}")
        for filename, info in tracked_files.items():
            logger.info(f"  - {filename}: {info.get('status', 'unknown')}")
        
        # Problem identifizieren
        actual_names = {f.name for f in actual_files}
        tracked_names = set(tracked_files.keys())
        
        missing_in_tracking = actual_names - tracked_names
        missing_in_filesystem = tracked_names - actual_names
        
        if missing_in_tracking:
            logger.warning(f"⚠️ PROBLEM: {len(missing_in_tracking)} Dateien nicht im Tracking:")
            for name in missing_in_tracking:
                logger.warning(f"    ❌ {name}")
        
        if missing_in_filesystem:
            logger.warning(f"⚠️ {len(missing_in_filesystem)} Dateien im Tracking aber nicht im Dateisystem:")
            for name in missing_in_filesystem:
                logger.warning(f"    ❌ {name}")
        
        return tracking_data, actual_files, missing_in_tracking
    else:
        logger.error(f"❌ Tracking-Datei nicht gefunden: {tracking_file}")
        return None, actual_files, set()

def create_test_transcript(logger):
    """Erstellt ein Test-Transkript."""
    logger.info("🧪 Erstelle Test-Transkript...")
    
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    test_filename = f"scene_{timestamp}_test_transkript.txt"
    test_path = pathlib.Path("web/transkripte") / test_filename
    
    test_content = f"""# Scene Test Transkript - {timestamp}

## SZENEN-METADATEN
- **Scene Name**: test_scene_{timestamp}
- **Datum**: {datetime.now().strftime("%Y-%m-%d")}
- **Zeit**: {datetime.now().strftime("%H:%M:%S")}
- **Spieler**: TestSpieler1, TestSpieler2
- **Spielleiter**: TestGM

## ZEITGESTEMPELTE SEGMENTE

### [00:00 - 02:30] - Einstieg in die Szene
**GM**: Ihr betretet eine dunkle Höhle. Das Licht eurer Fackeln wirft tanzende Schatten an die Wände.

**TestSpieler1**: Ich schaue mich vorsichtig um und suche nach Fallen.

**GM**: Du siehst seltsame Runen an den Wänden, die schwach blau glimmen.

### [02:30 - 05:00] - Entdeckung des Geheimnisses
**TestSpieler2**: Was bedeuten diese Runen? Kann ich sie entziffern?

**GM**: Mit deinem Wissen über Arkane Künste erkennst du, dass es sich um Schutzrunen handelt.

**TestSpieler1**: Das gefällt mir nicht. Wir sollten vorsichtig sein.

### [05:00 - 07:15] - Dramatischer Moment
**GM**: Plötzlich beginnen die Runen heller zu leuchten! Der Boden unter euren Füßen beginnt zu beben!

**TestSpieler2**: Ich versuche einen Zauber zu wirken, um uns zu schützen!

**TestSpieler1**: Ich springe zur Seite und suche Deckung!

**GM**: Ein mysteriöser Kristall erhebt sich aus dem Boden der Höhle...
"""
    
    with open(test_path, 'w', encoding='utf-8') as f:
        f.write(test_content)
    
    logger.info(f"✅ Test-Transkript erstellt: {test_filename}")
    logger.info(f"📄 Pfad: {test_path}")
    logger.info(f"📊 Größe: {test_path.stat().st_size} bytes")
    
    return test_path

def test_monitoring_system(logger, test_file_path):
    """Testet das Monitoring-System."""
    logger.info("🔄 Teste Monitoring-System...")
    
    # Simuliere _sync_tracking_with_filesystem Logik
    tracking_file = pathlib.Path("web/transkripte/transkript_tracking.json")
    transkript_dir = pathlib.Path("web/transkripte")
    
    # Lade aktuelles Tracking
    if tracking_file.exists():
        with open(tracking_file, 'r', encoding='utf-8') as f:
            tracking_data = json.load(f)
    else:
        tracking_data = {
            "last_updated": datetime.now().isoformat(),
            "transcripts": {},
            "status": "initialized"
        }
    
    logger.info(f"📊 Tracking vor Test: {len(tracking_data['transcripts'])} Dateien")
    
    # Scanne alle Dateien (wie im echten System)
    current_files = {}
    for file_path in transkript_dir.glob("*_transkript.txt"):
        import hashlib
        with open(file_path, 'rb') as f:
            file_hash = hashlib.md5(f.read()).hexdigest()
        
        file_info = {
            "filename": file_path.name,
            "size": file_path.stat().st_size,
            "modified": datetime.fromtimestamp(file_path.stat().st_mtime).isoformat(),
            "hash": file_hash,
            "status": "detected"
        }
        current_files[file_path.name] = file_info
    
    logger.info(f"📄 Dateisystem-Scan: {len(current_files)} Dateien gefunden")
    
    # Prüfe auf neue Dateien
    new_files = []
    updated = False
    
    for filename, file_info in current_files.items():
        if filename not in tracking_data["transcripts"]:
            # Neue Datei gefunden
            file_info["status"] = "new"
            tracking_data["transcripts"][filename] = file_info
            new_files.append(filename)
            updated = True
            logger.info(f"🆕 Neue Datei erkannt: {filename}")
        elif tracking_data["transcripts"][filename]["hash"] != file_info["hash"]:
            # Datei geändert
            tracking_data["transcripts"][filename] = file_info
            tracking_data["transcripts"][filename]["status"] = "modified"
            updated = True
            logger.info(f"📝 Datei geändert: {filename}")
    
    # Speichere Updates
    if updated:
        tracking_data["last_updated"] = datetime.now().isoformat()
        tracking_data["status"] = "active"
        with open(tracking_file, 'w', encoding='utf-8') as f:
            json.dump(tracking_data, f, indent=2, ensure_ascii=False)
        logger.info("💾 Tracking-Daten aktualisiert")
    
    return new_files, updated

def simulate_file_events(logger, test_file_path):
    """Simuliert Watchdog File Events."""
    logger.info("👁️ Simuliere Watchdog File Events...")
    
    # Importiere die Event-Handler Klasse
    try:
        sys.path.append('.')
        from scene_visualizer_runner import TranscriptEventHandler
        
        class MockRunner:
            def __init__(self):
                self.logger = logger
            
            def process_new_transcript(self, transcript_path):
                self.logger.info(f"🎭 WÜRDE VERARBEITEN: {transcript_path}")
                return True
        
        # Erstelle Mock Event
        class MockEvent:
            def __init__(self, src_path):
                self.src_path = src_path
                self.is_directory = False
        
        # Teste Event Handler
        mock_runner = MockRunner()
        handler = TranscriptEventHandler(mock_runner)
        
        event = MockEvent(str(test_file_path))
        logger.info(f"🔔 Simuliere on_created Event für: {test_file_path.name}")
        handler.on_created(event)
        
        return True
        
    except ImportError as e:
        logger.error(f"❌ Kann Event Handler nicht importieren: {e}")
        return False

def cleanup_test_file(logger, test_file_path):
    """Entfernt die Test-Datei."""
    try:
        if test_file_path.exists():
            test_file_path.unlink()
            logger.info(f"🗑️ Test-Datei entfernt: {test_file_path.name}")
    except Exception as e:
        logger.error(f"❌ Fehler beim Entfernen der Test-Datei: {e}")

def main():
    """Hauptfunktion für den Test."""
    logger = setup_logging()
    logger.info("🚀 Starte Transkript-Trigger-Test...")
    
    try:
        # 1. Aktuellen Zustand analysieren
        tracking_data, actual_files, missing_files = analyze_current_state(logger)
        
        if missing_files:
            logger.error(f"❌ HAUPTPROBLEM IDENTIFIZIERT: {len(missing_files)} Dateien nicht im Tracking!")
            logger.error("   Das System hat nur einen Teil der Dateien erfasst.")
        
        # 2. Test-Transkript erstellen
        test_file = create_test_transcript(logger)
        
        # 3. Warte kurz
        logger.info("⏳ Warte 2 Sekunden...")
        time.sleep(2)
        
        # 4. Teste JSON-Monitoring
        new_files, was_updated = test_monitoring_system(logger, test_file)
        
        if new_files:
            logger.info(f"✅ JSON-Monitoring funktioniert! {len(new_files)} neue Dateien erkannt:")
            for f in new_files:
                logger.info(f"   - {f}")
        else:
            logger.error("❌ JSON-Monitoring hat neue Datei NICHT erkannt!")
        
        # 5. Teste Watchdog Events
        event_success = simulate_file_events(logger, test_file)
        
        if event_success:
            logger.info("✅ Watchdog Event-Simulation erfolgreich")
        else:
            logger.error("❌ Watchdog Event-Simulation fehlgeschlagen")
        
        # 6. Finale Diagnose
        logger.info("\n" + "="*60)
        logger.info("🔍 DIAGNOSE-ZUSAMMENFASSUNG:")
        logger.info("="*60)
        
        if missing_files:
            logger.error(f"❌ HAUPTPROBLEM: {len(missing_files)} existierende Dateien nicht im Tracking")
            logger.error("   → Das System startet nicht mit allen vorhandenen Dateien")
        
        if not was_updated:
            logger.error("❌ JSON-Monitoring erkennt neue Dateien nicht")
        
        if not event_success:
            logger.error("❌ Watchdog Events funktionieren nicht")
        
        if was_updated and event_success and not missing_files:
            logger.info("✅ Trigger-System funktioniert korrekt!")
        
    except Exception as e:
        logger.error(f"❌ Test-Fehler: {e}")
        import traceback
        logger.error(traceback.format_exc())
    
    finally:
        # Cleanup
        if 'test_file' in locals():
            cleanup_test_file(logger, test_file)
    
    logger.info("🏁 Test beendet")

if __name__ == "__main__":
    main() 