import asyncio
import json
import os
import wave
import logging
import threading
import queue
import time
import traceback
from datetime import datetime
from pathlib import Path
from typing import List, Dict, Any, Optional

import numpy as np
# Removed: import sounddevice as sd - not needed for client-side recording
from fastapi import FastAPI, Request, HTTPException, Form, UploadFile, File
from fastapi.responses import HTMLResponse, FileResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
import uvicorn

# Setup logging FIRST
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Disable uvicorn access logs
logging.getLogger("uvicorn.access").setLevel(logging.WARNING)

# Try to import torch (should come with faster-whisper)
try:
    import torch
    TORCH_AVAILABLE = True
    logger.info("✅ torch imported successfully")
except ImportError:
    TORCH_AVAILABLE = False
    logger.warning("⚠️ torch not available - CUDA detection disabled")
    torch = None

# Initialize faster-whisper after CUDA check
try:
    from faster_whisper import WhisperModel
    WHISPER_AVAILABLE = True
    logger.info("✅ faster-whisper imported successfully")
except ImportError as e:
    WHISPER_AVAILABLE = False
    logger.error(f"❌ faster-whisper not available: {e}")
    WhisperModel = None

app = FastAPI(title="Audio Recording App", description="Record and play audio with device selection")

# Create directories
Path("static").mkdir(exist_ok=True)
Path("templates").mkdir(exist_ok=True)
Path("recordings").mkdir(exist_ok=True)
Path("transkripte").mkdir(exist_ok=True)

# Mount static files
app.mount("/static", StaticFiles(directory="static"), name="static")

# Setup templates
templates = Jinja2Templates(directory="templates")

# Global variables for client-side recording (simplified)
# Removed: recording_data, is_recording - client-side recording only
current_recording = None
sample_rate = 44100  # Still used for transcription reference

# Global variables for transcription
transcription_model = None
cuda_available = False
transcription_results = {}
is_transcribing = False

# Global variables for continuous recording (client-side)
# Removed: continuous_recording, continuous_recording_thread, current_continuous_scene, scene_duration, continuous_recording_stats
# Client-side handles continuous recording directly
transcription_queue = queue.Queue()
transcription_worker_thread = None

# CUDA and model initialization
def check_cuda_and_init_model():
    """Check CUDA availability and initialize Whisper model"""
    global cuda_available, transcription_model
    
    # Check CUDA (only if torch is available)
    if TORCH_AVAILABLE and torch:
        cuda_available = torch.cuda.is_available()
        logger.info(f"🔍 CUDA Check:")
        logger.info(f"   - CUDA Available: {cuda_available}")
        
        if cuda_available:
            logger.info(f"   - CUDA Devices: {torch.cuda.device_count()}")
            logger.info(f"   - Current Device: {torch.cuda.current_device()}")
            logger.info(f"   - Device Name: {torch.cuda.get_device_name()}")
            logger.info(f"   - Memory: {torch.cuda.get_device_properties(0).total_memory / 1024**3:.1f} GB")
    else:
        cuda_available = False
        logger.info(f"🔍 CUDA Check: torch not available - assuming CPU only")
    
    # Initialize Whisper model
    if WHISPER_AVAILABLE:
        try:
            model_size = "large-v3"
            if cuda_available:
                logger.info(f"🚀 Initializing Whisper model '{model_size}' on CUDA with FP16...")
                transcription_model = WhisperModel(model_size, device="cuda", compute_type="float16")
                logger.info("✅ Whisper model loaded successfully on CUDA")
            else:
                logger.info(f"🚀 Initializing Whisper model '{model_size}' on CPU...")
                transcription_model = WhisperModel(model_size, device="cpu", compute_type="int8")
                logger.info("✅ Whisper model loaded successfully on CPU")
        except Exception as e:
            logger.error(f"❌ Failed to load Whisper model: {e}")
            transcription_model = None
    else:
        logger.warning("⚠️ Whisper not available - transcription disabled")

# Initialize model on startup
check_cuda_and_init_model()

# Removed: continuous_recording_worker() - server-side continuous recording replaced with client-side

def transcription_worker():
    """Background transcription worker thread"""
    global is_transcribing
    
    logger.info("📝 Transcription worker started")
    
    while True:
        try:
            # Wait for file to transcribe
            filename = transcription_queue.get(timeout=1)
            
            if filename is None:  # Shutdown signal
                break
            
            logger.info(f"🎯 Processing transcription queue: {filename}")
            
            # Run transcription with timeout monitoring
            import concurrent.futures
            with concurrent.futures.ThreadPoolExecutor(max_workers=1) as executor:
                future = executor.submit(transcribe_audio_async, filename)
                try:
                    # Wait max 10 minutes for transcription
                    future.result(timeout=600)
                    logger.info(f"✅ Transcription completed successfully for: {filename}")
                except concurrent.futures.TimeoutError:
                    logger.error(f"❌ Transcription timeout after 10 minutes for: {filename}")
                    transcription_results[filename] = {
                        "filename": filename,
                        "error": "Transcription timeout after 10 minutes",
                        "timestamp": datetime.now().isoformat()
                    }
                except Exception as e:
                    logger.error(f"❌ Transcription error for {filename}: {e}")
            
            transcription_queue.task_done()
            
        except queue.Empty:
            continue
        except Exception as e:
            logger.error(f"❌ Error in transcription worker: {e}")
            import traceback
            logger.error(f"❌ Full traceback: {traceback.format_exc()}")
    
    logger.info("🏁 Transcription worker finished")

