import io
import json
import os
import sys
import time
import wave
import threading
from collections import deque
from pathlib import Path

os.environ.setdefault(
    "QTWEBENGINE_CHROMIUM_FLAGS",
    "--disable-background-timer-throttling "
    "--disable-backgrounding-occluded-windows "
    "--disable-renderer-backgrounding",
)

import numpy as np
import requests
import sounddevice as sd
import yt_dlp

from PySide6.QtCore import QObject, QTimer, QUrl, Signal, Slot
from PySide6.QtWidgets import (
    QApplication,
    QComboBox,
    QDoubleSpinBox,
    QFormLayout,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMainWindow,
    QMessageBox,
    QPushButton,
    QSpinBox,
    QTextEdit,
    QVBoxLayout,
    QWidget,
)
from PySide6.QtWebEngineCore import QWebEngineSettings
from PySide6.QtWebEngineWidgets import QWebEngineView

APP_DIR = Path(__file__).resolve().parent
CONFIG_PATH = APP_DIR / "config.json"
DEFAULT_CONFIG = {
    "audd_api_token": "",
    "audio_device": None,
    "sample_seconds": 7.0,
    "normal_interval_seconds": 7.0,
    "rapid_confirm_seconds": 3.0,
    "confirm_hits": 2,
    "sync_lead_seconds": 0.0,
    "youtube_results": 5,
    "mode": "HOT STANDBY",
}


def load_config():
    config = dict(DEFAULT_CONFIG)
    if CONFIG_PATH.exists():
        try:
            config.update(json.loads(CONFIG_PATH.read_text(encoding="utf-8")))
        except Exception:
            pass
    env_token = os.getenv("AUDD_API_TOKEN", "").strip()
    if env_token:
        config["audd_api_token"] = env_token
    return config


def save_config(config):
    CONFIG_PATH.write_text(
        json.dumps(config, ensure_ascii=False, indent=2), encoding="utf-8"
    )


def timecode_to_seconds(value):
    if value is None:
        return 0.0
    if isinstance(value, (int, float)):
        return float(value)
    text = str(value).strip()
    if not text:
        return 0.0
    parts = text.split(":")
    try:
        nums = [float(p) for p in parts]
    except ValueError:
        return 0.0
    if len(nums) == 3:
        return nums[0] * 3600 + nums[1] * 60 + nums[2]
    if len(nums) == 2:
        return nums[0] * 60 + nums[1]
    return nums[0]


def identity(match):
    return (
        (match.get("artist") or "").strip().casefold(),
        (match.get("title") or "").strip().casefold(),
    )


class Bus(QObject):
    log = Signal(str)
    status = Signal(str, str)
    match = Signal(dict)
    candidate = Signal(dict)
    ready = Signal(dict)
    sync = Signal(float)


class YouTubeSearcher:
    def __init__(self, max_results=5):
        self.max_results = max(1, int(max_results))

    @staticmethod
    def _score(item, artist, title):
        name = (item.get("title") or "").casefold()
        uploader = (
            item.get("channel")
            or item.get("uploader")
            or item.get("channel_id")
            or ""
        ).casefold()
        artist_cf = artist.casefold()
        title_cf = title.casefold()
        score = 0
        if title_cf and title_cf in name:
            score += 40
        if artist_cf and artist_cf in name:
            score += 25
        if artist_cf and artist_cf in uploader:
            score += 35
        good_terms = [
            "official music video",
            "official mv",
            "music video",
            "mv",
            "official video",
        ]
        bad_terms = [
            "reaction",
            "踊ってみた",
            "歌ってみた",
            "cover",
            "shorts",
            "short",
            "karaoke",
            "instrumental",
            "remix",
            "live",
        ]
        if any(term in name for term in good_terms):
            score += 35
        if "official" in uploader or "topic" in uploader:
            score += 15
        if any(term in name for term in bad_terms):
            score -= 25
        duration = item.get("duration")
        if isinstance(duration, (int, float)):
            if 90 <= duration <= 600:
                score += 10
            elif duration < 45 or duration > 1200:
                score -= 20
        return score

    def search(self, artist, title):
        query = f'{artist} {title} "official MV"'.strip()
        options = {
            "quiet": True,
            "no_warnings": True,
            "skip_download": True,
            "extract_flat": "in_playlist",
            "playlistend": self.max_results,
        }
        with yt_dlp.YoutubeDL(options) as ydl:
            info = ydl.extract_info(
                f"ytsearch{self.max_results}:{query}", download=False
            )
        entries = [e for e in (info or {}).get("entries", []) if e and e.get("id")]
        if not entries:
            return None
        ranked = sorted(
            entries,
            key=lambda item: self._score(item, artist, title),
            reverse=True,
        )
        best = ranked[0]
        return {
            "video_id": best.get("id", ""),
            "title": best.get("title", ""),
            "channel": best.get("channel") or best.get("uploader") or "",
            "duration": best.get("duration"),
            "webpage_url": f"https://www.youtube.com/watch?v={best.get('id', '')}",
            "query": query,
        }


