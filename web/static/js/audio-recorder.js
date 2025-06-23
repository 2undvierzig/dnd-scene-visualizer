// Audio Recorder Module - Client-seitige Audioaufnahme
class AudioRecorder {
    constructor() {
        this.mediaRecorder = null;
        this.audioChunks = [];
        this.stream = null;
        this.isRecording = false;
        this.recordingStartTime = null;
        this.maxDuration = 60; // Max duration in seconds
        this.onDataAvailable = null;
        this.onStop = null;
    }

    // Enumerate all audio input devices
    async getAudioDevices() {
        try {
            // Request permission first
            await navigator.mediaDevices.getUserMedia({ audio: true });
            
            // Get all devices
            const devices = await navigator.mediaDevices.enumerateDevices();
            
            // Filter audio input devices
            const audioInputs = devices.filter(device => device.kind === 'audioinput');
            
            console.log('Found audio devices:', audioInputs);
            return audioInputs;
        } catch (error) {
            console.error('Error getting audio devices:', error);
            throw new Error('Fehler beim Abrufen der Audiogeräte: ' + error.message);
        }
    }

    // Start recording with specific device
    async startRecording(deviceId = null, duration = 10) {
        if (this.isRecording) {
            throw new Error('Aufnahme läuft bereits');
        }

        try {
            // Set constraints
            const constraints = {
                audio: {
                    echoCancellation: true,
                    noiseSuppression: true,
                    autoGainControl: true
                }
            };

            // Add specific device if provided
            if (deviceId) {
                constraints.audio.deviceId = { exact: deviceId };
            }

            // Get user media
            this.stream = await navigator.mediaDevices.getUserMedia(constraints);
            
            // Create MediaRecorder with preferred mime type
            const mimeType = this.getSupportedMimeType();
            const options = { mimeType };
            
            this.mediaRecorder = new MediaRecorder(this.stream, options);
            this.audioChunks = [];
            
            // Set up event handlers
            this.mediaRecorder.ondataavailable = (event) => {
                if (event.data.size > 0) {
                    this.audioChunks.push(event.data);
                    if (this.onDataAvailable) {
                        this.onDataAvailable(event.data);
                    }
                }
            };

            this.mediaRecorder.onstop = async () => {
                console.log('[AudioRecorder] MediaRecorder stopped, chunks:', this.audioChunks.length);
                
                // Create blob from chunks
                const audioBlob = new Blob(this.audioChunks, { type: mimeType });
                console.log('[AudioRecorder] Created blob:', audioBlob.size, 'bytes, type:', audioBlob.type);
                
                // Convert to WAV format for compatibility
                const wavBlob = await this.convertToWav(audioBlob);
                console.log('[AudioRecorder] Converted to WAV:', wavBlob.size, 'bytes');
                
                // Clean up
                this.stopStream();
                
                if (this.onStop) {
                    console.log('[AudioRecorder] Calling onStop callback');
                    this.onStop(wavBlob);
                }
            };

            // Start recording
            this.mediaRecorder.start();
            this.isRecording = true;
            this.recordingStartTime = Date.now();
            
            // Auto-stop after duration
            if (duration && duration > 0) {
                this.maxDuration = Math.min(duration, 600); // Max 10 minutes
                setTimeout(() => {
                    if (this.isRecording) {
                        this.stopRecording();
                    }
                }, this.maxDuration * 1000);
            }

            console.log('Recording started with device:', deviceId);
            return true;
        } catch (error) {
            console.error('Error starting recording:', error);
            this.stopStream();
            throw new Error('Fehler beim Starten der Aufnahme: ' + error.message);
        }
    }

    // Stop recording
    stopRecording() {
        if (!this.isRecording || !this.mediaRecorder) {
            throw new Error('Keine aktive Aufnahme');
        }

        this.isRecording = false;
        this.mediaRecorder.stop();
        
        const duration = (Date.now() - this.recordingStartTime) / 1000;
        console.log('Recording stopped. Duration:', duration, 'seconds');
        
        return duration;
    }

    // Get supported MIME type
    getSupportedMimeType() {
        const types = [
            'audio/webm;codecs=opus',
            'audio/webm',
            'audio/ogg;codecs=opus',
            'audio/ogg',
            'audio/mp4',
            'audio/wav'
        ];

        for (const type of types) {
            if (MediaRecorder.isTypeSupported(type)) {
                console.log('Using MIME type:', type);
                return type;
            }
        }

        // Default fallback
        return 'audio/webm';
    }