def start_transcription_worker():
    """Start the transcription worker thread"""
    global transcription_worker_thread
    
    if transcription_worker_thread is None or not transcription_worker_thread.is_alive():
        transcription_worker_thread = threading.Thread(
            target=transcription_worker,
            daemon=True
        )
        transcription_worker_thread.start()
        logger.info("🚀 Transcription worker thread started")

# Start transcription worker on startup
start_transcription_worker()

@app.get("/", response_class=HTMLResponse)
async def home(request: Request):
    """Main page with audio recording interface"""
    return templates.TemplateResponse("index.html", {"request": request})

def save_transcript_to_file(filename: str, transcript_data: dict):
    """Save transcript data to a .txt file in transkripte directory"""
    try:
        logger.info(f"📝 Starting save_transcript_to_file for: {filename}")
        
        # Generate transcript filename
        base_name = os.path.splitext(filename)[0]
        transcript_filename = f"{base_name}_transkript.txt"
        transcript_path = os.path.join("transkripte", transcript_filename)
        
        logger.info(f"📝 Generated path: {transcript_path}")
        logger.info(f"📝 Transcript data keys: {list(transcript_data.keys())}")
        
        # Ensure transkripte directory exists
        os.makedirs("transkripte", exist_ok=True)
        logger.info(f"📝 Ensured transkripte directory exists")
        
        # Create content
        content = []
        content.append(f"Transkript für: {filename}")
        content.append(f"Datum: {datetime.now().strftime('%d.%m.%Y %H:%M:%S')}")
        content.append(f"Sprache: {transcript_data.get('language', 'Unbekannt')}")
        content.append(f"Konfidenz: {transcript_data.get('language_probability', 0) * 100:.1f}%")
        content.append(f"Dauer: {transcript_data.get('duration', 0):.2f} Sekunden")
        content.append(f"Verarbeitet mit: {transcript_data.get('device', 'CPU')}")
        content.append("=" * 50)
        content.append("")
        
        # Add full text
        content.append("VOLLTEXT:")
        full_text = transcript_data.get('full_text', 'Kein Text erkannt')
        content.append(full_text)
        content.append("")
        content.append("=" * 50)
        content.append("")
        
        # Add segments with timestamps
        content.append("ZEITGESTEMPELTE SEGMENTE:")
        segments = transcript_data.get('segments', [])
        logger.info(f"📝 Processing {len(segments)} segments")
        
        if segments:
            for i, segment in enumerate(segments, 1):
                start_time = segment.get('start', 0)
                end_time = segment.get('end', 0)
                text = segment.get('text', '')
                
                # Format timestamps
                start_min = int(start_time // 60)
                start_sec = start_time % 60
                end_min = int(end_time // 60)
                end_sec = end_time % 60
                
                content.append(f"[{start_min:02d}:{start_sec:05.2f} - {end_min:02d}:{end_sec:05.2f}] {text}")
        else:
            content.append("Keine Segmente verfügbar")
        
        logger.info(f"📝 Content prepared, total lines: {len(content)}")
        logger.info(f"📝 Full text length: {len(full_text)} chars")
        
        # Write file
        with open(transcript_path, 'w', encoding='utf-8') as f:
            f.write('\n'.join(content))
        
        # Verify file was created
        if os.path.exists(transcript_path):
            file_size = os.path.getsize(transcript_path)
            logger.info(f"📄 SUCCESS: Transcript saved to: {transcript_path} ({file_size} bytes)")
        else:
            logger.error(f"❌ FAILED: File was not created: {transcript_path}")
        
    except Exception as e:
        logger.error(f"❌ Error in save_transcript_to_file: {e}")
        import traceback
        logger.error(f"❌ Full traceback: {traceback.format_exc()}")
        raise

def split_audio_into_segments(filepath: str, segment_duration: int = 30):
    """Split audio file into 30-second segments for processing"""
    import wave
    import tempfile
    
    segments = []
    
    try:
        with wave.open(filepath, 'rb') as wav_file:
            frames = wav_file.getnframes()
            rate = wav_file.getframerate()
            channels = wav_file.getnchannels()
            sampwidth = wav_file.getsampwidth()
            
            total_duration = frames / float(rate)
            segment_frames = int(segment_duration * rate)
            
            logger.info(f"🔄 Splitting audio: {total_duration:.2f}s into {segment_duration}s segments")
            
            # Read all audio data
            wav_file.rewind()
            audio_data = wav_file.readframes(frames)
            
            # Create segments
            segment_count = 0
            for start_frame in range(0, frames, segment_frames):
                segment_count += 1
                end_frame = min(start_frame + segment_frames, frames)
                
                # Calculate byte positions
                bytes_per_frame = channels * sampwidth
                start_byte = start_frame * bytes_per_frame
                end_byte = end_frame * bytes_per_frame
                
                # Extract segment data
                segment_data = audio_data[start_byte:end_byte]
                
                # Create temporary file for this segment
                with tempfile.NamedTemporaryFile(suffix='.wav', delete=False) as temp_file:
                    temp_path = temp_file.name
                    
                    # Write segment to temporary file
                    with wave.open(temp_path, 'wb') as segment_wav:
                        segment_wav.setnchannels(channels)
                        segment_wav.setsampwidth(sampwidth)
                        segment_wav.setframerate(rate)
                        segment_wav.writeframes(segment_data)
                    
                    start_time = start_frame / float(rate)
                    end_time = end_frame / float(rate)
                    
                    segments.append({
                        'path': temp_path,
                        'start_time': start_time,
                        'end_time': end_time,
                        'segment_number': segment_count,
                        'duration': end_time - start_time
                    })
                    
                    logger.info(f"   📄 Segment {segment_count}: {start_time:.1f}s-{end_time:.1f}s ({temp_path})")
            
            logger.info(f"✅ Created {len(segments)} segments")
            return segments
            
    except Exception as e:
        logger.error(f"❌ Error splitting audio: {e}")
        raise


def transcribe_single_segment(segment_path: str, segment_info: dict):
    """Transcribe a single audio segment"""
    import time
    
    try:
        segment_start_time = time.time()
        logger.info(f"🎯 Transcribing segment {segment_info['segment_number']}: {segment_info['start_time']:.1f}s-{segment_info['end_time']:.1f}s")
        
        # Transcribe segment with VAD
        segments_generator, info = transcription_model.transcribe(
            segment_path, 
            language="de",
            beam_size=5,
            vad_filter=True,
            vad_parameters=dict(
                min_silence_duration_ms=500
            )
        )
        
        # Collect segment results
        text_segments = []
        segment_text = ""
        
        for segment in segments_generator:
            # Adjust timestamps to match position in full audio
            adjusted_start = segment.start + segment_info['start_time']
            adjusted_end = segment.end + segment_info['start_time']
            
            segment_data = {
                "start": round(adjusted_start, 2),
                "end": round(adjusted_end, 2),
                "text": segment.text.strip()
            }
            text_segments.append(segment_data)
            segment_text += segment.text.strip() + " "
        
        # Calculate transcription time
        segment_end_time = time.time()
        transcription_duration = segment_end_time - segment_start_time
        segment_audio_duration = segment_info['duration']
        
        # Log completion with timing
        logger.info(f"✅ Segment {segment_info['segment_number']} completed: {len(text_segments)} parts, {len(segment_text)} chars in {transcription_duration:.2f}s")
        
        # Warning if transcription took longer than the audio duration
        if transcription_duration > segment_audio_duration:
            logger.warning(f"⚠️ SLOW TRANSCRIPTION: Segment {segment_info['segment_number']} took {transcription_duration:.2f}s to transcribe {segment_audio_duration:.1f}s of audio (ratio: {transcription_duration/segment_audio_duration:.2f}x)")
        else:
            logger.info(f"⚡ Fast transcription: {transcription_duration:.2f}s for {segment_audio_duration:.1f}s audio (ratio: {transcription_duration/segment_audio_duration:.2f}x)")
        
        return {
            'segment_number': segment_info['segment_number'],
            'start_time': segment_info['start_time'],
            'end_time': segment_info['end_time'],
            'text': segment_text.strip(),
            'segments': text_segments,
            'language': info.language,
            'language_probability': info.language_probability,
            'transcription_duration': transcription_duration,
            'audio_duration': segment_audio_duration,
            'speed_ratio': transcription_duration / segment_audio_duration
        }
        
    except Exception as e:
        segment_end_time = time.time()
        transcription_duration = segment_end_time - segment_start_time
        
        logger.error(f"❌ Error transcribing segment {segment_info['segment_number']} after {transcription_duration:.2f}s: {e}")
        return {
            'segment_number': segment_info['segment_number'],
            'start_time': segment_info['start_time'],
            'end_time': segment_info['end_time'],
            'text': '',
            'segments': [],
            'error': str(e),
            'transcription_duration': transcription_duration
        }


def transcribe_scene_with_segments(filename: str):
    """Transcribe a scene by splitting it into 30-second segments"""
    global is_transcribing, transcription_results
    import time
    import os
    
    start_time = time.time()
    
    if not transcription_model:
        logger.error("❌ Transcription model not available")
        return
    
    filepath = os.path.join("recordings", filename)
    if not os.path.exists(filepath):
        logger.error(f"❌ File not found: {filepath}")
        return
    
    try:
        is_transcribing = True
        logger.info(f"🎭 Starting segment-based transcription for scene: {filename}")
        logger.info(f"   - File path: {filepath}")
        logger.info(f"   - File size: {os.path.getsize(filepath)} bytes")
        logger.info(f"   - Using device: {'CUDA' if cuda_available else 'CPU'}")
        
        # Check audio duration first
        import wave
        with wave.open(filepath, 'rb') as wav_file:
            frames = wav_file.getnframes()
            rate = wav_file.getframerate()
            audio_duration = frames / float(rate)
            logger.info(f"📊 Audio file duration: {audio_duration:.2f} seconds")
        
        # Split audio into 30-second segments
        split_start = time.time()
        segments = split_audio_into_segments(filepath, segment_duration=30)
        split_end = time.time()
        logger.info(f"⏱️ Audio splitting completed in {split_end - split_start:.2f}s")
        
        # Transcribe each segment
        transcribe_start = time.time()
        segment_results = []
        
        for i, segment_info in enumerate(segments):
            logger.info(f"📝 Processing segment {i+1}/{len(segments)}")
            
            try:
                result = transcribe_single_segment(segment_info['path'], segment_info)
                segment_results.append(result)
                
                # Clean up temporary file
                os.unlink(segment_info['path'])
                
            except Exception as e:
                logger.error(f"❌ Failed to process segment {i+1}: {e}")
                # Clean up temporary file even on error
                try:
                    os.unlink(segment_info['path'])
                except:
                    pass
        
        transcribe_end = time.time()
        logger.info(f"⏱️ All segments transcribed in {transcribe_end - transcribe_start:.2f}s")
        
        # Calculate performance statistics
        total_transcription_time = 0
        slow_segments = []
        fast_segments = []
        
        for result in segment_results:
            if 'transcription_duration' in result:
                total_transcription_time += result['transcription_duration']
                if 'speed_ratio' in result:
                    if result['speed_ratio'] > 1.0:
                        slow_segments.append((result['segment_number'], result['speed_ratio']))
                    else:
                        fast_segments.append((result['segment_number'], result['speed_ratio']))
        
        # Log performance summary
        logger.info(f"📊 PERFORMANCE SUMMARY:")
        logger.info(f"   - Total audio duration: {audio_duration:.1f}s")
        logger.info(f"   - Total transcription time: {total_transcription_time:.1f}s")
        logger.info(f"   - Overall speed ratio: {total_transcription_time/audio_duration:.2f}x")
        
        if slow_segments:
            logger.warning(f"   - ⚠️ Slow segments (>1x realtime): {len(slow_segments)}")
            for seg_num, ratio in slow_segments:
                logger.warning(f"      • Segment {seg_num}: {ratio:.2f}x slower than realtime")
        
        if fast_segments:
            logger.info(f"   - ⚡ Fast segments (<1x realtime): {len(fast_segments)}")
        
        # Combine results
        combine_start = time.time()
        all_segments = []
        full_text = ""
        
        # Sort by segment number to ensure correct order
        segment_results.sort(key=lambda x: x['segment_number'])
        
        for result in segment_results:
            if 'error' not in result:
                full_text += result['text'] + " "
                all_segments.extend(result['segments'])
        
        # Get language info from first successful segment
        language = "de"
        language_probability = 1.0
        for result in segment_results:
            if 'language' in result:
                language = result['language']
                language_probability = result['language_probability']
                break
        
        # Sort all segments by start time
        all_segments.sort(key=lambda x: x['start'])
        
        combine_end = time.time()
        logger.info(f"⏱️ Results combined in {combine_end - combine_start:.2f}s")
        
        # Create final result data
        result_data = {
            "filename": filename,
            "full_text": full_text.strip(),
            "segments": all_segments,
            "language": language,
            "language_probability": round(language_probability, 3),
            "duration": round(audio_duration, 2),
            "timestamp": datetime.now().isoformat(),
            "device": "CUDA" if cuda_available else "CPU",
            "processing_method": "segment-based",
            "segment_count": len(segments),
            "successful_segments": len([r for r in segment_results if 'error' not in r])
        }
        
        transcription_results[filename] = result_data
        logger.info(f"💾 Scene transcription result saved to dictionary with key: {filename}")
        
        # Save transcript as .txt file
        try:
            save_start = time.time()
            logger.info(f"💾 Saving .txt file for scene: {filename}")
            save_transcript_to_file(filename, result_data)
            save_end = time.time()
            logger.info(f"✅ Successfully saved .txt file for scene: {filename} in {save_end - save_start:.2f}s")
        except Exception as txt_error:
            logger.error(f"❌ Failed to save transcript file for {filename}: {txt_error}")
            import traceback
            logger.error(f"❌ Full traceback: {traceback.format_exc()}")
        
        total_time = time.time() - start_time
        logger.info(f"🎭 Scene transcription FULLY completed: {filename} in {total_time:.2f}s total")
        logger.info(f"   - Language: {language} ({language_probability:.3f})")
        logger.info(f"   - Duration: {audio_duration:.2f}s")
        logger.info(f"   - Segments processed: {len(segments)}")
        logger.info(f"   - Successful segments: {len([r for r in segment_results if 'error' not in r])}")
        logger.info(f"   - Total text segments: {len(all_segments)}")
        logger.info(f"   - Full text length: {len(full_text)} characters")
        
    except Exception as e:
        logger.error(f"❌ Scene transcription failed for {filename}: {e}")
        logger.error(f"   - Exception type: {type(e).__name__}")
        import traceback
        logger.error(f"❌ Full traceback: {traceback.format_exc()}")
        
        transcription_results[filename] = {
            "filename": filename,
            "error": str(e),
            "timestamp": datetime.now().isoformat()
        }
    finally:
        is_transcribing = False
        logger.info(f"🏁 Scene transcription thread finished for: {filename}")


def transcribe_audio_async(filename: str):
    """Transcribe audio file - uses segment-based method for scenes, traditional method for recordings"""
    
    # Use segment-based transcription for scenes
    if filename.startswith("scene_"):
        logger.info(f"🎭 Using segment-based transcription for scene: {filename}")
        transcribe_scene_with_segments(filename)
        return
    
    # Traditional transcription for single recordings
    global is_transcribing, transcription_results
    import time
    
    start_time = time.time()
    
    if not transcription_model:
        logger.error("❌ Transcription model not available")
        return
    
    filepath = os.path.join("recordings", filename)
    if not os.path.exists(filepath):
        logger.error(f"❌ File not found: {filepath}")
        return
    
    try:
        is_transcribing = True
        logger.info(f"🎯 Starting traditional transcription for: {filename}")
        logger.info(f"   - File path: {filepath}")
        logger.info(f"   - File size: {os.path.getsize(filepath)} bytes")
        logger.info(f"   - Using device: {'CUDA' if cuda_available else 'CPU'}")
        
        # Check audio duration first
        import wave
        with wave.open(filepath, 'rb') as wav_file:
            frames = wav_file.getnframes()
            rate = wav_file.getframerate()
            audio_duration = frames / float(rate)
            logger.info(f"📊 Audio file duration: {audio_duration:.2f} seconds")
        
        # Always use VAD for all files
        logger.info(f"📊 VAD filter: ENABLED (for all durations)")
        
        try:
            segments_generator, info = transcription_model.transcribe(
                filepath, 
                language="de",
                beam_size=5,
                vad_filter=True,
                vad_parameters=dict(
                    min_silence_duration_ms=500
                )
            )
            logger.info("✅ transcribe() method returned successfully")
        except Exception as e:
            logger.error(f"❌ Error calling transcribe(): {e}")
            raise
        
        # Log info about the audio
        logger.info(f"📊 Audio info - Duration: {info.duration:.2f}s, Language: {info.language}")
        
        # Convert generator to list with progress tracking
        segments = []
        segment_count = 0
        last_log_time = time.time()
        
        logger.info("🔄 Processing segments from generator...")
        try:
            for segment in segments_generator:
                segment_count += 1
                segments.append(segment)
                
                # Log progress every 5 seconds or every 10 segments
                current_time = time.time()
                if current_time - last_log_time > 5 or segment_count % 10 == 0:
                    logger.info(f"   📊 Progress: {segment_count} segments processed (last: {segment.start:.1f}s-{segment.end:.1f}s)")
                    last_log_time = current_time
            
            logger.info(f"✅ All segments collected: {segment_count} total")
        except Exception as e:
            logger.error(f"❌ Error processing segments: {e}")
            logger.error(f"   Processed {segment_count} segments before error")
            raise
        
        # Collect results
        text_segments = []
        full_text = ""
        
        for i, segment in enumerate(segments):
            segment_data = {
                "start": round(segment.start, 2),
                "end": round(segment.end, 2),
                "text": segment.text.strip()
            }
            text_segments.append(segment_data)
            full_text += segment.text.strip() + " "
        
        # Create result data
        result_data = {
            "filename": filename,
            "full_text": full_text.strip(),
            "segments": text_segments,
            "language": info.language,
            "language_probability": round(info.language_probability, 3),
            "duration": round(info.duration, 2),
            "timestamp": datetime.now().isoformat(),
            "device": "CUDA" if cuda_available else "CPU",
            "processing_method": "traditional"
        }
        
        transcription_results[filename] = result_data
        logger.info(f"💾 Transcription result saved to dictionary with key: {filename}")
        
        total_time = time.time() - start_time
        logger.info(f"✅ Traditional transcription completed for: {filename} in {total_time:.2f}s total")
        logger.info(f"   - Language: {info.language} ({info.language_probability:.3f})")
        logger.info(f"   - Duration: {info.duration:.2f}s")
        logger.info(f"   - Segments: {len(text_segments)}")
        logger.info(f"   - Full text length: {len(full_text)} characters")
        
    except Exception as e:
        logger.error(f"❌ Traditional transcription failed for {filename}: {e}")
        import traceback
        logger.error(f"❌ Full traceback: {traceback.format_exc()}")
        
        transcription_results[filename] = {
            "filename": filename,
            "error": str(e),
            "timestamp": datetime.now().isoformat()
        }
    finally:
        is_transcribing = False
        logger.info(f"🏁 Traditional transcription thread finished for: {filename}")

@app.get("/api/system-info")
async def get_system_info():
    """Get system information including CUDA status"""
    device_info = {}
    torch_version = "Not available"
    
    if TORCH_AVAILABLE and torch:
        torch_version = torch.__version__
        if cuda_available:
            device_info = {
                "count": torch.cuda.device_count(),
                "current": torch.cuda.current_device(),
                "name": torch.cuda.get_device_name(),
                "memory_gb": round(torch.cuda.get_device_properties(0).total_memory / 1024**3, 1)
            }
    
    return {
        "cuda_available": cuda_available,
        "whisper_available": WHISPER_AVAILABLE,
        "transcription_model_loaded": transcription_model is not None,
        "torch_available": TORCH_AVAILABLE,
        "torch_version": torch_version,
        "device_info": device_info
    }

# Removed: /api/devices endpoint - not needed for client-side recording
# Client-side audio device enumeration is handled by browser JavaScript

# Removed: /api/start-recording and /api/stop-recording endpoints
# Server-side recording replaced with client-side recording + upload

# Removed: /api/start-continuous-recording and /api/stop-continuous-recording endpoints
# Server-side continuous recording replaced with client-side scene recording + upload

@app.get("/api/recording-status")
async def get_recording_status():
    """Get current recording status - legacy endpoint for compatibility"""
    # Note: Server-side recording removed, but keeping endpoint for backward compatibility
    return {
        "is_recording": False,  # Always false - client-side recording only
        "current_recording": current_recording,
        "is_transcribing": is_transcribing,
        "transcription_available": transcription_model is not None,
        "continuous_recording": False,  # Always false - client-side recording only
        "transcription_queue_size": transcription_queue.qsize(),
        "note": "Server-side recording disabled - use client-side recording with upload"
    }

@app.get("/api/transcription/{filename}")
async def get_transcription(filename: str):
    """Get transcription for a specific recording"""
    logger.info(f"🔍 API request for transcription: {filename}")
    logger.info(f"📊 Available transcriptions: {list(transcription_results.keys())}")
    logger.info(f"📊 Transcription in progress: {is_transcribing}")
    
    if filename not in transcription_results:
        logger.info(f"❌ Transcription not found for: {filename}")
        raise HTTPException(status_code=404, detail="Transcription not found")
    
    logger.info(f"✅ Returning transcription for: {filename}")
    return transcription_results[filename]

@app.get("/api/transcriptions")
async def get_all_transcriptions():
    """Get all available transcriptions"""
    return {
        "transcriptions": transcription_results,
        "count": len(transcription_results),
        "is_transcribing": is_transcribing
    }

@app.get("/api/latest-scene-transcription")
async def get_latest_scene_transcription():
    """Get the latest completed scene transcription - legacy endpoint for compatibility"""
    # Find the latest scene file from recordings
    recordings_dir = Path("recordings")
    scene_files = sorted([f for f in recordings_dir.glob("scene_*.wav")], reverse=True)
    
    if not scene_files:
        raise HTTPException(status_code=404, detail="No scene recordings available")
    
    latest_file = scene_files[0].name
    
    if latest_file not in transcription_results:
        raise HTTPException(status_code=202, detail="Transcription not yet completed")
    
    return {
        "filename": latest_file,
        "transcription": transcription_results[latest_file],
        "note": "Server-side scene tracking disabled - using latest scene file"
    }

@app.get("/api/recordings")
async def get_recordings():
    """Get list of all recordings"""
    try:
        recordings_dir = Path("recordings")
        recordings = []
        
        for file in recordings_dir.glob("*.wav"):
            file_stats = file.stat()
            recordings.append({
                "filename": file.name,
                "size": file_stats.st_size,
                "created": datetime.fromtimestamp(file_stats.st_ctime).isoformat()
            })
        
        # Sort by creation time (newest first)
        recordings.sort(key=lambda x: x['created'], reverse=True)
        
        return {"recordings": recordings}
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error getting recordings: {str(e)}")

@app.get("/api/transcripts")
async def get_transcripts():
    """Get list of all transcript files"""
    try:
        transcripts_dir = Path("transkripte")
        transcripts = []
        
        for file in transcripts_dir.glob("*.txt"):
            if file.name == ".gitkeep":
                continue
                
            file_stats = file.stat()
            transcripts.append({
                "filename": file.name,
                "size": file_stats.st_size,
                "created": datetime.fromtimestamp(file_stats.st_ctime).isoformat(),
                "modified": datetime.fromtimestamp(file_stats.st_mtime).isoformat()
            })
        
        # Sort by creation time (newest first)
        transcripts.sort(key=lambda x: x['created'], reverse=True)
        
        return {"transcripts": transcripts}
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error getting transcripts: {str(e)}")

@app.get("/api/transcript/{filename}")
async def get_transcript_content(filename: str):
    """Get content of a specific transcript file"""
    try:
        # Security check: ensure filename doesn't contain path traversal
        if ".." in filename or "/" in filename or "\\" in filename:
            raise HTTPException(status_code=400, detail="Invalid filename")
        
        transcript_path = Path("transkripte") / filename
        
        if not transcript_path.exists():
            raise HTTPException(status_code=404, detail="Transcript file not found")
        
        if not transcript_path.suffix == ".txt":
            raise HTTPException(status_code=400, detail="Only .txt files are allowed")
        
        # Read file content
        content = transcript_path.read_text(encoding='utf-8')
        
        return {
            "filename": filename,
            "content": content,
            "size": transcript_path.stat().st_size
        }
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error reading transcript: {str(e)}")

@app.get("/api/play/{filename}")
async def play_recording(filename: str):
    """Serve audio file for playback"""
    filepath = os.path.join("recordings", filename)
    
    if not os.path.exists(filepath):
        raise HTTPException(status_code=404, detail="Recording not found")
    
    return FileResponse(filepath, media_type="audio/wav", filename=filename)

@app.delete("/api/recordings/{filename}")
async def delete_recording(filename: str):
    """Delete a recording"""
    filepath = os.path.join("recordings", filename)
    
    if not os.path.exists(filepath):
        raise HTTPException(status_code=404, detail="Recording not found")
    
    try:
        os.remove(filepath)
        return {"message": f"Recording {filename} deleted successfully"}
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error deleting recording: {str(e)}")

# ============= NEW CLIENT-SIDE RECORDING ENDPOINTS =============

@app.post("/api/upload-recording")
async def upload_recording(
    audio: UploadFile = File(...),
    filename: Optional[str] = Form(None)
):
    """Upload audio recording from client-side"""
    try:
        logger.info(f"📤 Received upload request - filename: {filename}, content_type: {audio.content_type}, size: {audio.size}")
        
        # Validate file type
        if not audio.content_type.startswith('audio/'):
            logger.error(f"❌ Invalid content type: {audio.content_type}")
            raise HTTPException(status_code=400, detail="File must be an audio file")
        
        # Generate filename if not provided
        if not filename:
            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            filename = f"recording_{timestamp}.wav"
        
        # Ensure filename ends with .wav
        if not filename.endswith('.wav'):
            filename = filename.rsplit('.', 1)[0] + '.wav'
        
        filepath = os.path.join("recordings", filename)
        logger.info(f"💾 Saving to: {filepath}")
        
        # Save uploaded file
        content = await audio.read()
        logger.info(f"📊 Read {len(content)} bytes from upload")
        
        # If the uploaded file is already WAV, save directly
        if audio.content_type == 'audio/wav' or audio.content_type == 'audio/wave':
            with open(filepath, 'wb') as f:
                f.write(content)
        else:
            # For other formats, we'll assume they're already in a compatible format
            # In production, you might want to convert using a library like pydub
            logger.warning(f"⚠️ Non-WAV format received: {audio.content_type}, saving as-is")
            with open(filepath, 'wb') as f:
                f.write(content)
        
        file_size = os.path.getsize(filepath)
        logger.info(f"✅ Client recording saved: {filename} ({file_size} bytes)")
        
        # Start transcription in background thread (only if model is available)
        if transcription_model:
            logger.info(f"🎯 Starting background transcription for uploaded file: {filename}")
            transcription_thread = threading.Thread(
                target=transcribe_audio_async, 
                args=(filename,),
                daemon=True
            )
            transcription_thread.start()
        else:
            logger.warning("⚠️ Transcription skipped - model not available")
        
        return {
            "message": "Recording uploaded and saved",
            "filename": filename,
            "size": file_size,
            "transcription_started": transcription_model is not None
        }
    except Exception as e:
        logger.error(f"❌ Error uploading recording: {e}")
        logger.error(f"❌ Full traceback: {traceback.format_exc()}")
        raise HTTPException(status_code=500, detail=f"Error uploading recording: {str(e)}")

@app.post("/api/upload-scene")
async def upload_scene(
    audio: UploadFile = File(...),
    scene_number: int = Form(...),
    timestamp: str = Form(...)
):
    """Upload scene recording from client-side continuous recording"""
    try:
        logger.info(f"🎭 Received scene upload - scene: {scene_number}, timestamp: {timestamp}, content_type: {audio.content_type}, size: {audio.size}")
        
        # Validate file type
        if not audio.content_type.startswith('audio/'):
            logger.error(f"❌ Invalid content type for scene: {audio.content_type}")
            raise HTTPException(status_code=400, detail="File must be an audio file")
        
        # Generate scene filename
        filename = f"scene_{timestamp}_sz{scene_number:03d}.wav"
        filepath = os.path.join("recordings", filename)
        logger.info(f"💾 Saving scene to: {filepath}")
        
        # Save uploaded file
        content = await audio.read()
        logger.info(f"📊 Read {len(content)} bytes from scene upload")
        
        with open(filepath, 'wb') as f:
            f.write(content)
        
        file_size = os.path.getsize(filepath)
        logger.info(f"✅ Client scene saved: {filename} ({file_size} bytes)")
        
        # Queue for transcription
        if transcription_model:
            transcription_queue.put(filename)
            logger.info(f"📝 Scene queued for transcription: {filename} (queue size: {transcription_queue.qsize()})")
        else:
            logger.warning("⚠️ Transcription skipped - model not available")
        
        return {
            "message": "Scene uploaded and saved",
            "filename": filename,
            "size": file_size,
            "transcription_queued": transcription_model is not None,
            "queue_size": transcription_queue.qsize()
        }
    except Exception as e:
        logger.error(f"❌ Error uploading scene: {e}")
        logger.error(f"❌ Full traceback: {traceback.format_exc()}")
        raise HTTPException(status_code=500, detail=f"Error uploading scene: {str(e)}")

@app.get("/api/client-recording-status")
async def get_client_recording_status():
    """Get recording status for client-side recording (simplified)"""
    return {
        "transcription_available": transcription_model is not None,
        "is_transcribing": is_transcribing,
        "transcription_queue_size": transcription_queue.qsize(),
        "cuda_available": cuda_available,
        "device_info": "CUDA" if cuda_available else "CPU"
    }

# ============= NEW SCENE VISUALIZATION ENDPOINTS =============

@app.get("/api/latest-scene")
async def get_latest_scene():
    """Get the latest scene with generated image and metadata"""
    try:
        # Find all scene metadata files (these are created when scenes are complete)
        scene_dir = Path("scene")
        scene_metadata_files = sorted([f for f in scene_dir.glob("scene_*_metadata.json")], 
                                     key=lambda x: x.stat().st_mtime, reverse=True)
        
        if not scene_metadata_files:
            logger.info("🎭 No scene metadata files found")
            raise HTTPException(status_code=404, detail="No scenes available")
        
        # Check for corresponding image files
        for metadata_file in scene_metadata_files:
            # Extract scene name (e.g., scene_20250620_sz001)
            scene_name = metadata_file.stem.replace("_metadata", "")
            
            # Check if image exists
            image_path = Path("scene") / f"{scene_name}_image.png"
            
            logger.info(f"🔍 Checking scene: {scene_name}")
            logger.info(f"   - Metadata exists: {metadata_file.exists()}")
            logger.info(f"   - Image exists: {image_path.exists()}")
            
            if image_path.exists():
                # Found complete scene, load metadata
                try:
                    with open(metadata_file, 'r', encoding='utf-8') as f:
                        metadata = json.load(f)
                    
                    # Add paths for frontend
                    metadata['image_url'] = f"/api/scene-image/{scene_name}_image.png"
                    
                    logger.info(f"✅ Returning complete scene: {scene_name}")
                    return {
                        "scene_name": scene_name,
                        "metadata": metadata,
                        "has_image": True,
                        "scene_timestamp": datetime.fromtimestamp(metadata_file.stat().st_mtime).isoformat()
                    }
                except Exception as e:
                    logger.error(f"❌ Error reading metadata for {scene_name}: {e}")
                    continue
        
        # No complete scene found yet
        logger.info("🎭 No complete scene (with image) found yet")
        raise HTTPException(status_code=202, detail="Scene image generation in progress")
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"❌ Error getting latest scene: {e}")
        logger.error(f"❌ Full traceback: {traceback.format_exc()}")
        raise HTTPException(status_code=500, detail=f"Error getting latest scene: {str(e)}")

@app.get("/api/scene-image/{filename}")
async def get_scene_image(filename: str):
    """Serve scene image file"""
    try:
        # Security check
        if ".." in filename or "/" in filename or "\\" in filename:
            raise HTTPException(status_code=400, detail="Invalid filename")
        
        image_path = Path("scene") / filename
        
        if not image_path.exists():
            logger.error(f"❌ Scene image not found: {image_path}")
            raise HTTPException(status_code=404, detail="Scene image not found")
        
        if not image_path.suffix.lower() in ['.png', '.jpg', '.jpeg']:
            raise HTTPException(status_code=400, detail="Only image files are allowed")
        
        return FileResponse(image_path, media_type="image/png", filename=filename)
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"❌ Error serving scene image: {e}")
        raise HTTPException(status_code=500, detail=f"Error serving scene image: {str(e)}")

