import pyaudio
import numpy as np
from faster_whisper import WhisperModel
import threading
import time
import os
import wave
from datetime import datetime

def test_audio_devices():
    """Test 1: Verfügbare Audio-Geräte anzeigen"""
    print("=== TEST 1: Audio-Geräte ===")
    try:
        p = pyaudio.PyAudio()
        print(f"Anzahl Audio-Geräte: {p.get_device_count()}")
        
        for i in range(p.get_device_count()):
            info = p.get_device_info_by_index(i)
            print(f"Gerät {i}: {info['name']} - Input Channels: {info['maxInputChannels']}")
            
        # Standard-Eingabegerät
        default_input = p.get_default_input_device_info()
        print(f"\nStandard-Eingabegerät: {default_input['name']}")
        print(f"Standard Sample Rate: {default_input['defaultSampleRate']}")
        
        p.terminate()
        return True
    except Exception as e:
        print(f"FEHLER bei Audio-Geräte Test: {e}")
        return False

def test_microphone_recording():
    """Test 2: Kurze Mikrofon-Aufnahme testen"""
    print("\n=== TEST 2: Mikrofon-Aufnahme (5 Sekunden) ===")
    try:
        CHUNK = 1024
        FORMAT = pyaudio.paInt16
        CHANNELS = 1
        RATE = 16000
        RECORD_SECONDS = 5
        
        p = pyaudio.PyAudio()
        
        stream = p.open(format=FORMAT,
                       channels=CHANNELS,
                       rate=RATE,
                       input=True,
                       frames_per_buffer=CHUNK)
        
        print("Aufnahme startet... Sprechen Sie jetzt!")
        frames = []
        
        for i in range(0, int(RATE / CHUNK * RECORD_SECONDS)):
            data = stream.read(CHUNK, exception_on_overflow=False)
            frames.append(data)
            if i % 10 == 0:  # Progress anzeigen
                print(f"Aufnahme... {i*CHUNK/RATE:.1f}s")
        
        print("Aufnahme beendet.")
        
        stream.stop_stream()
        stream.close()
        p.terminate()
        
        # Audio-Daten analysieren
        audio_data = b''.join(frames)
        audio_np = np.frombuffer(audio_data, dtype=np.int16)
        
        print(f"Audio-Daten Länge: {len(audio_np)} samples")
        print(f"Audio-Level (RMS): {np.sqrt(np.mean(audio_np**2)):.2f}")
        print(f"Max Amplitude: {np.max(np.abs(audio_np))}")
        
        # Speichere Test-Audio
        with wave.open("test_recording.wav", 'wb') as wf:
            wf.setnchannels(CHANNELS)
            wf.setsampwidth(p.get_sample_size(FORMAT))
            wf.setframerate(RATE)
            wf.writeframes(audio_data)
        
        print("Test-Aufnahme gespeichert als 'test_recording.wav'")
        return audio_np
        
    except Exception as e:
        print(f"FEHLER bei Mikrofon-Test: {e}")
        return None

def test_whisper_model():
    """Test 3: Whisper-Modell laden und testen"""
    print("\n=== TEST 3: Whisper-Modell ===")
    try:
        print("Lade Whisper-Modell...")
        
        # Versuche verschiedene Konfigurationen
        configs = [
            ("base", "cpu", "float32"),
            ("tiny", "cpu", "float32"),
            ("base", "cuda", "int8"),
            ("tiny", "cuda", "int8")
        ]
        
        model = None
        for size, device, compute_type in configs:
            try:
                print(f"Versuche: {size} auf {device} mit {compute_type}")
                model = WhisperModel(size, device=device, compute_type=compute_type)
                print(f"✓ Erfolg mit {size}/{device}/{compute_type}")
                break
            except Exception as e:
                print(f"✗ Fehlgeschlagen: {e}")
                continue
        
        if model is None:
            print("FEHLER: Kein Whisper-Modell konnte geladen werden!")
            return None
            
        # Test mit einem einfachen Audio-Array (Stille)
        print("Teste Modell mit Stille...")
        silent_audio = np.zeros(16000, dtype=np.float32)  # 1 Sekunde Stille
        segments, info = model.transcribe(silent_audio, language="de")
        
        print(f"Sprache erkannt: {info.language}")
        print(f"Sprachwahrscheinlichkeit: {info.language_probability:.2f}")
        
        return model
        
    except Exception as e:
        print(f"FEHLER bei Whisper-Test: {e}")
        return None

def test_transcription_with_audio(model, audio_data):
    """Test 4: Transkription mit echten Audio-Daten"""
    print("\n=== TEST 4: Transkription ===")
    if model is None or audio_data is None:
        print("Überspringe - Modell oder Audio nicht verfügbar")
        return False
        
    try:
        # Audio normalisieren
        audio_float = audio_data.astype(np.float32) / 32768.0
        
        print("Starte Transkription...")
        segments, info = model.transcribe(audio_float, beam_size=5, language="de", initial_prompt="Hallo")
        
        print(f"Erkannte Sprache: {info.language} (Wahrscheinlichkeit: {info.language_probability:.2f})")
        
        found_text = False
        for segment in segments:
            text = segment.text.strip()
            if text:
                print(f"[{segment.start:.2f}s - {segment.end:.2f}s]: {text}")
                found_text = True
        
        if not found_text:
            print("Keine Sprache erkannt - möglicherweise zu leise oder kein Sprach-Input")
            
        return found_text
        
    except Exception as e:
        print(f"FEHLER bei Transkription: {e}")
        return False

