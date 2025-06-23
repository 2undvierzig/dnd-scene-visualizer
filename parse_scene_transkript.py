#!/usr/bin/env python3
"""
Parser für Scene-Transkripte im neuen Format.
Extrahiert nur die zeitgestempelten Segmente für die Weiterverarbeitung.
"""
import re
import pathlib
from datetime import datetime
from typing import List, Dict, Optional, Tuple

class SceneTranskriptParser:
    """Parser für Scene-Transkripte mit Zeitstempeln."""
    
    def __init__(self, transkript_datei: str):
        """
        Initialisiert den Parser mit einer Scene-Transkript-Datei.
        
        Args:
            transkript_datei (str): Pfad zur Transkript-Datei
        """
        self.transkript_datei = pathlib.Path(transkript_datei)
        self.metadata = {}
        self.volltext = ""
        self.zeitgestempelte_segmente = []
        self._parse_transkript()
    
    def _parse_transkript(self):
        """Parst das Transkript und extrahiert Metadaten und Segmente."""
        if not self.transkript_datei.exists():
            raise FileNotFoundError(f"Transkript-Datei {self.transkript_datei} nicht gefunden.")
        
        inhalt = self.transkript_datei.read_text(encoding='utf-8')
        zeilen = inhalt.strip().split('\n')
        
        # Parse Metadaten
        for zeile in zeilen[:10]:  # Erste Zeilen für Metadaten
            if zeile.startswith("Transkript für:"):
                self.metadata['audio_file'] = zeile.split(': ', 1)[1]
            elif zeile.startswith("Datum:"):
                self.metadata['datum'] = zeile.split(': ', 1)[1]
            elif zeile.startswith("Sprache:"):
                self.metadata['sprache'] = zeile.split(': ', 1)[1]
            elif zeile.startswith("Konfidenz:"):
                self.metadata['konfidenz'] = zeile.split(': ', 1)[1]
            elif zeile.startswith("Dauer:"):
                self.metadata['dauer'] = zeile.split(': ', 1)[1]
        
        # Extrahiere Volltext
        volltext_start = False
        zeitstempel_start = False
        
        for i, zeile in enumerate(zeilen):
            if zeile.strip() == "VOLLTEXT:":
                volltext_start = True
                continue
            elif zeile.strip() == "ZEITGESTEMPELTE SEGMENTE:":
                volltext_start = False
                zeitstempel_start = True
                continue
            elif zeile.startswith("====="):
                continue
            
            if volltext_start and zeile.strip():
                self.volltext = zeile.strip()
            
            if zeitstempel_start and zeile.strip():
                # Parse Zeitstempel-Segmente im Format [MM:SS.ss - MM:SS.ss] Text
                segment_match = re.match(r'\[(\d{2}:\d{2}\.\d{2}) - (\d{2}:\d{2}\.\d{2})\] (.+)', zeile)
                if segment_match:
                    start_zeit, ende_zeit, text = segment_match.groups()
                    self.zeitgestempelte_segmente.append({
                        'start': start_zeit,
                        'ende': ende_zeit,
                        'text': text.strip()
                    })
    
    def get_zeitgestempelte_segmente(self) -> List[Dict[str, str]]:
        """
        Gibt die zeitgestempelten Segmente zurück.
        
        Returns:
            List[Dict[str, str]]: Liste von Segmenten mit start, ende und text
        """
        return self.zeitgestempelte_segmente
    
    def get_segmente_als_text(self) -> str:
        """
        Gibt alle zeitgestempelten Segmente als zusammenhängenden Text zurück.
        
        Returns:
            str: Alle Segmente als Text, mit Zeitstempeln
        """
        text_parts = []
        for segment in self.zeitgestempelte_segmente:
            text_parts.append(f"[{segment['start']} - {segment['ende']}] {segment['text']}")
        return "\n".join(text_parts)
    
    def get_nur_text(self) -> str:
        """
        Gibt nur den Text der Segmente ohne Zeitstempel zurück.
        
        Returns:
            str: Nur der reine Text aller Segmente
        """
        return " ".join([segment['text'] for segment in self.zeitgestempelte_segmente])
    
    def get_metadata(self) -> Dict[str, str]:
        """
        Gibt die Metadaten des Transkripts zurück.
        
        Returns:
            Dict[str, str]: Metadaten wie Datum, Sprache, etc.
        """
        return self.metadata
    
    def get_scene_name(self) -> str:
        """
        Extrahiert den Scene-Namen aus dem Dateinamen.
        
        Returns:
            str: Scene-Name (z.B. "scene_20250620_sz001")
        """
        # Entferne "_transkript.txt" vom Dateinamen
        name = self.transkript_datei.stem
        if name.endswith("_transkript"):
            name = name[:-11]  # Entferne "_transkript"
        return name

# Convenience-Funktionen
def parse_scene_transkript(transkript_datei: str) -> Dict[str, any]:
    """
    Convenience-Funktion zum Parsen eines Scene-Transkripts.
    
    Args:
        transkript_datei (str): Pfad zur Transkript-Datei
        
    Returns:
        Dict: Dictionary mit allen geparsten Daten
    """
    parser = SceneTranskriptParser(transkript_datei)
    return {
        'metadata': parser.get_metadata(),
        'scene_name': parser.get_scene_name(),
        'volltext': parser.volltext,
        'segmente': parser.get_zeitgestempelte_segmente(),
        'segmente_text': parser.get_segmente_als_text(),
        'nur_text': parser.get_nur_text()
    }

def get_latest_transkript(transkript_dir: str = "web/transkripte") -> Optional[pathlib.Path]:
    """
    Findet das neueste Transkript im angegebenen Verzeichnis.
    
    Args:
        transkript_dir (str): Pfad zum Transkript-Verzeichnis
        
    Returns:
        Optional[pathlib.Path]: Pfad zum neuesten Transkript oder None
    """
    transkript_path = pathlib.Path(transkript_dir)
    if not transkript_path.exists():
        return None
    
    # Finde alle Transkript-Dateien
    transkripte = list(transkript_path.glob("*_transkript.txt"))
    
    if not transkripte:
        return None
    
    # Sortiere nach Änderungszeit (neueste zuerst)
    transkripte.sort(key=lambda x: x.stat().st_mtime, reverse=True)
    
    return transkripte[0]

def main():
    """Test-Funktion für das Modul."""
    # Teste mit der Beispieldatei
    test_file = "web/transkripte/scene_20250620_sz001_transkript.txt"
    
    try:
        parser = SceneTranskriptParser(test_file)
        
        print("=== METADATEN ===")
        for key, value in parser.get_metadata().items():
            print(f"{key}: {value}")
        
        print(f"\nScene-Name: {parser.get_scene_name()}")
        
        print("\n=== ZEITGESTEMPELTE SEGMENTE ===")
        for segment in parser.get_zeitgestempelte_segmente():
            print(f"[{segment['start']} - {segment['ende']}] {segment['text']}")
        
        print("\n=== NUR TEXT ===")
        print(parser.get_nur_text())
        
    except Exception as e:
        print(f"Fehler: {e}")

if __name__ == "__main__":
    main() 