class RecognitionWorker(threading.Thread):
    def __init__(self, bus, config):
        super().__init__(daemon=True)
        self.bus = bus
        self.config = dict(config)
        self.stop_event = threading.Event()
        self.audio_lock = threading.Lock()
        self.audio_chunks = deque()
        self.audio_frames = 0
        self.sample_rate = 44100
        self.channels = 1
        self.current_id = None
        self.pending_id = None
        self.pending_hits = 0
        self.video_cache = {}

    def stop(self):
        self.stop_event.set()

    def _audio_callback(self, indata, frames, time_info, status):
        if status:
            self.bus.log.emit(f"Audio: {status}")
        data = np.asarray(indata[:, 0], dtype=np.float32).copy()
        max_frames = int(
            self.sample_rate * max(12.0, float(self.config["sample_seconds"]) + 3.0)
        )
        with self.audio_lock:
            self.audio_chunks.append(data)
            self.audio_frames += len(data)
            while self.audio_frames > max_frames and self.audio_chunks:
                removed = self.audio_chunks.popleft()
                self.audio_frames -= len(removed)

    def _snapshot_wav(self):
        needed = int(self.sample_rate * float(self.config["sample_seconds"]))
        with self.audio_lock:
            if self.audio_frames < min(needed, self.sample_rate * 3):
                return None
            joined = np.concatenate(list(self.audio_chunks))
        samples = joined[-needed:]
        pcm = np.clip(samples, -1.0, 1.0)
        pcm16 = (pcm * 32767.0).astype(np.int16)
        out = io.BytesIO()
        with wave.open(out, "wb") as wf:
            wf.setnchannels(1)
            wf.setsampwidth(2)
            wf.setframerate(self.sample_rate)
            wf.writeframes(pcm16.tobytes())
        return out.getvalue()

    def _recognize(self, wav_bytes):
        token = str(self.config.get("audd_api_token") or "").strip()
        if not token:
            raise RuntimeError("AUDD_API_TOKEN が未設定です")
        response = requests.post(
            "https://api.audd.io/",
            data={
                "api_token": token,
                "return": "spotify,apple_music",
                "market": "jp",
            },
            files={"file": ("floor.wav", wav_bytes, "audio/wav")},
            timeout=25,
        )
        response.raise_for_status()
        payload = response.json()
        if payload.get("status") != "success":
            err = payload.get("error") or {}
            raise RuntimeError(
                err.get("error_message") or err.get("message") or "AudD API error"
            )
        result = payload.get("result")
        if not result:
            return None
        return {
            "artist": result.get("artist") or "",
            "title": result.get("title") or "",
            "album": result.get("album") or "",
            "timecode": result.get("timecode") or "",
            "song_link": result.get("song_link") or "",
            "spotify_url": ((result.get("spotify") or {}).get("external_urls") or {}).get(
                "spotify", ""
            ),
            "apple_music_url": (result.get("apple_music") or {}).get("url", ""),
        }

    def _find_video(self, match):
        key = identity(match)
        if key in self.video_cache:
            return self.video_cache[key]
        self.bus.status.emit("SEARCHING", "YouTube MVを検索中")
        searcher = YouTubeSearcher(self.config.get("youtube_results", 5))
        video = searcher.search(match["artist"], match["title"])
        self.video_cache[key] = video
        return video

    def _promote(self, match, video):
        self.current_id = identity(match)
        self.pending_id = None
        self.pending_hits = 0
        payload = dict(match)
        payload["video"] = video
        payload["position_seconds"] = timecode_to_seconds(match.get("timecode"))
        self.bus.ready.emit(payload)

    def _handle_match(self, match):
        self.bus.match.emit(match)
        match_id = identity(match)
        pos = (
            timecode_to_seconds(match.get("timecode"))
            + float(self.config.get("sync_lead_seconds", 0.0))
        )
        if self.current_id == match_id:
            self.pending_id = None
            self.pending_hits = 0
            self.bus.sync.emit(max(0.0, pos))
            self.bus.status.emit("READY", "現在曲を追従中")
            return float(self.config["normal_interval_seconds"])
        if self.current_id is None:
            self.bus.log.emit(
                f"初回認識: {match['artist']} - {match['title']} / {match['timecode']}"
            )
            video = self._find_video(match)
            if video:
                self._promote(match, video)
                self.bus.status.emit("READY", "初回曲を準備完了")
            else:
                self.bus.status.emit("NO VIDEO", "MV候補が見つかりません")
            return float(self.config["normal_interval_seconds"])
        if self.pending_id == match_id:
            self.pending_hits += 1
        else:
            self.pending_id = match_id
            self.pending_hits = 1
            self.bus.log.emit(
                f"曲変更候補: {match['artist']} - {match['title']} / {match['timecode']}"
            )
        video = self._find_video(match)
        candidate_payload = dict(match)
        candidate_payload["video"] = video
        candidate_payload["hits"] = self.pending_hits
        self.bus.candidate.emit(candidate_payload)
        if self.pending_hits >= int(self.config.get("confirm_hits", 2)):
            if video:
                self.bus.log.emit(
                    f"曲変更確定: {match['artist']} - {match['title']}"
                )
                self._promote(match, video)
                self.bus.status.emit("READY", "新しい曲を準備完了")
            else:
                self.bus.status.emit("NO VIDEO", "曲は確定しましたがMVがありません")
            return float(self.config["normal_interval_seconds"])
        self.bus.status.emit(
            "CANDIDATE",
            f"新曲候補を確認中 ({self.pending_hits}/{self.config.get('confirm_hits', 2)})",
        )
        return float(self.config["rapid_confirm_seconds"])

    def run(self):
        device = self.config.get("audio_device", None)
        if isinstance(device, str) and device.isdigit():
            device = int(device)
        try:
            self.bus.status.emit("LISTENING", "音声入力を監視しています")
            with sd.InputStream(
                samplerate=self.sample_rate,
                channels=self.channels,
                dtype="float32",
                device=device,
                callback=self._audio_callback,
            ):
                next_delay = 1.0
                while not self.stop_event.wait(next_delay):
                    wav_bytes = self._snapshot_wav()
                    if not wav_bytes:
                        next_delay = 1.0
                        continue
                    try:
                        self.bus.status.emit("RECOGNIZING", "AudDで曲を認識中")
                        match = self._recognize(wav_bytes)
                        if match:
                            next_delay = self._handle_match(match)
                        else:
                            self.bus.status.emit("NO MATCH", "曲を認識できませんでした")
                            next_delay = float(
                                self.config["rapid_confirm_seconds"]
                                if self.pending_id
                                else self.config["normal_interval_seconds"]
                            )
                    except Exception as exc:
                        self.bus.log.emit(f"認識エラー: {exc}")
                        self.bus.status.emit("ERROR", str(exc))
                        next_delay = max(
                            5.0, float(self.config["normal_interval_seconds"])
                        )
        except Exception as exc:
            self.bus.log.emit(f"音声入力エラー: {exc}")
            self.bus.status.emit("AUDIO ERROR", str(exc))


