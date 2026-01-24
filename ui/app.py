import streamlit as st
import json
import subprocess

st.set_page_config(page_title="BackupD", layout="wide")
st.title("BackupD — VPS Backup Manager")

st.markdown("""This UI runs **on localhost only** by default.

Access it via SSH tunnel:

```bash
ssh -L 8050:127.0.0.1:8050 manos@<VPS_IP>
```

Then open: http://localhost:8050
""")

def run_root(cmd, input_text=None):
    p = subprocess.run(
        ["sudo", "/usr/local/sbin/backupctl"] + cmd,
        input=input_text,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
    )
    return p.returncode, p.stdout

rc, out = run_root(["status"])
if rc == 0:
    st.subheader("Status")
    st.json(json.loads(out))
else:
    st.error(out)

st.info("Use the left sidebar to open **Backup** and **Storage & Retention**.")
