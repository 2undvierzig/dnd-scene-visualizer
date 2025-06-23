#!/usr/bin/env python3
import os, sys, json, time, uuid, socket, pathlib, torch
from diffusers import FluxPipeline

CFG_PATH = pathlib.Path(__file__).with_suffix(".json")
CFG = json.loads(CFG_PATH.read_text())

# Sicherer Token-Zugriff über Umgebungsvariable
TOKEN = os.getenv("HUGGINGFACE_TOKEN")
if not TOKEN:
    print("FEHLER: HUGGINGFACE_TOKEN Umgebungsvariable ist nicht gesetzt!", file=sys.stderr)
    print("Bitte setzen Sie: export HUGGINGFACE_TOKEN=hf_IhrToken", file=sys.stderr)
    sys.exit(1)
DEVICE = "cuda" if torch.cuda.is_available() else "cpu"
DTYPE  = torch.bfloat16 if CFG["dtype"] == "bfloat16" else torch.float16
OUTDIR = pathlib.Path(CFG["output_dir"]).expanduser()
OUTDIR.mkdir(parents=True, exist_ok=True)

# === DEBUG STARTUP INFORMATION ===
def log_debug(msg):
    """Debug logging mit Timestamp."""
    timestamp = time.strftime("%Y-%m-%d %H:%M:%S")
    print(f"[{timestamp}] [IMG_SERVICE] {msg}", file=sys.stderr, flush=True)

log_debug("=== IMG GENERATION SERVICE STARTUP ===")
log_debug(f"Python Version: {sys.version}")
log_debug(f"Working Directory: {os.getcwd()}")
log_debug(f"Config Path: {CFG_PATH}")
log_debug(f"Config: {CFG}")
log_debug(f"Output Directory: {OUTDIR} (absolute: {OUTDIR.absolute()})")
log_debug(f"Output Directory exists: {OUTDIR.exists()}")
log_debug(f"Output Directory writable: {os.access(OUTDIR, os.W_OK)}")
log_debug(f"CUDA Available: {torch.cuda.is_available()}")
log_debug(f"Device: {DEVICE}")
log_debug(f"DTYPE: {DTYPE}")

# Liste existierende Dateien im Output-Verzeichnis
try:
    existing_files = list(OUTDIR.glob("*"))
    log_debug(f"Existing files in {OUTDIR}: {[f.name for f in existing_files]}")
except Exception as e:
    log_debug(f"Error listing output directory: {e}")

t0 = time.perf_counter()
log_debug("Loading model pipeline...")
PIPE = FluxPipeline.from_pretrained(
    CFG["model_id"],
    torch_dtype=DTYPE,
    token=TOKEN,
    trust_remote_code=True
).to(DEVICE)
log_debug("Loading LoRA weights...")
PIPE.load_lora_weights(
    CFG["lora_repo"],
    weight_name=CFG["lora_weight"],
    token=TOKEN
)
t1 = time.perf_counter()
log_debug(f"Model loaded in {t1 - t0:.2f}s")
sys.stderr.write(f"model_ready {t1 - t0:.2f}s\n")
sys.stderr.flush()

def handle(conn):
    client_addr = conn.getpeername()
    log_debug(f"=== NEW REQUEST from {client_addr} ===")
    
    try:
        line = conn.makefile().readline()
        if not line:
            log_debug("Empty request received")
            return
        
        log_debug(f"Raw request: {line.strip()}")
        req = json.loads(line)
        log_debug(f"Parsed request: {req}")
        
        prompt   = req["prompt"]
        outfile  = OUTDIR / req["file"]
        
        log_debug(f"Prompt: {prompt}")
        log_debug(f"Output file: {outfile}")
        log_debug(f"Output file absolute: {outfile.absolute()}")
        log_debug(f"Output file parent exists: {outfile.parent.exists()}")
        log_debug(f"Output file parent writable: {os.access(outfile.parent, os.W_OK)}")
        
        # Check if file already exists
        if outfile.exists():
            log_debug(f"WARNING: Output file already exists: {outfile}")
        
        log_debug("Starting image generation...")
        s1 = time.perf_counter()
        img = PIPE(prompt).images[0]
        s2 = time.perf_counter()
        log_debug(f"Image generated in {s2 - s1:.3f}s")
        log_debug(f"Image type: {type(img)}")
        log_debug(f"Image size: {img.size if hasattr(img, 'size') else 'unknown'}")
        
        log_debug(f"Saving image to: {outfile}")
        try:
            img.save(outfile)
            s3 = time.perf_counter()
            log_debug(f"Image saved in {s3 - s2:.3f}s")
            
            # Verify file was actually created
            if outfile.exists():
                file_size = outfile.stat().st_size
                log_debug(f"✅ File successfully created: {outfile} (size: {file_size} bytes)")
            else:
                log_debug(f"❌ ERROR: File was not created: {outfile}")
            
            # List current directory contents for debugging
            try:
                current_files = list(OUTDIR.glob("*"))
                log_debug(f"Current files in {OUTDIR}: {[f.name for f in current_files]}")
            except Exception as e:
                log_debug(f"Error listing directory after save: {e}")
                
        except Exception as save_error:
            log_debug(f"ERROR saving image: {save_error}")
            raise save_error
        
        resp = {
            "file": str(outfile),
            "timings": {
                "inference_s": round(s2 - s1, 3),
                "save_s":      round(s3 - s2, 3),
                "total_s":     round(s3 - s1, 3)
            }
        }
        
        log_debug(f"Response: {resp}")
        response_json = json.dumps(resp) + "\n"
        log_debug(f"Sending response: {response_json.strip()}")
        conn.sendall(response_json.encode())
        log_debug("✅ Request completed successfully")
        
    except Exception as e:
        error_msg = f"❌ Request failed: {e}"
        log_debug(error_msg)
        log_debug(f"Exception type: {type(e)}")
        import traceback
        log_debug(f"Traceback: {traceback.format_exc()}")
        
        error_response = json.dumps({"error": str(e)}) + "\n"
        try:
            conn.sendall(error_response.encode())
        except Exception as send_error:
            log_debug(f"Failed to send error response: {send_error}")
    finally:
        log_debug(f"=== REQUEST END for {client_addr} ===")
        conn.close()

log_debug(f"Starting socket server on {CFG['host']}:{CFG['port']}")
with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as srv:
    srv.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    srv.bind((CFG["host"], CFG["port"]))
    srv.listen()
    log_debug(f"✅ Server listening on {CFG['host']}:{CFG['port']}")
    
    while True:
        c, addr = srv.accept()
        log_debug(f"Accepted connection from {addr}")
        handle(c)
