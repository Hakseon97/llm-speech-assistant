import os
import json
import base64
import websocket
import threading
import sounddevice as sd
import numpy as np
from datetime import datetime

# 기본 설정
CONFIG_FILE = "config.yaml"
LOG_FILE = "conversation.txt"
DEBUG_LOG_FILE = "debug_log.txt"
SAMPLE_RATE = 24000
CHUNK = 1024

# 설정 로드
def load_config(file_path):
    try:
        import yaml
        with open(file_path, 'r') as f:
            config = yaml.safe_load(f) or {}
        log("설정 파일 로드 성공", "DEBUG")
    except Exception as e:
        log(f"설정 파일 로드 실패: {e}, 기본값 사용", "WARNING")
        config = {}
    return {
        "OPENAI_API_KEY": config.get("OPENAI_API_KEY", os.environ.get("OPENAI_API_KEY", "")),
        "REALTIME_API_URL": config.get("REALTIME_API_URL", "wss://api.openai.com/v1/realtime?model="),
        "MODEL_NAME": config.get("MODEL_NAME", "gpt-4o-mini-realtime-preview-2024-12-17")
    }

# 로그 함수
def log(message, level="INFO", debug_file=True):
    timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    msg = f"[{timestamp}] {level}: {message}"
    print(msg)
    if debug_file:
        with open(DEBUG_LOG_FILE, "a", encoding="utf-8") as f:
            f.write(msg + "\n")

# 설정 초기화
config = load_config(CONFIG_FILE)
OPENAI_API_KEY = config["OPENAI_API_KEY"]
WS_URL = f"{config['REALTIME_API_URL']}{config['MODEL_NAME']}"
HEADERS = [
    "Authorization: Bearer " + OPENAI_API_KEY,
    "OpenAI-Beta: realtime=v1"
]

if not OPENAI_API_KEY:
    log("API 키가 없습니다. 환경 변수나 config.yaml을 확인하세요.", "ERROR")
    exit(1)

# 대화 저장
def save_conversation(role, text):
    with open(LOG_FILE, "a", encoding="utf-8") as f:
        timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        f.write(f"[{timestamp}] {role}: {text}\n")

# 오디오 출력 스트림
try:
    output_stream = sd.OutputStream(
        samplerate=SAMPLE_RATE,
        channels=1,
        dtype="int16"
    )
    output_stream.start()
    log("오디오 출력 스트림 초기화 성공", "DEBUG")
except Exception as e:
    log(f"오디오 출력 스트림 초기화 실패: {e}", "ERROR")
    exit(1)

# WebSocket 핸들러
def on_open(ws):
    log("Realtime API에 연결됨! 대화를 시작하세요...")
    session_config = {
        "type": "session.update",
        "session": {
            "modalities": ["text", "audio"],  # 최소 설정 유지
            "input_audio_transcription": {"model": "whisper-1"},
            "voice": "alloy"
        }
    }
    log(f"세션 설정 전송: {json.dumps(session_config)}", "DEBUG")
    ws.send(json.dumps(session_config))
    start_audio_input(ws)

def on_message(ws, message):
    try:
        data = json.loads(message)
        event_type = data.get("type")
        log(f"수신 이벤트: {event_type}", "DEBUG")

        if event_type == "conversation.item.created":
            item = data["item"]
            if item["type"] == "message":
                role = "You" if item["role"] == "user" else "AI"
                content = next((c["text"] for c in item.get("content", []) if c.get("type") == "text"), "")
                if content:
                    log(f"{role}: {content}")
                    save_conversation(role, content)
        elif event_type == "input_audio_buffer.speech_started":
            log("음성 감지됨...", "DEBUG")
        elif event_type == "input_audio_buffer.committed":
            log("음성 처리됨.", "DEBUG")
        elif event_type == "response.audio.delta":
            log("TTS 오디오 데이터 수신", "DEBUG")
            audio_chunk = base64.b64decode(data["delta"])
            log(f"오디오 청크 크기: {len(audio_chunk)} bytes", "DEBUG")
            audio_data = np.frombuffer(audio_chunk, dtype=np.int16)
            log(f"오디오 데이터 변환: {audio_data.shape}", "DEBUG")
            output_stream.write(audio_data)
            log("오디오 재생 시도", "DEBUG")
        elif event_type == "response.created":
            log(f"응답 생성: {json.dumps(data)}", "DEBUG")
        elif event_type == "response.done":
            log(f"응답 완료: {json.dumps(data)}", "DEBUG")
        elif event_type == "error":
            log(f"API 오류: {json.dumps(data)}", "ERROR")
    except Exception as e:
        log(f"메시지 처리 오류: {e}", "ERROR")

def on_error(ws, error):
    log(f"WebSocket 오류: {error}", "ERROR")

def on_close(ws, close_status_code, close_msg):
    log(f"연결 종료: {close_status_code} - {close_msg}")
    output_stream.stop()
    output_stream.close()
    if audio_stream and audio_stream.active:
        audio_stream.stop()
        audio_stream.close()

# 오디오 입력 스트리밍
audio_stream = None
def start_audio_input(ws):
    def audio_callback(indata, frames, time, status):
        if status:
            log(f"오디오 상태: {status}", "WARNING")
        audio_event = {
            "type": "input_audio_buffer.append",
            "audio": base64.b64encode(indata.tobytes()).decode("utf-8")
        }
        ws.send(json.dumps(audio_event))

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

# WebSocket 실행
ws = websocket.WebSocketApp(
    WS_URL,
    header=HEADERS,
    on_open=on_open,
    on_message=on_message,
    on_error=on_error,
    on_close=on_close
)

# 메인 함수
def main():
    log("프로그램 시작")
    ws_thread = threading.Thread(target=ws.run_forever)
    ws_thread.daemon = True
    ws_thread.start()

    try:
        while True:
            threading.Event().wait()
    except KeyboardInterrupt:
        log("종료 요청 수신")
        ws.close()
        if audio_stream and audio_stream.active:
            audio_stream.stop()
            audio_stream.close()
        output_stream.stop()
        output_stream.close()
        log("프로그램 종료")

if __name__ == "__main__":
    main()