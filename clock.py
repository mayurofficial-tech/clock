import json
import math
import time
from datetime import date, datetime
from pathlib import Path

import streamlit as st
import streamlit.components.v1 as components

# Needs Streamlit >= 1.37 (st.fragment with run_every, st.dialog)

# -------------------- App configuration --------------------
st.set_page_config(
    page_title="FocusFlow",
    page_icon="🎯",
    layout="centered",
    initial_sidebar_state="expanded",
)

DATA_FILE = Path(__file__).resolve().parent / "focusflow_data.json"
DEFAULT_STUDY_MINUTES = 2
DEFAULT_BREAK_MINUTES = 1
MAX_LOG_EVENTS = 50

PAGE_CSS = """
<style>
  .block-container {max-width: 850px; padding-top: 2rem; padding-bottom: 3rem;}
  .hero {padding: 1.25rem 1.4rem; border-radius: 18px;
         background: linear-gradient(120deg, #172554, #0f766e);
         color: white; margin-bottom: 1rem;}
  .hero h1 {margin: 0; font-size: 2rem;}
  .hero p {margin: .45rem 0 0 0; color: #dbeafe;}
  div.stButton > button {border-radius: 12px; min-height: 2.8rem; font-weight: 600;}
</style>
<div class="hero">
  <h1>🎯 FocusFlow</h1>
  <p>Study with focus. Take breaks when you are ready. Your daily progress is saved.</p>
</div>
"""

BEEP_HTML = """
<script>
(() => {
  try {
    const AudioContext = window.AudioContext || window.webkitAudioContext;
    if (!AudioContext) return;
    const ctx = new AudioContext();
    const beep = () => {
      if (ctx.state === 'suspended') ctx.resume();
      const osc = ctx.createOscillator();
      const gain = ctx.createGain();
      osc.type = 'sine';
      osc.frequency.value = 880;
      gain.gain.value = 0.12;
      osc.connect(gain);
      gain.connect(ctx.destination);
      osc.start();
      osc.stop(ctx.currentTime + 0.22);
    };
    beep();
    const id = setInterval(beep, 650);
    window.addEventListener('pagehide', () => { clearInterval(id); ctx.close(); });
  } catch (e) {}
})();
</script>
"""


# -------------------- Storage (disk is read once, written only on change) --------------------
def new_day(day_key):
    return {
        "date": day_key,
        "study_sessions": 0,
        "break_sessions": 0,
        "study_seconds": 0,
        "break_seconds": 0,
        "completed_study_sessions": 0,
        "completed_break_sessions": 0,
        "events": [],
        "day_ended": False,
        "day_end_note": "",
    }


def read_from_disk():
    if not DATA_FILE.exists():
        return {"days": {}}
    try:
        with DATA_FILE.open("r", encoding="utf-8") as f:
            data = json.load(f)
        if isinstance(data, dict) and isinstance(data.get("days"), dict):
            return data
    except (json.JSONDecodeError, OSError):
        pass
    return {"days": {}}


def write_to_disk(data):
    tmp = DATA_FILE.with_suffix(".tmp")
    with tmp.open("w", encoding="utf-8") as f:
        json.dump(data, f, indent=2, ensure_ascii=False)
    tmp.replace(DATA_FILE)


def get_data():
    """Data lives in session_state, so we don't hit the disk on every rerun."""
    if "data" not in st.session_state:
        st.session_state.data = read_from_disk()
    return st.session_state.data


def today():
    return date.today().isoformat()


def add_event(day, event_type, details=""):
    day.setdefault("events", []).append(
        {"time": datetime.now().isoformat(timespec="seconds"), "type": event_type, "details": details}
    )


def update_day(day_key, updater):
    data = get_data()
    day = data["days"].setdefault(day_key, new_day(day_key))
    updater(day)
    write_to_disk(data)


def format_duration(seconds):
    seconds = max(0, int(seconds))
    hours, rem = divmod(seconds, 3600)
    minutes, secs = divmod(rem, 60)
    if hours:
        return f"{hours}h {minutes}m"
    if minutes:
        return f"{minutes}m {secs}s" if secs else f"{minutes}m"
    return f"{secs}s"


def pretty_date(day_key, fmt):
    try:
        return datetime.strptime(day_key, "%Y-%m-%d").strftime(fmt)
    except ValueError:
        return day_key


# -------------------- Session state defaults --------------------
ss = st.session_state
for key, default in {
    "phase": "Ready",
    "running": False,
    "end_time": None,
    "phase_duration": DEFAULT_STUDY_MINUTES * 60,
    "remaining_seconds": DEFAULT_STUDY_MINUTES * 60,
    "sound_active": False,
    "sound_enabled": True,
    "study_minutes": DEFAULT_STUDY_MINUTES,
    "break_minutes": DEFAULT_BREAK_MINUTES,
}.items():
    ss.setdefault(key, default)

