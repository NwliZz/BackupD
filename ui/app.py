import streamlit as st
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

from _helpers import inject_css, run_root, parse_json_best_effort, badge, hbytes, show_logs

st.set_page_config(page_title="BackupD", layout="wide")
inject_css()

st.title("BackupD")
badge("LOCALHOST UI • Access via SSH tunnel", "warn")

rc, out, err = run_root(["status"])
data = parse_json_best_effort(out)

if rc != 0 or not data:
    badge("Status: FAILED to read", "bad")
    st.code((out or "") + "\n" + (err or ""), language="text")
    st.stop()

badge("Status: OK", "ok")
show_logs(err)

c1, c2, c3, c4 = st.columns(4)
with c1:
    st.metric("Mode", data.get("mode", "?"))
with c2:
    st.metric("Local backups", data.get("local_count", 0))
with c3:
    st.metric("Remote backups", data.get("remote_count", 0))
with c4:
    st.metric("Latest local", data.get("local_latest") or "—")

st.markdown("---")

# --- Live Clock & Timer ---

def get_next_run(now: datetime, schedule_times: list[str]) -> timedelta:
    """Calculates the time difference to the next scheduled run."""
    run_times_today = []
    for t_str in schedule_times:
        try:
            hour, minute = map(int, t_str.split(':'))
            run_times_today.append(now.replace(hour=hour, minute=minute, second=0, microsecond=0))
        except (ValueError, IndexError):
            continue

    run_times_today.sort()

    next_run_time = None
    for run_time in run_times_today:
        if run_time > now:
            next_run_time = run_time
            break

    if next_run_time is None and run_times_today:
        next_run_time = run_times_today[0] + timedelta(days=1)

    return (next_run_time - now) if next_run_time else timedelta(0)

def format_timedelta(td: timedelta) -> str:
    """Formats a timedelta into HH:MM:SS."""
    total_seconds = int(td.total_seconds())
    if total_seconds < 0:
        total_seconds = 0
    hours, remainder = divmod(total_seconds, 3600)
    minutes, seconds = divmod(remainder, 60)
    return f"{hours:02d}:{minutes:02d}:{seconds:02d}"

rc_cfg, out_cfg, err_cfg = run_root(["get-config"])
cfg = parse_json_best_effort(out_cfg)

c1, c2, c3, c4 = st.columns(4)
if not cfg:
    c1.warning("Could not load config for clock/timer.")
else:
    tz = ZoneInfo(cfg.get("timezone", "UTC"))
    now = datetime.now(tz)
    schedule_times = cfg.get("schedule_times", [])
    delta_to_next = get_next_run(now, schedule_times)

    with c1:
        # Custom HTML for the live clock metric, to be updated by JavaScript
        st.markdown(f"""
            <div data-testid="stMetric">
                <label style="color: var(--muted); font-size: .9rem;">Server Time</label>
                <div id="live-clock" style="font-size: 1.75rem; font-weight: 600;">{now.strftime("%H:%M:%S")}</div>
            </div>
        """, unsafe_allow_html=True)

    with c2:
        # Custom HTML for the countdown timer metric
        st.markdown(f"""
            <div data-testid="stMetric">
                <label style="color: var(--muted); font-size: .9rem;">Next Backup In</label>
                <div id="live-countdown" style="font-size: 1.75rem; font-weight: 600;">{format_timedelta(delta_to_next)}</div>
            </div>
        """, unsafe_allow_html=True)

    # JavaScript to update the clocks every second without reloading the page
    js_code = f"""
<script>
(function() {{
    // Ensure this script doesn't run multiple times on Streamlit re-renders
    if (window.backupdClockActive) {{
        return;
    }}
    window.backupdClockActive = true;

    const clockElement = document.getElementById('live-clock');
    const countdownElement = document.getElementById('live-countdown');

    if (!clockElement || !countdownElement) {{
        return; // Elements not found, stop the script
    }}

    // --- Server Time Clock ---
    // Initialize with the precise ISO timestamp from the server for accuracy
    let serverTime = new Date('{now.isoformat()}');

    // --- Countdown Timer ---
    let remainingSeconds = {int(delta_to_next.total_seconds())};

    const formatTime = (date) => String(date.getHours()).padStart(2, '0') + ':' + String(date.getMinutes()).padStart(2, '0') + ':' + String(date.getSeconds()).padStart(2, '0');

    const formatCountdown = (seconds) => {{
        if (seconds < 0) seconds = 0;
        const h = String(Math.floor(seconds / 3600)).padStart(2, '0');
        const m = String(Math.floor((seconds % 3600) / 60)).padStart(2, '0');
        const s = String(seconds % 60).padStart(2, '0');
        return `${{h}}:${{m}}:${{s}}`;
    }};

    const timerInterval = setInterval(() => {{
        if (!document.body.contains(clockElement) || !document.body.contains(countdownElement)) {{
            clearInterval(timerInterval);
            window.backupdClockActive = false;
            return;
        }}
        serverTime.setSeconds(serverTime.getSeconds() + 1);
        clockElement.innerText = formatTime(serverTime);
        if (remainingSeconds > 0) remainingSeconds--;
        countdownElement.innerText = formatCountdown(remainingSeconds);
    }}, 1000);
}})();
</script>
"""
    st.components.v1.html(js_code, height=0)

disk = data.get("disk", {})
total = int(disk.get("total_bytes", 0) or 0)
used = int(disk.get("used_bytes", 0) or 0)
free = int(disk.get("free_bytes", 0) or 0)
pct = (used / total) if total else 0.0

st.markdown("---")
st.subheader("Storage")
st.progress(min(max(pct, 0.0), 1.0))
st.caption(
    f"Used: **{hbytes(used)}** • Free: **{hbytes(free)}** • Total: **{hbytes(total)}** • ({pct*100:.1f}%)"
)

st.info("Use the sidebar to open **Backup** and **Storage & Retention**.")
