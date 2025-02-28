import os
import json
import base64
import websocket
import threading
import sounddevice as sd
import numpy as np
import yaml
import time
from datetime import datetime

# 1. 전역 설정
CONFIG_FILE = "config.yaml"
CONVERSATION_DIR = "conversations"
DEBUG_LOG_FILE = "debug_log.txt"
SAMPLE_RATE = 24000
CHUNK = 1024
MAX_RECONNECT_ATTEMPTS = 5
RECONNECT_DELAY = 3
ACTIVATION_KEYWORDS = ["Alice"]
TERMINATION_KEYWORDS = ["Goodbye", "Stop", "Exit", "I'm done talking"]

def load_config(file_path="config.yaml"):
    with open(file_path, "r", encoding='utf-8') as f:
        return yaml.safe_load(f)
    
def log(message, level="INFO", debug_file=True):
    timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    msg = f"[{timestamp}] {level}: {message}"
    if level == "INFO":
        print(message)
    if debug_file:
        with open(DEBUG_LOG_FILE, "a", encoding="utf-8") as f:
            f.write(msg + "\n")

config = load_config(CONFIG_FILE)
OPENAI_API_KEY = config["OPENAI_API_KEY"]
WS_URL = f"{config['REALTIME_API_URL']}{config['MODEL_NAME']}"
INSTRUCTIONS = config["INSTRUCTIONS"]
HEADERS = [
    "Authorization: Bearer " + OPENAI_API_KEY,
    "OpenAI-Beta: realtime=v1"
]

if not OPENAI_API_KEY:
    log("API 키가 없습니다. 환경 변수나 config.yaml을 확인하세요.", "ERROR")
    exit(1)

# 전역 오디오 변수
output_stream = sd.OutputStream(samplerate=SAMPLE_RATE, channels=1, dtype="int16")
output_stream.start()
audio_stream = None
is_conversation_active = False
is_speaking = False

# 4. 추가 유틸리티 함수
def get_conversation_file():
    date_str = datetime.now().strftime("%Y%m%d")
    os.makedirs(CONVERSATION_DIR, exist_ok=True)
    return os.path.join(CONVERSATION_DIR, f"{date_str}_conversation.txt")

def save_conversation(role, text):
    filename = get_conversation_file()
    timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    log_entry = f"[{timestamp}] {role}: {text}"
    with open(filename, "a", encoding="utf-8") as f:
        f.write(log_entry + "\n")

# 5. WebSocket 관리 클래스
class WebSocketManager:
    def __init__(self):
        self.reconnect_attempts = 0
        self.ws = None

    def start_websocket(self):
        """WebSocket 연결을 초기화하고 실행"""
        try:
            log("WebSocket 연결 시작", "INFO")
            self.ws = websocket.WebSocketApp(
                WS_URL,
                header=HEADERS,
                on_open=self.on_open,
                on_message=on_message,
                on_error=self.on_error,
                on_close=self.on_close
            )
            self.reconnect_attempts = 0
            ws_thread = threading.Thread(target=self.ws.run_forever)
            ws_thread.daemon = True
            ws_thread.start()
        except Exception as e:
            log(f"WebSocket 연결 실패: {e}", "ERROR")
            self.reconnect()

    def on_open(self, ws):
        log("Realtime API에 연결됨! 대화를 시작하세요...", "INFO")
        session_config = {
            "type": "session.update",
            "session": {
                "modalities": ["text", "audio"],
                "input_audio_transcription": {"model": "whisper-1", "language": "en"},
                "voice": "alloy",
                "turn_detection": {
                    "type": "server_vad",
                    "threshold": 0.7,
                    "prefix_padding_ms": 300,
                    "silence_duration_ms": 500
                },
                "instructions": INSTRUCTIONS
            }
        }
        log(f"세션 설정 전송: {json.dumps(session_config)}", "DEBUG")
        ws.send(json.dumps(session_config))
        start_audio_input(ws)

    def on_error(self, ws, error):
        log(f"WebSocket 오류: {error}", "ERROR")

    def on_close(self, ws, close_status_code, close_msg):
        log(f"연결 종료: {close_status_code} - {close_msg}", "INFO")
        cleanup()
        self.reconnect()

    def reconnect(self):
        if self.reconnect_attempts < MAX_RECONNECT_ATTEMPTS:
            self.reconnect_attempts += 1
            log(f"{RECONNECT_DELAY}초 후 WebSocket 재연결 시도... ({self.reconnect_attempts}/{MAX_RECONNECT_ATTEMPTS})", "WARNING")
            if self.ws:
                self.ws.close()
            threading.Timer(RECONNECT_DELAY, self.start_websocket).start()
        else:
            log("최대 재연결 횟수를 초과하여 종료합니다.", "ERROR")

    # def stop_ai_speech(self):
    #     global output_stream, is_speaking
    #     if is_speaking:
    #         log("AI 음성 강제 중단 요청", "INFO")
    #         stop_event = {"type": "response.audio.stop"}
    #         self.ws.send(json.dumps(stop_event))
    #         is_speaking = False