PLAYER_HTML = r"""
<!doctype html>
<html>
<head>
<meta charset="utf-8" />
<style>
html, body { margin:0; width:100%; height:100%; overflow:hidden; background:#000; }
#player { position:absolute; inset:0; width:100%; height:100%; }
#next {
  position:absolute; inset:0; display:none; align-items:center; justify-content:center;
  background:#000; color:#fff; font-family:Arial, sans-serif; font-weight:900;
  font-size:10vw; letter-spacing:.08em; z-index:20;
}
#next small {
  display:block; font-size:2vw; text-align:center; margin-top:1.5rem;
  letter-spacing:.3em; opacity:.7;
}
#idle {
  position:absolute; inset:0; display:flex; align-items:center; justify-content:center;
  background:#000; color:#444; font-family:Arial, sans-serif; font-size:2vw; z-index:10;
}
</style>
<script src="https://www.youtube.com/iframe_api"></script>
<script>
let player = null;
let pendingVideo = null;
let pendingSeconds = 0;
function onYouTubeIframeAPIReady() {
  player = new YT.Player('player', {
    width:'100%', height:'100%',
    playerVars: {
      autoplay: 1, controls: 0, disablekb: 1, fs: 0,
      playsinline: 1, rel: 0, modestbranding: 1
    },
    events: {
      onReady: function() {
        player.mute();
        if (pendingVideo) loadVideo(pendingVideo, pendingSeconds);
      },
      onStateChange: function(e) {
        if (e.data === YT.PlayerState.PAUSED || e.data === YT.PlayerState.CUED) {
          try { player.playVideo(); } catch(_) {}
        }
      }
    }
  });
}
function loadVideo(videoId, seconds) {
  pendingVideo = videoId;
  pendingSeconds = seconds || 0;
  document.getElementById('idle').style.display = 'none';
  if (!player || !player.loadVideoById) return;
  player.loadVideoById({videoId: videoId, startSeconds: pendingSeconds});
  try { player.mute(); player.playVideo(); } catch(_) {}
}
function seekVideo(seconds) {
  pendingSeconds = seconds || 0;
  if (!player || !player.seekTo) return;
  try {
    const cur = player.getCurrentTime ? player.getCurrentTime() : 0;
    if (Math.abs(cur - pendingSeconds) > 0.75) {
      player.seekTo(pendingSeconds, true);
    }
    player.mute();
    player.playVideo();
  } catch(_) {}
}
function forceSeek(seconds) {
  pendingSeconds = seconds || 0;
  if (!player || !player.seekTo) return;
  try {
    player.seekTo(pendingSeconds, true);
    player.mute();
    player.playVideo();
  } catch(_) {}
}
function showNext(visible) {
  document.getElementById('next').style.display = visible ? 'flex' : 'none';
}
</script>
</head>
<body>
<div id="player"></div>
<div id="idle">AUTO VJ STANDBY</div>
<div id="next"><div>NEXT<small>SEARCHING / SYNCING</small></div></div>
</body>
</html>
"""


class VideoWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("AUTO VJ OUTPUT")
        self.resize(1280, 720)
        self.view = QWebEngineView()
        settings = self.view.settings()
        settings.setAttribute(
            QWebEngineSettings.WebAttribute.PlaybackRequiresUserGesture, False
        )
        settings.setAttribute(
            QWebEngineSettings.WebAttribute.FullScreenSupportEnabled, True
        )
        self.view.setHtml(PLAYER_HTML, QUrl("https://localhost/"))
        self.setCentralWidget(self.view)
        self.current_video_id = ""
        self.last_target_seconds = 0.0

    def load_video(self, video_id, seconds):
        self.current_video_id = video_id
        self.last_target_seconds = max(0.0, float(seconds))
        payload = json.dumps(video_id)
        self.view.page().runJavaScript(
            f"loadVideo({payload}, {self.last_target_seconds:.3f});"
        )

    def sync_to(self, seconds):
        self.last_target_seconds = max(0.0, float(seconds))
        self.view.page().runJavaScript(
            f"seekVideo({self.last_target_seconds:.3f});"
        )

    def force_sync(self):
        self.view.page().runJavaScript(
            f"forceSeek({self.last_target_seconds:.3f});"
        )

    def show_next(self, visible=True):
        self.view.page().runJavaScript(
            f"showNext({'true' if visible else 'false'});"
        )

    def toggle_fullscreen(self):
        if self.isFullScreen():
            self.showNormal()
        else:
            self.showFullScreen()