get_data()["days"].setdefault(today(), new_day(today()))
if "day_end_note_input" not in ss:
    ss.day_end_note_input = get_data()["days"][today()].get("day_end_note", "")


# -------------------- Callbacks (run before the rerun, so no st.rerun() needed) --------------------
def start_phase(kind):
    minutes = ss.study_minutes if kind == "Study" else ss.break_minutes
    duration = int(minutes) * 60
    ss.phase = kind
    ss.phase_duration = duration
    ss.remaining_seconds = duration
    ss.end_time = time.time() + duration
    ss.running = True
    ss.sound_active = False

    def updater(day):
        if kind == "Study":
            day["study_sessions"] = day.get("study_sessions", 0) + 1
            day["day_ended"] = False
        else:
            day["break_sessions"] = day.get("break_sessions", 0) + 1
        add_event(day, f"{kind.lower()}_started", f"{duration // 60} minute(s)")

    update_day(today(), updater)


def finish_phase():
    kind, duration = ss.phase, ss.phase_duration
    ss.running = False
    ss.end_time = None
    ss.remaining_seconds = 0
    ss.phase = f"{kind} complete"
    ss.sound_active = bool(ss.sound_enabled)

    def updater(day):
        prefix = kind.lower()
        day[f"{prefix}_seconds"] = day.get(f"{prefix}_seconds", 0) + duration
        day[f"completed_{prefix}_sessions"] = day.get(f"completed_{prefix}_sessions", 0) + 1
        add_event(day, f"{prefix}_completed", f"{duration // 60} minute(s)")

    update_day(today(), updater)


def stop_timer():
    was_running = ss.running
    ss.running = False
    ss.end_time = None
    ss.phase = "Ready"
    ss.sound_active = False
    if was_running:
        update_day(today(), lambda day: add_event(day, "timer_reset", "Timer stopped or reset"))


def stop_sound():
    ss.sound_active = False


def end_day():
    note = ss.day_end_note_input.strip()

    def updater(day):
        day["day_ended"] = True
        day["day_end_note"] = note
        add_event(day, "day_ended", note)

    update_day(today(), updater)
    ss.running = False
    ss.end_time = None
    ss.day_saved_msg = True


# -------------------- Daily summary popup --------------------
@st.dialog("📊 Daily summary", width="large")
def show_daily_summary(day_key):
    day = get_data()["days"].get(day_key)
    if not day:
        st.info("No saved data for this day.")
    else:
        st.caption(pretty_date(day_key, "%A, %d %B %Y"))
        c1, c2 = st.columns(2)
        c1.metric("Study sessions started", day.get("study_sessions", 0))
        c2.metric("Study sessions completed", day.get("completed_study_sessions", 0))
        c3, c4 = st.columns(2)
        c3.metric("Break sessions completed", day.get("completed_break_sessions", 0))
        c4.metric("Total focused time", format_duration(day.get("study_seconds", 0)))
        st.metric("Total break time", format_duration(day.get("break_seconds", 0)))

        if day.get("day_ended"):
            st.success("Day marked as ended.")
        else:
            st.caption("This day has not been marked as ended yet.")

        if day.get("day_end_note"):
            st.markdown("**Your day-end note**")
            st.write(day["day_end_note"])

        with st.expander("🧾 Session activity log", expanded=True):
            events = day.get("events", [])
            if events:
                lines = []
                for ev in reversed(events[-MAX_LOG_EVENTS:]):
                    raw = ev.get("time", "")
                    try:
                        t = datetime.fromisoformat(raw).strftime("%I:%M %p")
                    except ValueError:
                        t = raw
                    title = ev.get("type", "event").replace("_", " ").title()
                    detail = f" — {ev['details']}" if ev.get("details") else ""
                    lines.append(f"- **{t}** · {title}{detail}")
                st.markdown("\n".join(lines))
                if len(events) > MAX_LOG_EVENTS:
                    st.caption(f"Showing latest {MAX_LOG_EVENTS} of {len(events)} events.")
            else:
                st.caption("No activity saved for this day yet.")

    st.divider()
    if st.button("Close", key="close_summary_dialog", use_container_width=True):
        st.rerun()


