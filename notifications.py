"""
Road Damage Alert Notification Module.

Provides alert functionality for Live Camera Detection:
- Streamlit warning popup for detections >= 50% confidence
- Deduplication (30 sec per damage type)
- Optional sound alert via Web Audio API with autoplay policy handling
- Optional browser notification via HTML/JS Notification API
- Debug logging for troubleshooting
"""
import datetime
import time
import streamlit as st
from streamlit.components.v1 import html


# Deduplication: track last alert time per damage type (e.g. "Pothole", "Crack")
_last_alert_times = {}  # {damage_type: timestamp}


def _should_alert(damage_type: str, cooldown_seconds: int = 30) -> bool:
    """Returns True if an alert for this damage type can be shown (cooldown elapsed)."""
    now = time.time()
    last = _last_alert_times.get(damage_type, 0)
    if now - last >= cooldown_seconds:
        _last_alert_times[damage_type] = now
        return True
    return False


def _extract_damage_type(label: str) -> str:
    """Normalize a detection label into a damage type category."""
    label_lower = label.lower()
    if "pothole" in label_lower:
        return "Pothole"
    if "crack" in label_lower or "longitudinal" in label_lower or "transverse" in label_lower or "alligator" in label_lower:
        return "Crack"
    # Any other road damage label
    return label


def init_notification_system():
    """
    Call once on page load to request notification permission and set up a
    globally-shared AudioContext for reliable audio playback.
    
    A single global AudioContext avoids autoplay policy issues because:
    1. It is created once and reused
    2. It can be resumed after user gesture
    3. We store it as window.__smartroad_audio_ctx
    """
    init_js = """
    <script>
    (function() {
        console.log("[SmartRoad] init_notification_system() called", new Date().toISOString());
        
        // --- Pre-warm / create shared AudioContext ---
        try {
            if (!window.__smartroad_audio_ctx) {
                window.__smartroad_audio_ctx = new (window.AudioContext || window.webkitAudioContext)();
                console.log("[SmartRoad] Shared AudioContext CREATED, state:", window.__smartroad_audio_ctx.state);
            } else {
                console.log("[SmartRoad] Shared AudioContext already exists, state:", window.__smartroad_audio_ctx.state);
            }
            // If suspended, try to resume immediately (may still be blocked without gesture)
            if (window.__smartroad_audio_ctx.state === "suspended") {
                window.__smartroad_audio_ctx.resume().then(function() {
                    console.log("[SmartRoad] AudioContext resumed successfully, state:", window.__smartroad_audio_ctx.state);
                }).catch(function(err) {
                    console.warn("[SmartRoad] AudioContext resume failed:", err);
                });
            }
        } catch(e) {
            console.warn("[SmartRoad] AudioContext init error:", e);
        }
        
        // --- Request notification permission silently ---
        if ("Notification" in window && Notification.permission === "default") {
            Notification.requestPermission().then(function(perm) {
                console.log("[SmartRoad] Notification permission:", perm);
            });
        }
        
        // Log that init completed
        console.log("[SmartRoad] init_notification_system() complete");
    })();
    </script>
    """
    html(init_js, height=0)


def unlock_audio_on_gesture():
    """
    Call this right after a user-initiated action (like clicking Start Camera).
    This unlocks the AudioContext because it runs from a user gesture event handler.
    
    This is the KEY fix for browser autoplay restrictions.
    """
    unlock_js = """
    <script>
    (function() {
        console.log("[SmartRoad] unlock_audio_on_gesture() called (from user gesture)", new Date().toISOString());
        
        // Create shared AudioContext if not yet created
        try {
            if (!window.__smartroad_audio_ctx) {
                window.__smartroad_audio_ctx = new (window.AudioContext || window.webkitAudioContext)();
                console.log("[SmartRoad] Shared AudioContext CREATED via user gesture, state:", window.__smartroad_audio_ctx.state);
            }
            
            // Resume if suspended - THIS WORKS because we're in a user gesture context
            if (window.__smartroad_audio_ctx.state === "suspended") {
                window.__smartroad_audio_ctx.resume().then(function() {
                    console.log("[SmartRoad] AudioContext RESUMED from user gesture, state:", window.__smartroad_audio_ctx.state);
                    
                    // Play a very short silent tone to fully unlock audio
                    var osc = window.__smartroad_audio_ctx.createOscillator();
                    var gain = window.__smartroad_audio_ctx.createGain();
                    osc.connect(gain);
                    gain.connect(window.__smartroad_audio_ctx.destination);
                    gain.gain.setValueAtTime(0.001, window.__smartroad_audio_ctx.currentTime);
                    osc.start(window.__smartroad_audio_ctx.currentTime);
                    osc.stop(window.__smartroad_audio_ctx.currentTime + 0.01);
                    console.log("[SmartRoad] Audio unlock tone played successfully");
                }).catch(function(err) {
                    console.warn("[SmartRoad] AudioContext resume from gesture failed:", err);
                });
            } else {
                console.log("[SmartRoad] AudioContext already in state:", window.__smartroad_audio_ctx.state);
            }
        } catch(e) {
            console.warn("[SmartRoad] Audio unlock error:", e);
        }
        
        console.log("[SmartRoad] unlock_audio_on_gesture() complete");
    })();
    </script>
    """
    html(unlock_js, height=0)