# 6. 오디오 및 WebSocket 콜백 함수
def on_message(ws, message):
    global is_speaking, is_conversation_active
    try:
        data = json.loads(message)
        event_type = data.get("type")
        log(f"수신 이벤트: {event_type}", "DEBUG")
        log(f"이벤트 데이터: {json.dumps(data, indent=2)}", "DEBUG")

        if event_type == "conversation.item.created":
            item = data["item"]
            if item["type"] == "message" and is_conversation_active:
                role = "You" if item["role"] == "user" else "AI"
                content = next((c["text"] for c in item.get("content", []) if c.get("type") == "text"), "")
                if content:
                    log(f"{role}: {content}", "INFO")
                    save_conversation(role, content)
        elif event_type == "input_audio_buffer.speech_started":
            log("음성 감지됨...", "DEBUG")
        elif event_type == "conversation.item.input_audio_transcription.completed":
            transcript = data.get("transcript", "")
            if transcript and not is_speaking:
                log(f"You: {transcript}", "INFO")
                if is_conversation_active:
                    save_conversation("You", transcript)
                if any(keyword in transcript for keyword in ACTIVATION_KEYWORDS) \
                    and not is_conversation_active:
                    log("대화가 시작되었습니다.", "INFO")
                    is_conversation_active = True
                    ws.send(json.dumps({
                        "type": "response.create",
                        "response": {
                            "content": [{"type": "text", "text": "yes. master?"}]
                            }
                        }))
                if any(keyword in transcript for keyword in TERMINATION_KEYWORDS) \
                    and is_conversation_active:
                    log("대화가 종료되었습니다.", "INFO")
                    is_conversation_active = False
                    ws.send(json.dumps({
                        "type": "response.create",
                        "response": {
                            "content": [{"type": "text", "text": "Goodbye."}]
                            }
                        }))
        elif event_type == "response.audio.delta":
            if is_conversation_active:
                log("TTS 오디오 데이터 수신", "DEBUG")
                is_speaking = True
                audio_chunk = base64.b64decode(data["delta"])
                audio_data = np.frombuffer(audio_chunk, dtype=np.int16)
                output_stream.write(audio_data)
        elif event_type == "response.audio.done":
            log("TTS 오디오 재생 완료", "DEBUG")
            is_speaking = False
        elif event_type == "response.audio_transcript.done":
            if is_conversation_active:
                transcript = data.get("transcript", "")
                if transcript:
                    log(f"AI: {transcript}", "INFO")
                    save_conversation("AI", transcript)
        elif event_type == "error":
            log(f"API 오류: {json.dumps(data)}", "ERROR")
    except Exception as e:
        log(f"메시지 처리 오류: {e}", "ERROR")

def start_audio_input(ws):
    def audio_callback(indata, frames, time, status):
        global is_speaking
        if status:
            log(f"오디오 상태: {status}", "WARNING")
        if is_speaking:
            return
        audio_event = {
            "type": "input_audio_buffer.append",
            "audio": base64.b64encode(indata.tobytes()).decode("utf-8")
        }
        ws.send(json.dumps(audio_event))
        log("입력 오디오 전송", "DEBUG")

    global audio_stream
    try:
        audio_stream = sd.InputStream(
            samplerate=SAMPLE_RATE,
            channels=1,
            dtype="int16",
            blocksize=CHUNK,
            callback=audio_callback
        )
        audio_stream.start()
        log("오디오 입력 스트림 시작됨", "DEBUG")
    except Exception as e:
        log(f"오디오 입력 스트림 시작 실패: {e}", "ERROR")

def cleanup():
    global output_stream, audio_stream
    if output_stream and output_stream.active:
        output_stream.stop()
        output_stream.close()
    if audio_stream and audio_stream.active:
        audio_stream.abort()
        audio_stream.close()
    output_stream = sd.OutputStream(samplerate=SAMPLE_RATE, channels=1, dtype="int16")
    output_stream.start()
    audio_stream = None

# 7. 메인 함수
def main():
    log("프로그램 시작", "INFO")
    ws_manager = WebSocketManager()
    ws_manager.start_websocket()

    try:
        while True:
            threading.Event().wait()
    except KeyboardInterrupt:
        log("종료 요청 수신", "INFO")
        if ws_manager.ws:
            ws_manager.ws.close()
        cleanup()
        log("프로그램 종료", "INFO")
        exit(0)

if __name__ == "__main__":
    main()