class MainWindow(QMainWindow):
    STATUS_COLORS = {
        "READY": "#31d158",
        "LISTENING": "#64d2ff",
        "RECOGNIZING": "#ffd60a",
        "SEARCHING": "#ffd60a",
        "CANDIDATE": "#ff9f0a",
        "NO MATCH": "#8e8e93",
        "NO VIDEO": "#ff453a",
        "ERROR": "#ff453a",
        "AUDIO ERROR": "#ff453a",
        "STOPPED": "#8e8e93",
    }

    def __init__(self):
        super().__init__()
        self.setWindowTitle("AUTO VJ BACKUP - MVP")
        self.resize(820, 760)
        self.config = load_config()
        self.bus = Bus()
        self.worker = None
        self.video = VideoWindow()
        self.current_ready = None
        self.previous_ready = None
        self._build_ui()
        self._wire_bus()
        self._load_devices()
        self._apply_config_to_ui()
        self.video.show()

    def _build_ui(self):
        root = QWidget()
        layout = QVBoxLayout(root)
        self.status_label = QLabel("STOPPED")
        self.status_label.setStyleSheet(
            "font-size:28px;font-weight:800;padding:12px;border-radius:8px;"
        )
        self.status_detail = QLabel("開始すると常時監視します")
        self.status_detail.setWordWrap(True)
        layout.addWidget(self.status_label)
        layout.addWidget(self.status_detail)
        form = QFormLayout()
        self.mode_combo = QComboBox()
        self.mode_combo.addItems(["HOT STANDBY", "FULL AUTO"])
        form.addRow("Mode", self.mode_combo)
        self.device_combo = QComboBox()
        form.addRow("Audio input", self.device_combo)
        self.token_edit = QLineEdit()
        self.token_edit.setEchoMode(QLineEdit.EchoMode.Password)
        self.token_edit.setPlaceholderText("AudD API token")
        form.addRow("AudD token", self.token_edit)
        self.sample_spin = QDoubleSpinBox()
        self.sample_spin.setRange(3.0, 15.0)
        self.sample_spin.setSingleStep(0.5)
        self.sample_spin.setSuffix(" sec")
        form.addRow("Recognition sample", self.sample_spin)
        self.interval_spin = QDoubleSpinBox()
        self.interval_spin.setRange(3.0, 30.0)
        self.interval_spin.setSingleStep(0.5)
        self.interval_spin.setSuffix(" sec")
        form.addRow("Normal interval", self.interval_spin)
        self.rapid_spin = QDoubleSpinBox()
        self.rapid_spin.setRange(2.0, 10.0)
        self.rapid_spin.setSingleStep(0.5)
        self.rapid_spin.setSuffix(" sec")
        form.addRow("New-track confirm", self.rapid_spin)
        self.hits_spin = QSpinBox()
        self.hits_spin.setRange(1, 4)
        form.addRow("Confirm hits", self.hits_spin)
        self.lead_spin = QDoubleSpinBox()
        self.lead_spin.setRange(-5.0, 5.0)
        self.lead_spin.setSingleStep(0.05)
        self.lead_spin.setDecimals(2)
        self.lead_spin.setSuffix(" sec")
        form.addRow("Sync offset", self.lead_spin)
        layout.addLayout(form)
        now_box = QGridLayout()
        now_box.addWidget(QLabel("NOW"), 0, 0)
        self.now_title = QLabel("-")
        self.now_title.setStyleSheet("font-size:20px;font-weight:700;")
        self.now_artist = QLabel("-")
        self.now_timecode = QLabel("-")
        self.video_title = QLabel("-")
        self.video_title.setWordWrap(True)
        self.candidate_label = QLabel("-")
        self.candidate_label.setWordWrap(True)
        now_box.addWidget(self.now_title, 0, 1)
        now_box.addWidget(QLabel("ARTIST"), 1, 0)
        now_box.addWidget(self.now_artist, 1, 1)
        now_box.addWidget(QLabel("POSITION"), 2, 0)
        now_box.addWidget(self.now_timecode, 2, 1)
        now_box.addWidget(QLabel("VIDEO"), 3, 0)
        now_box.addWidget(self.video_title, 3, 1)
        now_box.addWidget(QLabel("CANDIDATE"), 4, 0)
        now_box.addWidget(self.candidate_label, 4, 1)
        layout.addLayout(now_box)
        row = QHBoxLayout()
        self.start_btn = QPushButton("START HOT STANDBY")
        self.stop_btn = QPushButton("STOP")
        self.stop_btn.setEnabled(False)
        self.save_btn = QPushButton("SAVE SETTINGS")
        row.addWidget(self.start_btn)
        row.addWidget(self.stop_btn)
        row.addWidget(self.save_btn)
        layout.addLayout(row)
        output_row = QHBoxLayout()
        self.show_output_btn = QPushButton("SHOW OUTPUT")
        self.take_btn = QPushButton("TAKE / FULLSCREEN")
        self.resync_btn = QPushButton("RESYNC")
        self.next_btn = QPushButton("NEXT TEST")
        output_row.addWidget(self.show_output_btn)
        output_row.addWidget(self.take_btn)
        output_row.addWidget(self.resync_btn)
        output_row.addWidget(self.next_btn)
        layout.addLayout(output_row)
        layout.addWidget(QLabel("LOG"))
        self.log = QTextEdit()
        self.log.setReadOnly(True)
        layout.addWidget(self.log, 1)
        self.setCentralWidget(root)
        self.start_btn.clicked.connect(self.start_monitoring)
        self.stop_btn.clicked.connect(self.stop_monitoring)
        self.save_btn.clicked.connect(self.save_settings)
        self.show_output_btn.clicked.connect(self._show_output)
        self.take_btn.clicked.connect(self._take)
        self.resync_btn.clicked.connect(self.video.force_sync)
        self.next_btn.clicked.connect(self._test_next)

    def _wire_bus(self):
        self.bus.log.connect(self._log)
        self.bus.status.connect(self._set_status)
        self.bus.match.connect(self._on_match)
        self.bus.candidate.connect(self._on_candidate)
        self.bus.ready.connect(self._on_ready)
        self.bus.sync.connect(self.video.sync_to)

    def _load_devices(self):
        self.device_combo.clear()
        try:
            devices = sd.query_devices()
            for idx, device in enumerate(devices):
                if int(device.get("max_input_channels", 0)) > 0:
                    self.device_combo.addItem(
                        f"{idx}: {device.get('name', 'Unknown')}", idx
                    )
        except Exception as exc:
            self._log(f"Audio device list error: {exc}")

    def _apply_config_to_ui(self):
        self.mode_combo.setCurrentText(self.config.get("mode", "HOT STANDBY"))
        self.token_edit.setText(self.config.get("audd_api_token", ""))
        self.sample_spin.setValue(float(self.config.get("sample_seconds", 7.0)))
        self.interval_spin.setValue(
            float(self.config.get("normal_interval_seconds", 7.0))
        )
        self.rapid_spin.setValue(
            float(self.config.get("rapid_confirm_seconds", 3.0))
        )
        self.hits_spin.setValue(int(self.config.get("confirm_hits", 2)))
        self.lead_spin.setValue(float(self.config.get("sync_lead_seconds", 0.0)))
        target = self.config.get("audio_device")
        if target is not None:
            for i in range(self.device_combo.count()):
                if self.device_combo.itemData(i) == target:
                    self.device_combo.setCurrentIndex(i)
                    break

    def _ui_config(self):
        return {
            **self.config,
            "mode": self.mode_combo.currentText(),
            "audio_device": self.device_combo.currentData(),
            "audd_api_token": self.token_edit.text().strip(),
            "sample_seconds": self.sample_spin.value(),
            "normal_interval_seconds": self.interval_spin.value(),
            "rapid_confirm_seconds": self.rapid_spin.value(),
            "confirm_hits": self.hits_spin.value(),
            "sync_lead_seconds": self.lead_spin.value(),
        }

    @Slot()
    def save_settings(self):
        self.config = self._ui_config()
        save_config(self.config)
        self._log("設定を保存しました")

    @Slot()
    def start_monitoring(self):
        if self.worker and self.worker.is_alive():
            return
        cfg = self._ui_config()
        if not cfg["audd_api_token"]:
            QMessageBox.warning(
                self,
                "AudD token",
                "AudD API tokenを入力してください。既存のVercel環境変数とは別に、"
                "このデスクトップMVPではローカル設定を使います。",
            )
            return
        if self.device_combo.currentData() is None:
            QMessageBox.warning(self, "Audio", "音声入力デバイスを選んでください。")
            return
        self.config = cfg
        save_config(self.config)
        self.worker = RecognitionWorker(self.bus, self.config)
        self.worker.start()
        self.start_btn.setEnabled(False)
        self.stop_btn.setEnabled(True)
        self._log("HOT STANDBY開始")

    @Slot()
    def stop_monitoring(self):
        if self.worker:
            self.worker.stop()
            self.worker = None
        self.start_btn.setEnabled(True)
        self.stop_btn.setEnabled(False)
        self._set_status("STOPPED", "監視を停止しました")

    @Slot(str)
    def _log(self, text):
        stamp = time.strftime("%H:%M:%S")
        self.log.append(f"[{stamp}] {text}")

    @Slot(str, str)
    def _set_status(self, state, detail):
        color = self.STATUS_COLORS.get(state, "#ffffff")
        self.status_label.setText(state)
        self.status_label.setStyleSheet(
            f"font-size:28px;font-weight:800;padding:12px;border-radius:8px;"
            f"background:#202124;color:{color};"
        )
        self.status_detail.setText(detail)

    @Slot(dict)
    def _on_match(self, match):
        self.now_title.setText(match.get("title") or "-")
        self.now_artist.setText(match.get("artist") or "-")
        self.now_timecode.setText(match.get("timecode") or "-")

    @Slot(dict)
    def _on_candidate(self, payload):
        video = payload.get("video") or {}
        self.candidate_label.setText(
            f"{payload.get('artist', '')} - {payload.get('title', '')} "
            f"[{payload.get('hits', 1)} hit] / "
            f"{video.get('title', 'video searching...')}"
        )

    @Slot(dict)
    def _on_ready(self, payload):
        self.previous_ready = self.current_ready
        self.current_ready = payload
        video = payload.get("video") or {}
        video_id = video.get("video_id")
        seconds = (
            float(payload.get("position_seconds", 0.0))
            + float(self.config.get("sync_lead_seconds", 0.0))
        )
        self.video_title.setText(
            f"{video.get('title', '-')} / {video.get('channel', '-')}"
        )
        self.candidate_label.setText("-")
        if not video_id:
            self._set_status("NO VIDEO", "再生可能なYouTube候補がありません")
            return
        is_track_change = self.previous_ready is not None
        if self.mode_combo.currentText() == "FULL AUTO" and is_track_change:
            self.video.show_next(True)

            def switch():
                self.video.load_video(video_id, max(0.0, seconds))
                QTimer.singleShot(900, lambda: self.video.show_next(False))

            QTimer.singleShot(1100, switch)
        else:
            self.video.load_video(video_id, max(0.0, seconds))
        self._log(
            f"READY: {payload.get('artist', '')} - {payload.get('title', '')} "
            f"@ {seconds:.2f}s / {video.get('title', '')}"
        )

    def _show_output(self):
        self.video.showNormal()
        self.video.raise_()
        self.video.activateWindow()

    def _take(self):
        self.video.show()
        self.video.showFullScreen()
        self.video.raise_()
        self.video.activateWindow()
        if self.current_ready:
            self.video.force_sync()

    def _test_next(self):
        self.video.show_next(True)
        QTimer.singleShot(1500, lambda: self.video.show_next(False))

    def closeEvent(self, event):
        if self.worker:
            self.worker.stop()
        self.video.close()
        event.accept()


def main():
    app = QApplication(sys.argv)
    app.setApplicationName("AUTO VJ BACKUP")
    window = MainWindow()
    window.show()
    sys.exit(app.exec())


if __name__ == "__main__":
    main()