def test_file_writing():
    """Test 5: Datei-Schreibung testen"""
    print("\n=== TEST 5: Datei-Schreibung ===")
    try:
        test_file = "test_transcript.txt"
        
        # Test schreiben
        with open(test_file, "w", encoding="utf-8") as f:
            f.write("Test-Transkription\n")
            f.flush()
        
        # Test lesen
        with open(test_file, "r", encoding="utf-8") as f:
            content = f.read()
        
        print(f"Test-Datei Inhalt: '{content.strip()}'")
        
        # Aufräumen
        os.remove(test_file)
        print("✓ Datei-Schreibung funktioniert")
        return True
        
    except Exception as e:
        print(f"FEHLER bei Datei-Test: {e}")
        return False

def test_buffer_simulation():
    """Test 6: Puffer-Simulation wie im Hauptprogramm"""
    print("\n=== TEST 6: Puffer-Simulation ===")
    try:
        from collections import deque
        
        # Simuliere Audio-Puffer
        buffer = deque()
        RATE = 16000
        CHUNK_SIZE = 1024
        BUFFER_DURATION = 3
        
        # Fülle Puffer mit Test-Daten
        max_chunks = int(BUFFER_DURATION * RATE / CHUNK_SIZE)
        print(f"Erwartete Chunks für {BUFFER_DURATION}s: {max_chunks}")
        
        for i in range(max_chunks + 5):  # Etwas mehr als nötig
            chunk = np.random.randint(-1000, 1000, CHUNK_SIZE, dtype=np.int16).tobytes()
            buffer.append(chunk)
            
            # Puffer-Begrenzung wie im Original
            while len(buffer) > max_chunks:
                buffer.popleft()
        
        print(f"Finale Puffer-Größe: {len(buffer)} chunks")
        
        # Kombiniere Chunks
        audio_data = b''.join(list(buffer))
        audio_np = np.frombuffer(audio_data, dtype=np.int16).astype(np.float32) / 32768.0
        
        print(f"Kombinierte Audio-Länge: {len(audio_np)} samples ({len(audio_np)/RATE:.2f}s)")
        print("✓ Puffer-Logik funktioniert")
        return True
        
    except Exception as e:
        print(f"FEHLER bei Puffer-Test: {e}")
        return False

def main():
    """Führe alle Tests aus"""
    print("🔧 STT DIAGNOSE-TESTS STARTEN 🔧")
    print("=" * 50)
    
    results = {}
    
    # Test 1: Audio-Geräte
    results['audio_devices'] = test_audio_devices()
    
    # Test 2: Mikrofon-Aufnahme
    audio_data = test_microphone_recording()
    results['microphone'] = audio_data is not None
    
    # Test 3: Whisper-Modell
    model = test_whisper_model()
    results['whisper_model'] = model is not None
    
    # Test 4: Transkription
    results['transcription'] = test_transcription_with_audio(model, audio_data)
    
    # Test 5: Datei-Schreibung
    results['file_writing'] = test_file_writing()
    
    # Test 6: Puffer-Simulation
    results['buffer_logic'] = test_buffer_simulation()
    
    # Zusammenfassung
    print("\n" + "=" * 50)
    print("📊 TEST-ERGEBNISSE:")
    print("=" * 50)
    
    for test_name, passed in results.items():
        status = "✅ BESTANDEN" if passed else "❌ FEHLGESCHLAGEN"
        print(f"{test_name.replace('_', ' ').title()}: {status}")
    
    failed_tests = [name for name, passed in results.items() if not passed]
    
    if failed_tests:
        print(f"\n🚨 FEHLGESCHLAGENE TESTS: {', '.join(failed_tests)}")
        print("\n💡 LÖSUNGSVORSCHLÄGE:")
        
        if 'audio_devices' in failed_tests:
            print("- Überprüfen Sie PyAudio-Installation: pip install pyaudio")
            
        if 'microphone' in failed_tests:
            print("- Mikrofon-Berechtigung prüfen")
            print("- Anderes Audio-Gerät versuchen")
            
        if 'whisper_model' in failed_tests:
            print("- Internet-Verbindung für Modell-Download prüfen")
            print("- Versuchen Sie 'tiny' Modell: WhisperModel('tiny', device='cpu')")
            
        if 'transcription' in failed_tests:
            print("- Lauter sprechen während der Test-Aufnahme")
            print("- Längere Audio-Segmente testen")
    else:
        print("\n🎉 ALLE TESTS BESTANDEN!")
        print("Das Problem liegt möglicherweise in der Main-Loop oder Threading-Logik.")

if __name__ == "__main__":
    main() 