    // Convert blob to WAV format using Web Audio API
    async convertToWav(blob) {
        console.log('[AudioRecorder] Starting WAV conversion for blob size:', blob.size);
        return new Promise(async (resolve, reject) => {
            try {
                // Create audio context
                const audioContext = new (window.AudioContext || window.webkitAudioContext)();
                console.log('[AudioRecorder] AudioContext created, sample rate:', audioContext.sampleRate);
                
                // Decode audio data
                const arrayBuffer = await blob.arrayBuffer();
                console.log('[AudioRecorder] ArrayBuffer size:', arrayBuffer.byteLength);
                
                const audioBuffer = await audioContext.decodeAudioData(arrayBuffer);
                console.log('[AudioRecorder] Audio decoded - duration:', audioBuffer.duration, 
                           'channels:', audioBuffer.numberOfChannels, 
                           'sample rate:', audioBuffer.sampleRate);
                
                // Convert to WAV
                const wavBuffer = this.audioBufferToWav(audioBuffer);
                const wavBlob = new Blob([wavBuffer], { type: 'audio/wav' });
                console.log('[AudioRecorder] WAV conversion complete, size:', wavBlob.size);
                
                audioContext.close();
                resolve(wavBlob);
            } catch (error) {
                console.error('[AudioRecorder] Error converting to WAV:', error);
                console.log('[AudioRecorder] Falling back to original blob');
                // Fallback: return original blob
                resolve(blob);
            }
        });
    }

    // Convert AudioBuffer to WAV format
    audioBufferToWav(buffer) {
        const numOfChan = buffer.numberOfChannels;
        const length = buffer.length * numOfChan * 2 + 44;
        const out = new ArrayBuffer(length);
        const view = new DataView(out);
        const channels = [];
        let sample;
        let offset = 0;
        let pos = 0;

        // Write WAV header
        const setUint16 = (data) => {
            view.setUint16(pos, data, true);
            pos += 2;
        };

        const setUint32 = (data) => {
            view.setUint32(pos, data, true);
            pos += 4;
        };

        // Write WAVE header
        setUint32(0x46464952); // "RIFF"
        setUint32(length - 8); // file length - 8
        setUint32(0x45564157); // "WAVE"

        setUint32(0x20746d66); // "fmt " chunk
        setUint32(16); // length = 16
        setUint16(1); // PCM (uncompressed)
        setUint16(numOfChan);
        setUint32(buffer.sampleRate);
        setUint32(buffer.sampleRate * 2 * numOfChan); // avg. bytes/sec
        setUint16(numOfChan * 2); // block-align
        setUint16(16); // 16-bit

        setUint32(0x61746164); // "data" - chunk
        setUint32(length - pos - 4); // chunk length

        // Write interleaved data
        for (let i = 0; i < buffer.numberOfChannels; i++) {
            channels.push(buffer.getChannelData(i));
        }

        while (pos < length) {
            for (let i = 0; i < numOfChan; i++) {
                sample = Math.max(-1, Math.min(1, channels[i][offset])); // clamp
                sample = (sample < 0 ? sample * 0x8000 : sample * 0x7FFF) | 0; // scale to 16-bit signed int
                view.setInt16(pos, sample, true); // write 16-bit sample
                pos += 2;
            }
            offset++;
        }

        return out;
    }

    // Clean up resources
    stopStream() {
        if (this.stream) {
            this.stream.getTracks().forEach(track => track.stop());
            this.stream = null;
        }
    }

    // Check if recording is active
    getIsRecording() {
        return this.isRecording;
    }

    // Get recording duration
    getRecordingDuration() {
        if (!this.isRecording || !this.recordingStartTime) {
            return 0;
        }
        return (Date.now() - this.recordingStartTime) / 1000;
    }
}

// Continuous recording manager
class ContinuousRecorder {
    constructor(sceneDurationMinutes = 1) {
        this.recorder = new AudioRecorder();
        this.isRunning = false;
        this.currentScene = 0;
        this.sceneDuration = sceneDurationMinutes * 60; // Convert to seconds
        this.deviceId = null;
        this.onSceneComplete = null;
        this.stats = {
            totalScenes: 0,
            totalDuration: 0,
            startTime: null
        };
    }

    async start(deviceId, sceneDurationMinutes) {
        if (this.isRunning) {
            throw new Error('Kontinuierliche Aufnahme läuft bereits');
        }

        this.deviceId = deviceId;
        this.sceneDuration = sceneDurationMinutes * 60;
        this.isRunning = true;
        this.stats.startTime = new Date();
        this.currentScene = 0;

        console.log('Starting continuous recording:', {
            deviceId,
            sceneDuration: this.sceneDuration
        });

        // Start recording loop
        this.recordNextScene();
    }

