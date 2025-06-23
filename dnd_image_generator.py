#!/usr/bin/env python3
"""
D&D Bildgenerator - Erstellt Bildgenerierungs-Prompts basierend auf D&D-Session-Transkripten.
"""
import ollama
import parse_transkript
import img_gen
import re
import sys
import logging
import pathlib
import json
import socket
from datetime import datetime

def get_required_model():
    """Lädt das erforderliche Modell aus der Konfiguration."""
    try:
        with open('run_config.json', 'r') as f:
            config = json.load(f)
        return config['services']['ollama']['required_model']
    except Exception:
        return "deepseek-r1:14b"  # Fallback

def create_system_prompt():
    """Erstellt den System-Prompt für das LLM."""
    return """You are an expert Dungeons & Dragons scene analyst and image prompt generator specialized for the "dndstyle" LoRA model.

Your task is to:
1. Analyze the provided D&D session transcript excerpt
2. Identify the current situation, location, characters, and atmosphere
3. Generate a detailed image generation prompt optimized for the "dndstyle" model

CRITICAL OUTPUT FORMAT:
You MUST format your response EXACTLY as follows (after any thinking):

SCENE ANALYSIS: [Brief description of what's happening]

DNDSTYLE IMAGE PROMPT: dndstyle, [your detailed prompt here]

IMAGE NAME: [descriptive filename without extension, use underscores instead of spaces]

IMAGE PROMPT REQUIREMENTS:
- MUST start with "dndstyle" as the trigger word
- Be optimized for a LoRA model trained on D&D illustrations
- Capture key visual elements (characters, environment, objects, lighting)
- Focus on the most dramatic or visually interesting moment
- Include specific D&D fantasy elements (races, classes, equipment, creatures)
- Include atmospheric details (mood, lighting, weather, dungeon ambiance)
- Be concise but descriptive (avoid overly long prompts)
- Use D&D-specific terminology and visual style descriptions

IMAGE NAME REQUIREMENTS:
- ONLY use ASCII letters (a-z, A-Z), numbers (0-9), and underscores (_)
- NO special characters, spaces, accents, or non-English characters
- Maximum 50 characters long
- Use descriptive English words separated by underscores
- Examples: "party_discovers_artifact", "dragon_combat_dungeon", "ancient_chamber_frescoes"

EXAMPLE OUTPUT:
SCENE ANALYSIS: The party discovers a hidden chamber with ancient frescoes depicting dragons and knights. A mysterious artifact glows brighter as it's placed on an ornate altar.

DNDSTYLE IMAGE PROMPT: dndstyle, fantasy adventurers in ancient stone chamber, ornate altar with glowing artifact, dragon and knight frescoes on walls, torchlight atmosphere, dramatic lighting, D&D illustration style

IMAGE NAME: party_discovers_artifact_chamber

Remember: The output format is CRITICAL. Always include all three sections exactly as shown. The IMAGE NAME must be valid ASCII-only filename."""

def setup_logging():
    """Konfiguriert Logging für Debug-Ausgaben mit besserer Sichtbarkeit."""
    # Console Handler mit einfachem Format (ohne Farben für Kompatibilität)
    console_handler = logging.StreamHandler(sys.stdout)
    console_handler.setLevel(logging.INFO)
    console_formatter = logging.Formatter(
        '\033[94m[DnD-IMG]\033[0m %(asctime)s - %(levelname)s - %(message)s'
    )
    console_handler.setFormatter(console_formatter)
    
    # File Handler mit detaillierten Infos
    file_handler = logging.FileHandler('dnd_image_generator.log', encoding='utf-8')
    file_handler.setLevel(logging.DEBUG)
    file_formatter = logging.Formatter(
        '%(asctime)s - %(name)s - %(levelname)s - %(filename)s:%(lineno)d - %(message)s'
    )
    file_handler.setFormatter(file_formatter)
    
    # Logger konfigurieren
    logger = logging.getLogger('DnDImageGenerator')
    logger.setLevel(logging.DEBUG)
    logger.addHandler(console_handler)
    logger.addHandler(file_handler)
    
    return logger