# -------------------- Sidebar --------------------
with st.sidebar:
    st.title("📅 Daily history")
    st.caption("Your sessions are saved automatically in a local JSON file.")

    days = get_data()["days"]
    if not days:
        st.info("Your daily summaries will appear here.")
    for day_key in sorted(days, reverse=True):
        d = days[day_key]
        is_today = day_key == today()
        label = f"{'📍 ' if is_today else '📄 '}{pretty_date(day_key, '%a, %d %b %Y')}"
        with st.expander(label, expanded=is_today):
            st.write(f"📚 Study sessions: **{d.get('study_sessions', 0)}**")
            st.write(f"✅ Study completed: **{d.get('completed_study_sessions', 0)}**")
            st.write(f"☕ Break sessions: **{d.get('break_sessions', 0)}**")
            st.write(f"⏱️ Study time: **{format_duration(d.get('study_seconds', 0))}**")
            st.write(f"🌿 Break time: **{format_duration(d.get('break_seconds', 0))}**")
            if d.get("day_ended"):
                st.success("Day ended")
            # Dialog opens only on the run where the button is clicked,
            # so it never re-pops on later reruns.
            if st.button("View summary", key=f"summary_{day_key}", use_container_width=True):
                show_daily_summary(day_key)

    st.divider()
    st.subheader("⚙️ Timer settings")
    st.number_input("Study duration (minutes)", min_value=1, max_value=180, step=1, key="study_minutes")
    st.number_input("Break duration (minutes)", min_value=1, max_value=60, step=1, key="break_minutes")
    st.toggle("🔔 Sound enabled", key="sound_enabled")


# -------------------- Main page --------------------
st.markdown(PAGE_CSS, unsafe_allow_html=True)


def timer_panel():
    """Only this fragment reruns every second, not the whole app."""
    if ss.running and ss.end_time is not None:
        ss.remaining_seconds = max(0, math.ceil(ss.end_time - time.time()))
        if ss.remaining_seconds <= 0:
            finish_phase()
            st.rerun()  # full rerun once, to refresh buttons, sidebar and sound

    if ss.running:
        st.info(f"⏳ {ss.phase} session in progress")
    elif ss.phase == "Study complete":
        st.success("🎉 Study complete! Click **Start Break** when you are ready.")
    elif ss.phase == "Break complete":
        st.success("🌿 Break complete! Start another study session whenever you are ready.")
    else:
        st.info("Ready when you are. Start a phase when you want to begin.")

    if ss.phase == "Ready":
        remaining = int(ss.study_minutes) * 60
    else:
        remaining = ss.remaining_seconds
    minutes, seconds = divmod(max(0, remaining), 60)
    st.markdown(
        f"""
        <div style="text-align:center; padding:1.4rem; border:1px solid #334155;
                    border-radius:20px; margin:.8rem 0 1rem 0;">
          <div style="font-size:1rem; color:#94a3b8;">{ss.phase}</div>
          <div style="font-size:4rem; font-weight:750; letter-spacing:2px; line-height:1.25;">
            {minutes:02d}:{seconds:02d}
          </div>
          <div style="font-size:.9rem; color:#94a3b8;">
            {'Running' if ss.running else 'Paused / ready'}
          </div>
        </div>
        """,
        unsafe_allow_html=True,
    )


# Auto-refresh only while a timer is running
st.fragment(timer_panel, run_every=1 if ss.running else None)()

col1, col2, col3 = st.columns(3)
col1.button("▶️ Start Study", use_container_width=True, disabled=ss.running,
            on_click=start_phase, args=("Study",))
col2.button("☕ Start Break", use_container_width=True, disabled=ss.running,
            on_click=start_phase, args=("Break",))
col3.button("⏹ Stop / Reset", use_container_width=True, on_click=stop_timer)

if ss.sound_active and ss.sound_enabled:
    st.warning("🔔 Timer finished.")
    c1, c2 = st.columns([1, 3])
    c1.button("🔇 Stop Sound", type="primary", use_container_width=True, on_click=stop_sound)
    c2.caption("Use Stop Sound to silence the notification.")
    components.html(BEEP_HTML, height=0)

st.divider()

# -------------------- End of day --------------------
st.subheader("🌙 End your day")
st.caption("When you finish studying for today, save your day-end note and view your daily report.")
st.text_area(
    "What did you learn today? (optional)",
    placeholder="Example: Practised SMOTE, ADASYN, and model evaluation.",
    key="day_end_note_input",
    height=90,
)
st.button("💾 Save & End Day", type="primary", use_container_width=True, on_click=end_day)
if ss.pop("day_saved_msg", False):
    st.success("Your day has been saved to focusflow_data.json.")

st.caption("💡 Data is stored locally in focusflow_data.json beside this script. Keep that file if you want to retain your history.")