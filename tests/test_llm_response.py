#!/usr/bin/env python3
"""
Test-Script für LLM-Antworten - Debug DeepSeek-R1 Parsing
"""
import ollama
import re

def test_simple_prompt():
    """Testet eine einfache Prompt-Antwort."""
    prompt = """You are a D&D scene analyst. 

Generate a response in this EXACT format:

SCENE ANALYSIS: A brief description

DNDSTYLE IMAGE PROMPT: dndstyle, detailed prompt here

IMAGE NAME: scene_name

Here's a D&D transcript:
[19:12:00] Drücken Symbol, Wand dreht.
[19:12:18] Raum dahinter voller Fresken.
[19:12:36] Fresken zeigen Drachen und Ritter.

Please analyze and respond."""

    print("🤖 Teste einfachen Prompt...")
    
    try:
        # Lade Model aus Config
        try:
            import json
            with open('run_config.json', 'r') as f:
                config = json.load(f)
            model_name = config['services']['ollama']['required_model']
        except Exception as e:
            print(f"❌ Fehler beim Laden der Model-Config: {e}")
            model_name = "deepseek-r1:14b"  # Fallback
        
        print(f"🤖 Verwende Modell: {model_name}")
        
        # Verwende richtige Ollama API
        try:
            response = ollama.chat(
                model=model_name,
                messages=[{'role': 'user', 'content': prompt}],
                options={
                    'temperature': 0.3,
                    'num_predict': 800
                }
            )
        except AttributeError:
            # Fallback für ältere ollama API
            try:
                response = ollama.generate(
                    model=model_name,
                    prompt=prompt,
                    options={
                        'temperature': 0.3,
                        'num_predict': 800
                    }
                )
            except AttributeError:
                # Letzte Option: Client verwenden
                client = ollama.Client()
                response = client.generate(
                    model=model_name,
                    prompt=prompt,
                    options={
                        'temperature': 0.3,
                        'num_predict': 800
                    }
                )
        
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
            print("✅ Antwort erhalten:")
            print("=" * 50)
            print(response_text)
            print("=" * 50)
            
            # Teste Parsing
            text = response_text
            
            # Entferne <think> Tags
            if '<think>' in text and '</think>' in text:
                after_think = text.split('</think>')
                if len(after_think) > 1:
                    text = after_think[1].strip()
                    print(f"\n🧠 Nach <think> Entfernung:\n{text}")
            
            # Teste Pattern
            prompt_match = re.search(r'DNDSTYLE IMAGE PROMPT:\s*(.+?)(?=\nIMAGE NAME:|$)', text, re.IGNORECASE | re.DOTALL)
            name_match = re.search(r'IMAGE NAME:\s*(.+?)(?=\n|$)', text, re.IGNORECASE)
            
            if prompt_match:
                print(f"\n✅ Prompt gefunden: {prompt_match.group(1).strip()}")
            else:
                print("\n❌ Prompt NICHT gefunden")
                
            if name_match:
                print(f"✅ Name gefunden: {name_match.group(1).strip()}")
            else:
                print("❌ Name NICHT gefunden")
                
        else:
            print("❌ Keine Antwort erhalten")
            
    except Exception as e:
        print(f"❌ Fehler: {e}")

if __name__ == "__main__":
    test_simple_prompt() 