def check_service_availability():
    """Prüft die Verfügbarkeit aller benötigten Services."""
    logger = logging.getLogger('DnDImageGenerator')
    
    # Ollama Service prüfen
    try:
        logger.info("🔍 Prüfe Ollama Service...")
        response = ollama.list()
        models = [model['name'] for model in response.get('models', [])]
        logger.info(f"Verfügbare Modelle: {models}")
        
        required_model = get_required_model()
        logger.debug(f"Erforderliches Modell gefunden: {required_model}")
        
        if required_model in models:
            logger.info(f"✅ {required_model} Modell verfügbar")
        else:
            logger.warning(f"⚠️ {required_model} Modell nicht gefunden")
            return False
    except Exception as e:
        logger.error(f"❌ Ollama Service nicht verfügbar: {e}")
        return False
    
    # Image Generation Service prüfen
    try:
        logger.info("🔍 Prüfe Image Generation Service...")
        config_path = pathlib.Path("img_gen_service.json")
        
        if not config_path.exists():
            logger.error("❌ img_gen_service.json nicht gefunden")
            return False
        
        with open(config_path, 'r') as f:
            config = json.load(f)
        
        host = config.get('host', 'localhost')
        port = config.get('port', 5555)
        
        # Socket-Test
        sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        sock.settimeout(5)
        result = sock.connect_ex((host, port))
        sock.close()
        
        if result == 0:
            logger.info(f"✅ Image Service erreichbar auf {host}:{port}")
            return True
        else:
            logger.error(f"❌ Image Service nicht erreichbar auf {host}:{port}")
            return False
            
    except Exception as e:
        logger.error(f"❌ Fehler beim Prüfen des Image Service: {e}")
        return False

def analyze_transcript_and_generate_prompt(transcript_text):
    """
    Analysiert das Transkript und generiert einen Bildgenerierungs-Prompt.
    
    Args:
        transcript_text (list): Liste der Transkript-Zeilen
        
    Returns:
        str: Der generierte Bildgenerierungs-Prompt
    """
    logger = logging.getLogger('DnDImageGenerator')
    logger.info("🧠 Starte LLM-Analyse...")
    
    # System-Prompt erstellen
    system_prompt = create_system_prompt()
    
    # Transkript-Text vorbereiten
    transcript_content = "\n".join(transcript_text)
    logger.debug(f"Transkript-Inhalt ({len(transcript_text)} Zeilen):\n{transcript_content[:200]}...")
    
    # User-Prompt erstellen
    user_prompt = f"""Here is a D&D session transcript excerpt from the last 5 minutes:

{transcript_content}

Please analyze this transcript and generate an appropriate image generation prompt for the current scene."""
    
    # Vollständigen Prompt zusammenstellen
    full_prompt = f"{system_prompt}\n\n{user_prompt}"
    logger.debug(f"Vollständiger Prompt-Länge: {len(full_prompt)} Zeichen")
    
    # Ollama abfragen mit Retry-Logik
    max_retries = 3
    retry_delay = 5
    
    for attempt in range(max_retries):
        try:
            logger.info(f"🤖 Ollama Abfrage (Versuch {attempt + 1}/{max_retries})...")
            start_time = datetime.now()
            
            model_name = get_required_model()
            
            # Verwende richtige Ollama API
            try:
                response = ollama.chat(
                    model=model_name,
                    messages=[{'role': 'user', 'content': full_prompt}],
                    options={
                        'temperature': 0.7,
                        'top_p': 0.9,
                        'num_predict': 1500,
                        'num_ctx': 4096
                    }
                )
            except AttributeError:
                # Fallback für ältere ollama API
                try:
                    response = ollama.generate(
                        model=model_name, 
                        prompt=full_prompt,
                        options={
                            'temperature': 0.7,
                            'top_p': 0.9,
                            'num_predict': 1500,
                            'num_ctx': 4096
                        }
                    )
                except AttributeError:
                    # Letzte Option: Client verwenden
                    client = ollama.Client()
                    response = client.generate(
                        model=model_name, 
                        prompt=full_prompt,
                        options={
                            'temperature': 0.7,
                            'top_p': 0.9,
                            'num_predict': 1500,
                            'num_ctx': 4096
                        }
                    )
            
            end_time = datetime.now()
            duration = (end_time - start_time).total_seconds()
            logger.info(f"🤖 LLM-Analyse abgeschlossen nach {duration:.1f}s")
            
            # Extrahiere Antwort je nach API-Format
            response_text = None
            
            if response:
                if 'message' in response and 'content' in response['message']:
                    # Neue chat API
                    response_text = response['message']['content']
                elif 'response' in response:
                    # Alte generate API
                    response_text = response['response']
                
            if response_text:
                logger.info(f"✅ LLM-Antwort erhalten nach {duration:.1f}s")
                logger.debug(f"Antwort-Länge: {len(response_text)} Zeichen")
                return response_text
            else:
                logger.warning(f"⚠️ Leere oder ungültige Antwort von Ollama")
                logger.debug(f"Response-Struktur: {response.keys() if response else 'None'}")
                
        except Exception as e:
            logger.error(f"❌ Ollama-Abfrage fehlgeschlagen (Versuch {attempt + 1}): {e}")
            if attempt < max_retries - 1:
                logger.info(f"⏳ Warte {retry_delay}s vor nächstem Versuch...")
                import time
                time.sleep(retry_delay)
            else:
                return f"Fehler bei der Ollama-Abfrage nach {max_retries} Versuchen: {e}"
    
    return "Fehler: Alle Ollama-Abfrage-Versuche fehlgeschlagen"