@app.get("/api/scene-status")
async def get_scene_status():
    """Get current scene processing status"""
    try:
        # Count complete scenes
        scene_dir = Path("scene")
        
        scene_images = list(scene_dir.glob("scene_*_image.png"))
        scene_metadata = list(scene_dir.glob("scene_*_metadata.json"))
        
        # Find latest scene (based on metadata files)
        latest_scene = None
        if scene_metadata:
            latest = max(scene_metadata, key=lambda x: x.stat().st_mtime)
            latest_scene = latest.stem.replace("_metadata", "")
        
        # Check if latest has image
        latest_has_image = False
        if latest_scene:
            image_path = scene_dir / f"{latest_scene}_image.png"
            latest_has_image = image_path.exists()
        
        # Count complete scenes
        complete_scenes = 0
        for metadata_file in scene_metadata:
            scene_name = metadata_file.stem.replace("_metadata", "")
            image_path = scene_dir / f"{scene_name}_image.png"
            if image_path.exists():
                complete_scenes += 1
        
        return {
            "total_images": len(scene_images),
            "total_metadata": len(scene_metadata),
            "complete_scenes": complete_scenes,
            "latest_scene": latest_scene,
            "latest_has_image": latest_has_image,
            "is_transcribing": is_transcribing,
            "transcription_queue_size": transcription_queue.qsize()
        }
        
    except Exception as e:
        logger.error(f"❌ Error getting scene status: {e}")
        raise HTTPException(status_code=500, detail=f"Error getting scene status: {str(e)}")