def check_detections(
    detections: list,
    latitude: float = 0.0,
    longitude: float = 0.0,
    address: str = "",
    conf_threshold: float = 0.5,
    enable_sound: bool = True,
    enable_browser_notify: bool = True,
):
    """
    Evaluate a list of detections and trigger alerts as needed.

    Parameters
    ----------
    detections : list
        List of detection dicts with keys: "label", "confidence", "bbox", etc.
    latitude, longitude : float
        Current GPS coordinates.
    address : str
        Human-readable address or road name.
    conf_threshold : float
        Minimum confidence to trigger alert (default 0.5 = 50%).
    enable_sound : bool
        If True, injects JS to play a brief alert sound.
    enable_browser_notify : bool
        If True, injects JS to show a browser notification.
    """
    if not detections:
        print("[alerts] No detections to process.")
        return

    print(f"[alerts] Processing {len(detections)} detection(s)...")
    print(f"[alerts] Sound enabled: {enable_sound}, Browser notify enabled: {enable_browser_notify}")
    triggered_count = 0

    for item in detections:
        confidence = item.get("confidence", 0)
        label = item.get("label", "Unknown")
        print(f"[alerts]   Detection: {label}, confidence: {confidence:.3f}, threshold: {conf_threshold}")

        if confidence < conf_threshold:
            print(f"[alerts]   SKIP: confidence {confidence:.2f} < threshold {conf_threshold}")
            continue

        damage_type = _extract_damage_type(label)
        if not damage_type:
            print(f"[alerts]   SKIP: could not extract damage type from '{label}'")
            continue

        if not _should_alert(damage_type):
            print(f"[alerts]   SKIP: {damage_type} within cooldown period (30s)")
            continue

        confidence_pct = round(confidence * 100, 1)
        now_str = datetime.datetime.now().strftime("%H:%M:%S")

        location_str = f"Lat: {latitude}, Lon: {longitude}"
        if address:
            location_str = f"{address} ({location_str})"

        # --- Streamlit warning popup ---
        alert_msg = (
            f"**⚠️ ROAD DAMAGE ALERT**\n\n"
            f"**Damage Type:** {damage_type}\n\n"
            f"**Confidence:** {confidence_pct}%\n\n"
            f"**Location:** {location_str}\n\n"
            f"**Time:** {now_str}"
        )
        st.warning(alert_msg)
        print(f"[alerts] Streamlit alert triggered: {damage_type} @ {confidence_pct}%")

        # --- Optional sound alert ---
        if enable_sound:
            print(f"[alerts] Calling _play_alert_sound() for {damage_type}")
            _play_alert_sound()
            print(f"[alerts] Sound alert triggered successfully for {damage_type}")
        else:
            print(f"[alerts] Sound DISABLED by user setting, skipping sound for {damage_type}")

        # --- Optional browser notification ---
        if enable_browser_notify:
            _show_browser_notification(damage_type, confidence_pct, location_str, now_str)
            print(f"[alerts] Browser notification triggered for {damage_type}")
        else:
            print(f"[alerts] Browser notification DISABLED by user setting")

        triggered_count += 1

    print(f"[alerts] Total alerts triggered: {triggered_count}")
    print(f"[alerts] check_detections() complete")