def parse_llm_response(response_text):
    """
    Parst die LLM-Antwort und extrahiert Prompt und Bildname.
    Unterstützt DeepSeek-R1 Format mit <think> Tags.
    
    Args:
        response_text (str): Die Antwort vom LLM
        
    Returns:
        tuple: (image_prompt, image_name) oder (None, None) bei Fehlern
    """
    logger = logging.getLogger('DnDImageGenerator')
    logger.info("🔍 Parse LLM-Antwort...")
    
    try:
        logger.debug(f"📝 LLM-Antwort (erste 200 Zeichen): {response_text[:200]}")
        
        # Für DeepSeek-R1: Entferne <think> Abschnitte falls vorhanden
        clean_response = response_text
        if '<think>' in response_text and '</think>' in response_text:
            # Extrahiere alles nach dem </think> Tag
            after_think = response_text.split('</think>')
            if len(after_think) > 1:
                clean_response = after_think[1].strip()
                logger.debug(f"🧠 <think> Abschnitt entfernt, verarbeite: {clean_response[:100]}...")
        
        # DNDSTYLE IMAGE PROMPT extrahieren (mehrere Pattern probieren)
        prompt_patterns = [
            r'DNDSTYLE IMAGE PROMPT:\s*(.+?)(?=\nIMAGE NAME:|$)',
            r'IMAGE PROMPT:\s*(.+?)(?=\nIMAGE NAME:|$)', 
            r'PROMPT:\s*(.+?)(?=\nIMAGE NAME:|$)',
            r'dndstyle[,\s]+(.+?)(?=\nIMAGE NAME:|$)'
        ]
        
        # IMAGE NAME extrahieren
        name_patterns = [
            r'IMAGE NAME:\s*(.+?)(?=\n|$)',
            r'NAME:\s*(.+?)(?=\n|$)',
            r'FILENAME:\s*(.+?)(?=\n|$)'
        ]
        
        image_prompt = None
        image_name = None
        
        # Prompt Pattern suchen
        for pattern in prompt_patterns:
            match = re.search(pattern, clean_response, re.IGNORECASE | re.DOTALL)
            if match:
                image_prompt = match.group(1).strip()
                # Entferne LLM-Formatierung wie ** am Anfang
                image_prompt = re.sub(r'^\*+\s*', '', image_prompt)
                logger.debug(f"✅ Prompt gefunden mit Pattern: {pattern}")
                break
        
        # Name Pattern suchen 
        for pattern in name_patterns:
            match = re.search(pattern, clean_response, re.IGNORECASE)
            if match:
                image_name = match.group(1).strip()
                logger.debug(f"✅ Name gefunden mit Pattern: {pattern}")
                break
        
        # Fallback: Wenn strukturierte Antwort nicht gefunden wird
        if not image_prompt or not image_name:
            logger.warning("⚠️ Strukturierte Antwort nicht gefunden, verwende Fallback-Parsing...")
            
            # Suche nach "dndstyle" im Text
            dndstyle_match = re.search(r'(dndstyle[^.!?\n]+)', clean_response, re.IGNORECASE)
            if dndstyle_match:
                image_prompt = dndstyle_match.group(1).strip()
                image_name = "generated_scene"
                logger.info(f"🔧 Fallback-Prompt extrahiert: {image_prompt}")
            else:
                # Als letzter Ausweg: Erstelle grundlegenden Prompt
                image_prompt = "dndstyle fantasy adventure scene, dungeons and dragons style illustration"
                image_name = "fallback_scene"
                logger.warning(f"🆘 Fallback auf Basis-Prompt: {image_prompt}")
        
        if image_prompt and image_name:
            logger.info(f"✅ Extrahiert - Bildname (roh): '{image_name}'")
            logger.info(f"✅ Extrahiert - Prompt: '{image_prompt[:100]}...'")
            
            # Erweiterte Bildname-Bereinigung
            original_name = image_name
            
            # Entferne LLM-Formatierung wie **, führende/trailing Sterne, etc.
            clean_image_name = re.sub(r'^\*+\s*|\s*\*+$', '', image_name)
            
            # Entferne alles in Klammern (wie "(Secret Chamber)")
            clean_image_name = re.sub(r'\s*\([^)]*\)', '', clean_image_name)
            
            # Entferne alle Nicht-ASCII-Zeichen und ersetze sie durch Unterstriche
            clean_image_name = re.sub(r'[^\x00-\x7F]', '_', clean_image_name)
            
            # Erlaube nur alphanumerische Zeichen und Unterstriche
            clean_image_name = re.sub(r'[^a-zA-Z0-9_]', '_', clean_image_name)
            
            # Entferne mehrfache Unterstriche
            clean_image_name = re.sub(r'_{2,}', '_', clean_image_name)
            
            # Entferne führende/trailing Unterstriche
            clean_image_name = clean_image_name.strip('_')
            
            # Falls Name leer oder zu kurz, verwende Fallback
            if len(clean_image_name) < 3:
                clean_image_name = "generated_scene"
                logger.warning(f"⚠️ Bildname war unbrauchbar, verwende Fallback: '{clean_image_name}'")
            
            # Begrenze Länge auf 35 Zeichen (um Platz für Timestamp zu lassen)
            if len(clean_image_name) > 35:
                clean_image_name = clean_image_name[:35].rstrip('_')
            
            # Füge Minutentimestamp hinzu
            from datetime import datetime
            minute_timestamp = datetime.now().strftime("%H%M")
            timestamped_name = f"{minute_timestamp}_{clean_image_name}"
            
            if timestamped_name != original_name:
                logger.info(f"🧹 Bildname bereinigt: '{original_name}' → '{timestamped_name}'")
            
            return image_prompt, timestamped_name
        else:
            logger.error("❌ Konnte Prompt oder Bildname nicht aus LLM-Antwort extrahieren")
            logger.debug(f"🐛 Vollständige LLM-Antwort:\n{response_text}")
            return None, None
            
    except Exception as e:
        logger.error(f"❌ Fehler beim Parsen der LLM-Antwort: {e}")
        logger.debug(f"🐛 Vollständige LLM-Antwort:\n{response_text}")
        return None, None