@app.get("/api/all-scenes")
async def get_all_scenes():
    """Get list of all available scenes with their status"""
    try:
        scene_dir = Path("scene")
        
        scenes = []
        
        # Find all scene metadata files - these represent complete scenes
        for metadata_file in scene_dir.glob("scene_*_metadata.json"):
            scene_name = metadata_file.stem.replace("_metadata", "")
            
            # Check for image
            image_path = scene_dir / f"{scene_name}_image.png"
            
            scene_info = {
                "scene_name": scene_name,
                "metadata_file": metadata_file.name,
                "metadata_created": datetime.fromtimestamp(metadata_file.stat().st_mtime).isoformat(),
                "has_metadata": True,  # Always true since we found the metadata file
                "has_image": image_path.exists(),
                "is_complete": image_path.exists()  # Complete if both metadata and image exist
            }
            
            # Add image creation time if available  
            if image_path.exists():
                scene_info["image_created"] = datetime.fromtimestamp(image_path.stat().st_mtime).isoformat()
            
            scenes.append(scene_info)
        
        # Sort by metadata creation time (newest first)
        scenes.sort(key=lambda x: x['metadata_created'], reverse=True)
        
        return {
            "scenes": scenes,
            "total": len(scenes),
            "complete": len([s for s in scenes if s['is_complete']])
        }
        
    except Exception as e:
        logger.error(f"❌ Error getting all scenes: {e}")
        raise HTTPException(status_code=500, detail=f"Error getting all scenes: {str(e)}")

