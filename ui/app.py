import streamlit as st

from _helpers import inject_css, run_root, parse_json_best_effort, badge, hbytes, show_logs

st.set_page_config(page_title="BackupD", layout="wide")
inject_css()

st.title("BackupD")
badge("LOCALHOST UI • Access via SSH tunnel", "warn")

st.markdown(
    """
**Tunnel command (from your PC):**
```bash
ssh -L 8050:127.0.0.1:8050 speg-vps
```
Open: http://localhost:8050
""",
    help="UI listens on 127.0.0.1 only. Keep it that way.",
)

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