def generate_image_from_prompt(image_prompt, image_name):
    """
    Generiert ein Bild basierend auf dem Prompt und Bildnamen.
    
    Args:
        image_prompt (str): Der Bildgenerierungs-Prompt
        image_name (str): Der gewünschte Bildname
        
    Returns:
        dict: Ergebnis der Bildgenerierung oder None bei Fehlern
    """
    logger = logging.getLogger('DnDImageGenerator')
    logger.info("🎨 Starte Bildgenerierung...")
    
    try:
        # PNG-Extension hinzufügen
        if not image_name.endswith('.png'):
            image_name += '.png'
        
        logger.info(f"📁 Ziel-Datei: {image_name}")
        logger.info(f"🎭 Prompt: {image_prompt}")
        
        # Prüfe Image Service vor Generierung
        if not check_image_service_connectivity():
            logger.error("❌ Image Service nicht verfügbar - überspringe Bildgenerierung")
            return None
        
        start_time = datetime.now()
        logger.info("🚀 Sende Anfrage an Image Generation Service...")
        
        result = img_gen.generate_img(image_prompt, image_name)
        
        end_time = datetime.now()
        duration = (end_time - start_time).total_seconds()
        
        if result:
            logger.info(f"✅ Bildgenerierung erfolgreich nach {duration:.1f}s")
            logger.info(f"📊 Ergebnis: {result}")
            return result
        else:
            logger.error(f"❌ Bildgenerierung fehlgeschlagen nach {duration:.1f}s")
            return None
        
    except Exception as e:
        logger.error(f"❌ Fehler bei der Bildgenerierung: {e}")
        return None

