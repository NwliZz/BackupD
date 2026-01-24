import json
import subprocess
import streamlit as st

st.set_page_config(page_title="Storage & Retention — BackupD", layout="wide")
st.title("Storage & Retention")

def run_root(cmd, input_text=None):
    p = subprocess.run(
        ["sudo", "/usr/local/sbin/backupctl"] + cmd,
        input=input_text,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
    )
    return p.returncode, p.stdout

rc, out = run_root(["get-config"])
if rc != 0:
    st.error(out); st.stop()
cfg = json.loads(out)

st.subheader("Retention policy")

def tier_editor(scope: str):
    pol = cfg.get("retention", {}).get(scope, {})
    st.markdown(f"### {scope.capitalize()}")
    ka = st.number_input(f"{scope}: keep ALL for days", min_value=0, max_value=3650, value=int(pol.get("keep_all_days", 0)), key=f"{scope}_ka")
    kd = st.number_input(f"{scope}: keep DAILY until days", min_value=0, max_value=3650, value=int(pol.get("keep_daily_until_days", 0)), key=f"{scope}_kd")
    kw = st.number_input(f"{scope}: keep WEEKLY until days", min_value=0, max_value=3650, value=int(pol.get("keep_weekly_until_days", 0)), key=f"{scope}_kw")
    km = st.number_input(f"{scope}: keep MONTHLY until days", min_value=0, max_value=3650, value=int(pol.get("keep_monthly_until_days", 0)), key=f"{scope}_km")
    return {"keep_all_days": int(ka), "keep_daily_until_days": int(kd), "keep_weekly_until_days": int(kw), "keep_monthly_until_days": int(km)}

c1, c2 = st.columns(2)
with c1:
    local_pol = tier_editor("local")
with c2:
    remote_pol = tier_editor("remote")

st.divider()
st.subheader("Dry-run & cleanup")

b1, b2, b3 = st.columns(3)
with b1:
    if st.button("Refresh dry-run plan"):
        rc2, out2 = run_root(["retention-plan"])
        if rc2 == 0:
            st.session_state["plan"] = json.loads(out2)
        else:
            st.error(out2)
with b2:
    if st.button("Run cleanup now"):
        rc2, out2 = run_root(["retention-apply"])
        if rc2 == 0:
            st.success("Cleanup done")
            st.session_state["plan"] = json.loads(out2)
        else:
            st.error(out2)
with b3:
    if st.button("Save retention settings"):
        new = dict(cfg)
        new.setdefault("retention", {})
        new["retention"]["local"] = local_pol
        new["retention"]["remote"] = remote_pol
        rc2, out2 = run_root(["set-config"], input_text=json.dumps(new))
        if rc2 == 0:
            st.success("Saved.")
        else:
            st.error(out2)

plan = st.session_state.get("plan")
if plan:
    st.json(plan)

st.info("Tip: OneDrive deletions typically go to the recycle bin; you may need to empty it to free quota.")
