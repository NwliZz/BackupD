"""Streamlit dashboard for BackupD status, storage, and live timers."""

import streamlit as st
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

from _helpers import inject_css, run_root, parse_json_best_effort, badge, hbytes, show_logs

# ---- Page setup and theme helpers ----
st.set_page_config(page_title="BackupD", layout="wide")
inject_css()

# ---- Header and connectivity notice ----
st.title("BackupD")
badge("LOCALHOST UI • Access via SSH tunnel", "warn")

# ---- Load status from backend ----
rc, out, err = run_root(["status"])
data = parse_json_best_effort(out)

if rc != 0 or not data:
    badge("Status: FAILED to read", "bad")
    st.code((out or "") + "\n" + (err or ""), language="text")
    st.stop()

# ---- Status banner and logs ----
badge("Status: OK", "ok")
show_logs(err)

# ---- Top-line metrics ----
# Layout for live clock and countdown.
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

# Load schedule config used to seed the live clock/timer.
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

    # Match Streamlit theme typography/colors inside the embedded HTML components.
    theme_font = st.get_option("theme.font") or "Source Sans Pro"
    theme_text = st.get_option("theme.primaryColor") or st.get_option("theme.textColor") or "#e6e6e6"

    # Render the live clock in its own component so JS updates reliably.
    with c1:
        clock_html = f"""
<style>
  html, body {{
    margin: 0;
    padding: 0;
    background: transparent;
  }}
  .metric {{
    font-family: "{theme_font}", "Source Sans Pro", "Inter", "Segoe UI", system-ui, sans-serif;
    color: {theme_text};
  }}
  .metric .label {{ opacity: .7; font-size: .9rem; }}
  .metric .value {{ font-size: 1.75rem; font-weight: 600; }}
</style>
<div class="metric">
  <div class="label">Server Time</div>
  <div id="live-clock" class="value">{now.strftime("%H:%M:%S")}</div>
</div>
<script>
(function() {{
  const clockElement = document.getElementById('live-clock');
  if (!clockElement) return;
  let serverTime = new Date('{now.isoformat()}');
  const formatTime = (date) =>
    String(date.getHours()).padStart(2, '0') + ':' +
    String(date.getMinutes()).padStart(2, '0') + ':' +
    String(date.getSeconds()).padStart(2, '0');
  setInterval(() => {{
    serverTime.setSeconds(serverTime.getSeconds() + 1);
    clockElement.innerText = formatTime(serverTime);
  }}, 1000);
}})();
</script>
"""
        st.components.v1.html(clock_html, height=95)

    # Render the countdown timer in a separate component.
    with c2:
        countdown_html = f"""
<style>
  html, body {{
    margin: 0;
    padding: 0;
    background: transparent;
  }}
  .metric {{
    font-family: "{theme_font}", "Source Sans Pro", "Inter", "Segoe UI", system-ui, sans-serif;
    color: {theme_text};
  }}
  .metric .label {{ opacity: .7; font-size: .9rem; }}
  .metric .value {{ font-size: 1.75rem; font-weight: 600; }}
</style>
<div class="metric">
  <div class="label">Next Backup In</div>
  <div id="live-countdown" class="value">{format_timedelta(delta_to_next)}</div>
</div>
<script>
(function() {{
  const countdownElement = document.getElementById('live-countdown');
  if (!countdownElement) return;
  let remainingSeconds = {int(delta_to_next.total_seconds())};
  const formatCountdown = (seconds) => {{
    if (seconds < 0) seconds = 0;
    const h = String(Math.floor(seconds / 3600)).padStart(2, '0');
    const m = String(Math.floor((seconds % 3600) / 60)).padStart(2, '0');
    const s = String(seconds % 60).padStart(2, '0');
    return `${{h}}:${{m}}:${{s}}`;
  }};
  setInterval(() => {{
    if (remainingSeconds > 0) remainingSeconds--;
    countdownElement.innerText = formatCountdown(remainingSeconds);
  }}, 1000);
}})();
</script>
"""
        st.components.v1.html(countdown_html, height=95)

# ---- Storage section ----
disk = data.get("disk", {})
total = int(disk.get("total_bytes", 0) or 0)
used = int(disk.get("used_bytes", 0) or 0)
free = int(disk.get("free_bytes", 0) or 0)
local_used = int(data.get("local_bytes", 0) or 0)
other_used = max(used - local_used, 0)

def clamp_unit(value: float) -> float:
    """Clamp a ratio into the [0, 1] range for progress bars."""
    return min(max(value, 0.0), 1.0)

pct = clamp_unit((used / total) if total else 0.0)
other_pct = clamp_unit((other_used / total) if total else 0.0)
backup_pct = clamp_unit((local_used / total) if total else 0.0)

# ---- Storage metrics and visual bar ----
st.markdown("---")
st.subheader("Storage")
theme_primary = st.get_option("theme.primaryColor") or "#1f77b4"
bar_html = f"""
<style>
  .storage-bar {{
    width: 100%;
    height: 18px;
    background: rgba(154, 160, 166, 0.25);
    border-radius: 6px;
    overflow: hidden;
    display: flex;
  }}
  .storage-bar__segment {{
    height: 100%;
  }}
  .storage-bar__segment--other {{
    width: {other_pct * 100:.2f}%;
    background: #9aa0a6;
  }}
  .storage-bar__segment--backup {{
    width: {backup_pct * 100:.2f}%;
    background: {theme_primary};
  }}
</style>
<div class="storage-bar" role="img" aria-label="Storage usage">
  <div class="storage-bar__segment storage-bar__segment--other"></div>
  <div class="storage-bar__segment storage-bar__segment--backup"></div>
</div>
"""
st.markdown(bar_html, unsafe_allow_html=True)
st.caption(
    f"Used: **{hbytes(used)}** • Free: **{hbytes(free)}** • Total: **{hbytes(total)}** • ({pct*100:.1f}%)"
)
st.caption(
    f"Other used: **{hbytes(other_used)}** • Local backups: **{hbytes(local_used)}** • Free: **{hbytes(free)}**"
)