def check_image_service_connectivity():
    """Schnelle Konnektivitätsprüfung für Image Service."""
    try:
        config_path = pathlib.Path("img_gen_service.json")
        if not config_path.exists():
            return False
        
        with open(config_path, 'r') as f:
            config = json.load(f)
        
        host = config.get('host', 'localhost')
        port = config.get('port', 5555)
        
        sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        sock.settimeout(2)
        result = sock.connect_ex((host, port))
        sock.close()
        
        return result == 0
    except:
        return False

def main():
    """Hauptfunktion des Scripts."""
    # Logging konfigurieren
    logger = setup_logging()
    
    logger.info("🎲 === D&D Bildgenerator gestartet ===")
    
    try:
        # Service-Verfügbarkeit prüfen
        logger.info("🔧 Prüfe Service-Verfügbarkeit...")
        if not check_service_availability():
            logger.error("❌ Nicht alle Services verfügbar - Script beendet")
            return False
        
        # Transkript laden
        logger.info("📖 Lade Transkript...")
        try:
            parser = parse_transkript.TranskriptParser("transcript.txt")
            letzte_5_min = parser.get_transkript(5)
        except Exception as e:
            logger.error(f"❌ Fehler beim Laden des Transkripts: {e}")
            return False
        
        if not letzte_5_min:
            logger.warning("⚠️ Keine Transkript-Daten in den letzten 5 Minuten gefunden")
            return False
        
        logger.info(f"✅ Gefunden: {len(letzte_5_min)} Einträge aus den letzten 5 Minuten")
        
        # Transkript-Inhalt loggen (gekürzt)
        logger.debug("📄 Transkript-Inhalt:")
        for i, eintrag in enumerate(letzte_5_min[:3]):  # Nur erste 3 zeigen
            logger.debug(f"  {i+1}: {eintrag}")
        if len(letzte_5_min) > 3:
            logger.debug(f"  ... und {len(letzte_5_min) - 3} weitere Einträge")
        
        # LLM-Analyse
        logger.info("🧠 Starte LLM-Analyse...")
        generated_prompt = analyze_transcript_and_generate_prompt(letzte_5_min)
        
        if generated_prompt.startswith("Fehler"):
            logger.error(f"❌ LLM-Analyse fehlgeschlagen: {generated_prompt}")
            return False
        
        logger.info("✅ LLM-Analyse erfolgreich")
        logger.debug(f"📝 Generierte Antwort (erste 200 Zeichen):\n{generated_prompt[:200]}...")
        
        # Parsing
        image_prompt, image_name = parse_llm_response(generated_prompt)
        
        if image_prompt and image_name:
            logger.info("✅ Prompt und Bildname erfolgreich extrahiert")
            
            # Bildgenerierung
            result = generate_image_from_prompt(image_prompt, image_name)
            
            if result:
                logger.info("🎉 Bildgenerierung komplett erfolgreich!")
                logger.info(f"📁 Generiertes Bild verfügbar")
                return True
            else:
                logger.error("❌ Bildgenerierung fehlgeschlagen")
                return False
        else:
            logger.error("❌ Konnte Prompt oder Bildname nicht extrahieren")
            logger.debug(f"📝 Vollständige LLM-Antwort:\n{generated_prompt}")
            return False
        
    except KeyboardInterrupt:
        logger.info("⚠️ Script durch Benutzer unterbrochen")
        return False
    except Exception as e:
        logger.error(f"❌ Unerwarteter Fehler: {e}", exc_info=True)
        return False
    finally:
        logger.info("🔻 D&D Bildgenerator beendet")

if __name__ == "__main__":
    success = main()
    sys.exit(0 if success else 1)
    main() 