@app.get("/api/scene/{scene_name}")
async def get_specific_scene(scene_name: str):
    """Get a specific scene by name with metadata and image info"""
    try:
        logger.info(f"🔍 DEBUG: get_specific_scene called with scene_name: {scene_name}")
        
        # Security check
        if ".." in scene_name or "/" in scene_name or "\\" in scene_name:
            logger.error(f"❌ DEBUG: Invalid scene name: {scene_name}")
            raise HTTPException(status_code=400, detail="Invalid scene name")
        
        # Check if scene files exist - only need metadata and image, not transcript
        metadata_path = Path("scene") / f"{scene_name}_metadata.json"
        image_path = Path("scene") / f"{scene_name}_image.png"
        
        logger.info(f"🔍 DEBUG: File check for scene {scene_name}:")
        logger.info(f"   - Metadata: {metadata_path} exists: {metadata_path.exists()}")
        logger.info(f"   - Image: {image_path} exists: {image_path.exists()}")
        
        # Check all files in scene directory for debugging
        logger.info(f"🔍 DEBUG: Files in scene/:")
        for f in Path("scene").glob("*"):
            logger.info(f"   - {f.name}")
        
        if not metadata_path.exists() or not image_path.exists():
            logger.warning(f"⚠️ DEBUG: Scene metadata or image missing:")
            logger.warning(f"   - Metadata exists: {metadata_path.exists()}")
            logger.warning(f"   - Image exists: {image_path.exists()}")
            raise HTTPException(status_code=202, detail="Scene image generation in progress")
        
        # Load metadata
        try:
            logger.info(f"🔍 DEBUG: Loading metadata from: {metadata_path}")
            with open(metadata_path, 'r', encoding='utf-8') as f:
                metadata = json.load(f)
            
            logger.info(f"🔍 DEBUG: Metadata loaded successfully, keys: {list(metadata.keys())}")
            
            # Add paths for frontend
            metadata['image_url'] = f"/api/scene-image/{scene_name}_image.png"
            
            logger.info(f"✅ DEBUG: Returning scene data for: {scene_name}")
            return {
                "scene_name": scene_name,
                "metadata": metadata,
                "has_image": True,
                "scene_timestamp": datetime.fromtimestamp(metadata_path.stat().st_mtime).isoformat()
            }
        except Exception as e:
            logger.error(f"❌ DEBUG: Error reading metadata for {scene_name}: {e}")
            logger.error(f"❌ DEBUG: Full traceback: {traceback.format_exc()}")
            raise HTTPException(status_code=500, detail=f"Error reading scene metadata: {str(e)}")
            
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"❌ DEBUG: Unexpected error getting specific scene {scene_name}: {e}")
        logger.error(f"❌ DEBUG: Full traceback: {traceback.format_exc()}")
        raise HTTPException(status_code=500, detail=f"Error getting scene: {str(e)}")

if __name__ == "__main__":
    uvicorn.run("main:app", host="0.0.0.0", port=8000, reload=True, log_level="warning") 