    async recordNextScene() {
        if (!this.isRunning) {
            return;
        }

        try {
            this.currentScene++;
            const sceneNumber = this.currentScene;
            
            console.log(`[ContinuousRecorder] Recording scene ${sceneNumber}... Duration: ${this.sceneDuration}s`);

            // Set up recorder for this scene
            this.recorder.onStop = async (blob) => {
                console.log(`[ContinuousRecorder] Scene ${sceneNumber} recording stopped`);
                
                // Handle completed scene
                const now = new Date();
                const timestamp = now.getFullYear().toString() +
                    (now.getMonth() + 1).toString().padStart(2, '0') +
                    now.getDate().toString().padStart(2, '0') + '_' +
                    now.getHours().toString().padStart(2, '0') +
                    now.getMinutes().toString().padStart(2, '0') +
                    now.getSeconds().toString().padStart(2, '0');
                const filename = `scene_${timestamp}_sz${String(sceneNumber).padStart(3, '0')}.wav`;
                
                console.log(`[ContinuousRecorder] Scene ${sceneNumber} - Filename: ${filename}, Blob size: ${blob.size}`);
                
                // Update stats
                this.stats.totalScenes++;
                this.stats.totalDuration += this.sceneDuration;

                // Trigger callback
                if (this.onSceneComplete) {
                    console.log(`[ContinuousRecorder] Calling onSceneComplete for scene ${sceneNumber}`);
                    await this.onSceneComplete(blob, filename, sceneNumber);
                } else {
                    console.error('[ContinuousRecorder] No onSceneComplete callback set!');
                }

                // Start next scene if still running
                if (this.isRunning) {
                    console.log('[ContinuousRecorder] Starting next scene...');
                    // Small delay between scenes
                    setTimeout(() => this.recordNextScene(), 100);
                } else {
                    console.log('[ContinuousRecorder] Recording stopped, not starting next scene');
                }
            };

            // Start recording this scene
            await this.recorder.startRecording(this.deviceId, this.sceneDuration);

        } catch (error) {
            console.error('Error recording scene:', error);
            this.isRunning = false;
            throw error;
        }
    }

    stop() {
        console.log('[ContinuousRecorder] Stopping continuous recording...');
        
        // Always set running to false first
        this.isRunning = false;
        
        try {
            // Stop current recording if active
            if (this.recorder && this.recorder.getIsRecording()) {
                console.log('[ContinuousRecorder] Stopping active recording...');
                this.recorder.stopRecording();
            } else {
                console.log('[ContinuousRecorder] No active recording to stop');
            }
            
            // Clear any callbacks to prevent further scene processing
            this.recorder.onStop = null;
            
            // Clean up recorder stream
            if (this.recorder) {
                this.recorder.stopStream();
            }
            
        } catch (error) {
            console.error('[ContinuousRecorder] Error during stop (continuing anyway):', error);
        }

        console.log('[ContinuousRecorder] Continuous recording stopped successfully. Stats:', this.stats);
        return this.stats;
    }
    
    // Force stop - for emergency situations
    forceStop() {
        console.log('[ContinuousRecorder] Force stopping continuous recording...');
        
        this.isRunning = false;
        this.currentScene = 0;
        
        try {
            if (this.recorder) {
                // Clear callbacks
                this.recorder.onStop = null;
                this.recorder.onDataAvailable = null;
                
                // Stop media recorder
                if (this.recorder.mediaRecorder && this.recorder.mediaRecorder.state !== 'inactive') {
                    this.recorder.mediaRecorder.stop();
                }
                
                // Stop stream
                this.recorder.stopStream();
                
                // Reset recorder state
                this.recorder.isRecording = false;
                this.recorder.audioChunks = [];
            }
        } catch (error) {
            console.error('[ContinuousRecorder] Error during force stop (ignoring):', error);
        }
        
        // Reset stats
        const finalStats = { ...this.stats };
        this.stats = {
            totalScenes: 0,
            totalDuration: 0,
            startTime: null
        };
        
        console.log('[ContinuousRecorder] Force stop completed');
        return finalStats;
    }

    getStats() {
        return {
            ...this.stats,
            currentScene: this.currentScene,
            isRunning: this.isRunning
        };
    }
}

// Export for use in main application
window.AudioRecorder = AudioRecorder;
window.ContinuousRecorder = ContinuousRecorder; 