import json
import streamlit as st

from _helpers import inject_css, run_root, parse_json_best_effort, badge, show_logs

st.set_page_config(page_title="Storage & Retention — BackupD", layout="wide")
inject_css()

st.title("Storage & Retention")
st.markdown("🧹 **Prune locally** + ☁️ **prune remotely** based on a tiered policy (keep-all → daily → weekly → monthly).")

rc, out, err = run_root(["get-config"])
cfg = parse_json_best_effort(out)
if rc != 0 or not cfg:
    badge("Failed to load config", "bad")
    st.code(out + "\n" + err, language="text")
    st.stop()

show_logs(err)

st.subheader("Policy editor")

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

st.markdown("---")
b1, b2, b3 = st.columns(3)
refresh = b1.button("🔎 Refresh dry-run plan", use_container_width=True)
cleanup = b2.button("🧹 Run cleanup now", use_container_width=True)
save = b3.button("💾 Save policy", use_container_width=True)

if refresh:
    rc2, out2, err2 = run_root(["retention-plan"])
    plan = parse_json_best_effort(out2)
    if rc2 == 0 and plan:
        st.session_state["plan"] = plan
        badge("Dry-run plan: READY", "ok")
    else:
        badge("Dry-run plan: FAILED", "bad")
        st.code(out2 + "\n" + err2, language="text")
    show_logs(err2)

if cleanup:
    rc2, out2, err2 = run_root(["retention-apply"])
    plan = parse_json_best_effort(out2)
    if rc2 == 0 and plan:
        st.session_state["plan"] = plan
        badge("Cleanup: DONE ✅", "ok")
    else:
        badge("Cleanup: FAILED ❌", "bad")
        st.code(out2 + "\n" + err2, language="text")
    show_logs(err2)

if save:
    new = dict(cfg)
    new.setdefault("retention", {})
    new["retention"]["local"] = local_pol
    new["retention"]["remote"] = remote_pol
    rc2, out2, err2 = run_root(["set-config"], input_text=json.dumps(new))
    if rc2 == 0:
        badge("Saved ✅", "ok")
    else:
        badge("Save FAILED ❌", "bad")
        st.code(out2 + "\n" + err2, language="text")
    show_logs(err2)

plan = st.session_state.get("plan")
if plan:
    st.subheader("Plan details")
    l = plan.get("local", {})
    r = plan.get("remote", {})
    c1, c2, c3, c4 = st.columns(4)
    c1.metric("Local delete", len(l.get("delete", [])))
    c2.metric("Local keep", len(l.get("keep", [])))
    c3.metric("Remote delete", len(r.get("delete", [])))
    c4.metric("Remote keep", len(r.get("keep", [])))

    with st.expander("Local: delete list"):
        st.write(l.get("delete", []))
    with st.expander("Remote: delete list"):
        st.write(r.get("delete", []))

st.info("Note: OneDrive deletions can land in recycle bin. You may need to empty it to free quota.")