def _play_alert_sound():
    """
    Inject HTML/JS to play a short beep sound via the globally shared AudioContext.
    
    Uses window.__smartroad_audio_ctx (created by init_notification_system and
    unlocked by unlock_audio_on_gesture). This ensures the AudioContext is in
    'running' state when we try to play.
    """
    sound_html = """
    <script>
    (function() {
        var timestamp = new Date().toLocaleTimeString();
        console.log("[SmartRoad] _play_alert_sound() called at", timestamp);
        
        try {
            // Use the globally shared AudioContext
            var ctx = window.__smartroad_audio_ctx;
            
            if (!ctx) {
                console.warn("[SmartRoad] No shared AudioContext found, creating new one");
                ctx = new (window.AudioContext || window.webkitAudioContext)();
                window.__smartroad_audio_ctx = ctx;
            }
            
            console.log("[SmartRoad] AudioContext state before play:", ctx.state);
            
            // If suspended, try to resume
            if (ctx.state === "suspended") {
                console.log("[SmartRoad] AudioContext is suspended, attempting resume...");
                ctx.resume().then(function() {
                    console.log("[SmartRoad] AudioContext resumed, state:", ctx.state);
                    _doPlay(ctx);
                }).catch(function(err) {
                    console.warn("[SmartRoad] AudioContext resume failed in _play_alert_sound:", err);
                });
            } else {
                // Already running - play immediately
                _doPlay(ctx);
            }
        } catch(e) {
            console.warn("[SmartRoad] Alert sound error in _play_alert_sound:', e);
        }
        
        function _doPlay(ctx) {
            try {
                // Play a short alert beep (880 Hz sine wave, 300ms duration)
                var osc = ctx.createOscillator();
                var gain = ctx.createGain();
                osc.connect(gain);
                gain.connect(ctx.destination);
                
                osc.frequency.value = 880;
                osc.type = 'sine';
                
                // Ramp up gain quickly to avoid click, then ramp down
                var now = ctx.currentTime;
                gain.gain.setValueAtTime(0.001, now);
                gain.gain.linearRampToValueAtTime(0.3, now + 0.02);
                gain.gain.exponentialRampToValueAtTime(0.001, now + 0.3);
                
                osc.start(now);
                osc.stop(now + 0.3);
                
                console.log("[SmartRoad] BEEP sound played successfully at", new Date().toLocaleTimeString());
            } catch(e) {
                console.warn("[SmartRoad] Audio playback error:", e);
            }
        }
    })();
    </script>
    """
    html(sound_html, height=0)


def _show_browser_notification(damage_type: str, confidence_pct: float, location: str, timestamp: str):
    """Inject HTML/JS to show a browser notification."""
    notify_html = f"""
    <script>
    (function() {{
        console.log("[SmartRoad] Attempting browser notification: {damage_type} @ {confidence_pct}%");
        if (!("Notification" in window)) {{
            console.warn("[SmartRoad] Browser notifications not supported.");
            return;
        }}
        if (Notification.permission === "granted") {{
            try {{
                var n = new Notification("⚠️ ROAD DAMAGE ALERT", {{
                    body: "Damage: {damage_type}\\nConfidence: {confidence_pct}%\\nLoc: {location}\\nTime: {timestamp}",
                    icon: ""
                }});
                console.log("[SmartRoad] Notification sent successfully");
                // Auto-close after 5 seconds
                setTimeout(function() {{ n.close(); }}, 5000);
            }} catch(e) {{
                console.warn("[SmartRoad] Notification error:", e);
            }}
        }} else if (Notification.permission !== "denied") {{
            Notification.requestPermission().then(function(permission) {{
                console.log("[SmartRoad] Permission result:", permission);
                if (permission === "granted") {{
                    try {{
                        var n = new Notification("⚠️ ROAD DAMAGE ALERT", {{
                            body: "Damage: {damage_type}\\nConfidence: {confidence_pct}%\\nLoc: {location}\\nTime: {timestamp}",
                            icon: ""
                        }});
                        console.log("[SmartRoad] Notification sent after permission grant");
                        setTimeout(function() {{ n.close(); }}, 5000);
                    }} catch(e) {{
                        console.warn("[SmartRoad] Notification error:", e);
                    }}
                }}
            }});
        }} else {{
            console.warn("[SmartRoad] Notification permission denied");
        }}
    }})();
    </script>
    """
    html(notify_html, height=0)


def reset_dedup():
    """Clear all deduplication tracking (useful when starting a new session)."""
    _last_alert_times.clear()
    print("[alerts] Dedup cache cleared")