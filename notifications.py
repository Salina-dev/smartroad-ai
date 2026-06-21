"""
Road Damage Alert Notification Module.

Provides alert functionality for Live Camera Detection:
- Streamlit warning popup for detections >= 50% confidence
- Deduplication (30 sec per damage type)
- Optional sound alert via HTML/JS
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
    """Call once on page load to request notification permission and warm up AudioContext."""
    init_js = """
    <script>
    (function() {
        // Request notification permission silently
        if ("Notification" in window && Notification.permission === "default") {
            Notification.requestPermission().then(function(perm) {
                console.log("[SmartRoad] Notification permission:", perm);
            });
        }
        // Pre-warm AudioContext (must be from user gesture, but this helps)
        try {
            var ctx = new (window.AudioContext || window.webkitAudioContext)();
            if (ctx.state === "suspended") {
                ctx.resume();
            }
            console.log("[SmartRoad] AudioContext initialized, state:", ctx.state);
        } catch(e) {
            console.warn("[SmartRoad] AudioContext init:", e);
        }
    })();
    </script>
    """
    html(init_js, height=0)


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
    triggered_count = 0

    for item in detections:
        confidence = item.get("confidence", 0)
        if confidence < conf_threshold:
            print(f"[alerts] Skipping {item.get('label','?')}: confidence {confidence:.2f} < threshold {conf_threshold}")
            continue

        label = item.get("label", "Unknown")
        damage_type = _extract_damage_type(label)
        if not damage_type:
            print(f"[alerts] Skipping: could not extract damage type from '{label}'")
            continue

        if not _should_alert(damage_type):
            print(f"[alerts] Skipping {damage_type}: within cooldown period")
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
            _play_alert_sound()
            print(f"[alerts] Sound alert triggered for {damage_type}")

        # --- Optional browser notification ---
        if enable_browser_notify:
            _show_browser_notification(damage_type, confidence_pct, location_str, now_str)
            print(f"[alerts] Browser notification triggered for {damage_type}")

        triggered_count += 1

    print(f"[alerts] Total alerts triggered: {triggered_count}")


def _play_alert_sound():
    """Inject HTML/JS to play a short beep sound via Web Audio API."""
    sound_html = """
    <script>
    (function() {
        try {
            var ctx = new (window.AudioContext || window.webkitAudioContext)();
            if (ctx.state === "suspended") {
                ctx.resume();
            }
            // Play a short alert beep
            var osc = ctx.createOscillator();
            var gain = ctx.createGain();
            osc.connect(gain);
            gain.connect(ctx.destination);
            osc.frequency.value = 880;
            osc.type = 'sine';
            gain.gain.setValueAtTime(0.3, ctx.currentTime);
            gain.gain.exponentialRampToValueAtTime(0.01, ctx.currentTime + 0.3);
            osc.start(ctx.currentTime);
            osc.stop(ctx.currentTime + 0.3);
            console.log("[SmartRoad] Beep sound played at", new Date().toLocaleTimeString());
        } catch(e) {
            console.warn('[SmartRoad] Alert sound error:', e);
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