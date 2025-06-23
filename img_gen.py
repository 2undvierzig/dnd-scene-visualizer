#!/usr/bin/env python3
"""
Ein einfaches Python-Modul zum Generieren von Bildern über einen Socket-Service.
"""
import json
import socket
import pathlib
import sys
import time

# Konfigurationspfad
CFG_PATH = pathlib.Path("img_gen_service.json")

def log_debug(msg):
    """Debug logging mit Timestamp."""
    timestamp = time.strftime("%Y-%m-%d %H:%M:%S")
    print(f"[{timestamp}] [IMG_CLIENT] {msg}", file=sys.stderr, flush=True)

def _load_config():
    """Lädt die Konfiguration aus der JSON-Datei."""
    try:
        config = json.loads(CFG_PATH.read_text())
        log_debug(f"Config loaded: {config}")
        return config
    except FileNotFoundError:
        log_debug(f"ERROR: Config file not found: {CFG_PATH}")
        raise FileNotFoundError(f"Konfigurationsdatei {CFG_PATH} nicht gefunden.")
    except json.JSONDecodeError as e:
        log_debug(f"ERROR: Invalid JSON in config: {e}")
        raise ValueError(f"Ungültiges JSON in {CFG_PATH}.")

def generate_img(prompt, img_name):
    """
    Generiert ein Bild basierend auf dem gegebenen Prompt.
    
    Args:
        prompt (str): Der Text-Prompt für die Bildgenerierung
        img_name (str): Der gewünschte Dateiname für das generierte Bild
        
    Returns:
        dict: Die Antwort vom Bildgenerierungs-Service
    """
    log_debug("=== GENERATE_IMG START ===")
    log_debug(f"Prompt: {prompt}")
    log_debug(f"Image name: {img_name}")
    
    cfg = _load_config()
    
    # Check if target file already exists
    target_path = pathlib.Path(img_name)
    if target_path.exists():
        log_debug(f"WARNING: Target file already exists: {target_path.absolute()}")
    
    req_data = {"prompt": prompt, "file": img_name}
    req = json.dumps(req_data) + "\n"
    log_debug(f"Request data: {req_data}")
    log_debug(f"Raw request: {req.strip()}")
    
    try:
        log_debug(f"Connecting to {cfg['host']}:{cfg['port']}")
        start_time = time.time()
        
        with socket.create_connection((cfg["host"], cfg["port"]), timeout=300) as s:
            log_debug("✅ Socket connection established")
            
            log_debug("Sending request...")
            s.sendall(req.encode())
            log_debug("✅ Request sent")
            
            log_debug("Waiting for response...")
            resp_raw = s.makefile().readline()
            end_time = time.time()
            
            log_debug(f"Raw response received: {resp_raw.strip()}")
            log_debug(f"Total request time: {end_time - start_time:.2f}s")
            
            if not resp_raw:
                log_debug("ERROR: Empty response received")
                raise ValueError("Empty response from service")
            
            try:
                response = json.loads(resp_raw)
                log_debug(f"Parsed response: {response}")
                
                # Check for error in response
                if "error" in response:
                    log_debug(f"ERROR response from service: {response['error']}")
                    return response
                
                # Verify file was created on client side
                if "file" in response:
                    response_file_path = pathlib.Path(response["file"])
                    log_debug(f"Response indicates file: {response_file_path}")
                    log_debug(f"File exists: {response_file_path.exists()}")
                    if response_file_path.exists():
                        file_size = response_file_path.stat().st_size
                        log_debug(f"✅ File verified on client side: {response_file_path} (size: {file_size} bytes)")
                    else:
                        log_debug(f"❌ ERROR: File not found on client side: {response_file_path}")
                
                log_debug("✅ Request completed successfully")
                return response
                
            except json.JSONDecodeError as e:
                log_debug(f"ERROR: Invalid JSON response: {e}")
                log_debug(f"Raw response was: {resp_raw}")
                raise ValueError("Ungültige Antwort vom Service erhalten.")
                
    except socket.timeout:
        log_debug("ERROR: Socket timeout")
        raise ConnectionError("Socket timeout beim Service")
    except socket.error as e:
        log_debug(f"ERROR: Socket error: {e}")
        raise ConnectionError(f"Verbindung zum Service fehlgeschlagen: {e}")
    except Exception as e:
        log_debug(f"ERROR: Unexpected error: {e}")
        raise
    finally:
        log_debug("=== GENERATE_IMG END ===")

def main():
    """Test-Funktion für das Modul."""
    log_debug("=== IMG_GEN TEST START ===")
    try:
        result = generate_img("dndstyle illustration of a drag queen", "queen.png")
        log_debug(f"Test result: {result}")
        print(result)
    except Exception as e:
        log_debug(f"Test failed: {e}")
        raise
    finally:
        log_debug("=== IMG_GEN TEST END ===")

if __name__ == "__main__":
    main() 