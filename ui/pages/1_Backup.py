"""Backup configuration and manual run controls."""

import json
import streamlit as st

from _helpers import inject_css, run_root, parse_json_best_effort, badge, show_logs

# ---- Page setup and theme helpers ----
st.set_page_config(page_title="Backup — BackupD", layout="wide")
inject_css()

# ---- Page header ----
st.title("Backup")
st.markdown("🗂️ **Build archive** ➜ 🗄️ **DB dumps** ➜ ☁️ **Upload** ➜ 🧹 **Retention**")

# ---- Load config from backend ----
rc, out, err = run_root(["get-config"])
cfg = parse_json_best_effort(out)
if rc != 0 or not cfg:
    badge("Failed to load config", "bad")
    st.code(out + "\n" + err, language="text")
    st.stop()

show_logs(err)

# ====== TARGETS ======
# Configure included paths, schedules, and exclusions.
st.subheader("Targets & Schedule")

a, b = st.columns([1, 1])
with a:
    mode = st.radio("Backup mode", ["custom", "hestia"], index=0 if cfg.get("mode") == "custom" else 1)
    if mode == "hestia":
        badge("Hestia mode: includes /backup", "ok")
        include_paths_list = ["/backup"]
        st.code("/backup", language="text")
    else:
        include_paths = st.text_area("Include paths (one per line)", value="\n".join(cfg.get("include_paths", [])), height=120)
        include_paths_list = [l.strip() for l in include_paths.splitlines() if l.strip()]

with b:
    schedule_times = st.text_input("Backup times (HH:MM, comma-separated)", value=",".join(cfg.get("schedule_times", ["03:00"])))
    schedule_times_list = [t.strip() for t in schedule_times.split(",") if t.strip()]
    tz = st.text_input("Timezone", value=cfg.get("timezone", "Europe/Athens"))
    tol = st.number_input("Tolerance window (minutes)", min_value=1, max_value=10, value=int(cfg.get("tolerance_minutes", 2)))

with st.expander("Advanced: Excludes"):
    exclude_globs = st.text_area("Exclude patterns (one per line)", value="\n".join(cfg.get("exclude_globs", [])), height=180)
    exclude_globs_list = [l.strip() for l in exclude_globs.splitlines() if l.strip()]

# ====== DATABASES ======
# Configure database discovery and dump schedules.
st.markdown("---")
st.subheader("Databases")

db_cfg = cfg.get("db", {})
db_enabled = st.toggle("Enable DB discovery/dumps", value=bool(db_cfg.get("enabled", True)))

colA, colB, colC = st.columns([1, 1, 1])
with colA:
    policy = st.selectbox("DB dump policy", ["hybrid", "daily", "every_backup"],
                          index=["hybrid", "daily", "every_backup"].index(db_cfg.get("policy", "hybrid")))
with colB:
    dump_times = st.text_input("DB dump times (HH:MM, comma-separated)", value=",".join(db_cfg.get("dump_times", ["03:05"])))
    dump_times_list = [t.strip() for t in dump_times.split(",") if t.strip()]
with colC:
    st.caption("Tip: for WP + Pretalx critical restores, use **every_backup**.")

btn1, btn2, btn3 = st.columns(3)
with btn1:
    discover = st.button("🔎 Discover live DBs", use_container_width=True)
with btn2:
    testdb = st.button("🧪 Test DB access", use_container_width=True)
with btn3:
    st.write("")

if discover:
    rc2, out2, err2 = run_root(["discover-dbs"])
    rep = parse_json_best_effort(out2)
    if rc2 == 0 and rep:
        st.session_state["db_report"] = rep
        badge("DB discovery: OK", "ok")
    else:
        badge("DB discovery: FAILED", "bad")
        st.code(out2 + "\n" + err2, language="text")

if testdb:
    rc2, out2, err2 = run_root(["test-dbs"])
    res = parse_json_best_effort(out2)
    if rc2 == 0 and res:
        c1, c2 = st.columns(2)
        for col, key, label in [(c1, "mysql", "MariaDB/MySQL"), (c2, "postgres", "PostgreSQL")]:
            ok = bool(res.get(key, {}).get("ok"))
            with col:
                badge(f"{label}: {'OK' if ok else 'FAILED'}", "ok" if ok else "bad")
                st.code(res.get(key, {}).get("detail", "").strip() or "—", language="text")
        show_logs(err2)
    else:
        badge("DB test: FAILED", "bad")
        st.code(out2 + "\n" + err2, language="text")

rep = st.session_state.get("db_report")

mysql_selected, pg_selected = [], []
sys_mysql = ",".join(cfg.get("system_db_defaults", {}).get("mysql", ["information_schema", "performance_schema", "sys"]))
sys_pg = ",".join(cfg.get("system_db_defaults", {}).get("postgres", ["template0", "template1"]))

if rep:
    mysql_all = rep.get("mysql_dbs", [])
    pg_all = rep.get("postgres_dbs", [])
    sel = rep.get("selected", {"mysql": [], "postgres": []})

    st.markdown("#### DB Discovery Report")
    left, right = st.columns(2)

    with left:
        badge(f"MySQL found: {len(mysql_all)} • selected: {len(sel.get('mysql', []))}", "ok")
        mysql_selected = st.multiselect("Select MySQL DBs to dump", options=mysql_all, default=sel.get("mysql", []))
        with st.expander("Advanced: MySQL system DB defaults"):
            sys_mysql = st.text_input("System DBs (comma-separated)", value=sys_mysql)

    with right:
        badge(f"Postgres found: {len(pg_all)} • selected: {len(sel.get('postgres', []))}", "ok")
        pg_selected = st.multiselect("Select Postgres DBs to dump", options=pg_all, default=sel.get("postgres", []))
        with st.expander("Advanced: Postgres system DB defaults"):
            sys_pg = st.text_input("System DBs (comma-separated)", value=sys_pg)

    with st.expander("Advanced: raw discovery details"):
        st.json(rep.get("raw_report", {}))

# ====== CLOUD + ACTIONS ======
# Configure remote storage and trigger immediate actions.
st.markdown("---")
st.subheader("Cloud & Actions")

c1, c2 = st.columns([1, 1])
with c1:
    upload_enabled = st.toggle("☁️ Upload enabled", value=bool(cfg.get("upload_enabled", True)))
    rclone_remote = st.text_input("rclone remote name", value=cfg.get("rclone_remote", "onedrive"))
    remote_path = st.text_input("Remote base path", value=cfg.get("remote_path", "VPS-Backups"))

with c2:
    b1, b2, b3 = st.columns(3)
    testcloud = b1.button("🔌 Test OneDrive", use_container_width=True)
    backupnow = b2.button("🚀 Backup now", use_container_width=True)
    save = b3.button("💾 Save", use_container_width=True)

    if testcloud:
        rc2, out2, err2 = run_root(["test-cloud"])
        if rc2 == 0:
            badge("Cloud connection: OK", "ok")
            st.code(out2.strip(), language="text")
        else:
            badge("Cloud connection: FAILED", "bad")
            st.code(out2 + "\n" + err2, language="text")

    if backupnow:
        with st.spinner("Running backup…"):
            rc2, out2, err2 = run_root(["backup-now"])
        res = parse_json_best_effort(out2)
        if rc2 == 0 and res and res.get("ok"):
            badge("Backup: SUCCESS ✅", "ok")
        else:
            badge("Backup: FAILED ❌", "bad")

        # Pretty summary
        if res:
            cols = st.columns(4)
            cols[0].metric("Uploaded", "Yes" if res.get("uploaded") else "No")
            cols[1].metric("Local pruned", res.get("retention_local_deleted", 0))
            cols[2].metric("Remote pruned", res.get("retention_remote_deleted", 0))
            cols[3].metric("DB dumps", "Yes" if res.get("db_dump_dir") else "No")

            st.markdown("**Artifacts**")
            st.code(
                "\n".join([
                    f"archive: {res.get('archive_path') or '—'}",
                    f"db_dump_dir: {res.get('db_dump_dir') or '—'}",
                ]),
                language="text",
            )
        else:
            st.code(out2, language="text")

        show_logs(err2, "Logs (stderr)")

if save:
    # Build and persist a validated config payload.
    new = dict(cfg)
    new["mode"] = mode
    if mode == "custom":
        new["include_paths"] = include_paths_list

    # excludes
    if mode == "hestia":
        new["exclude_globs"] = cfg.get("exclude_globs", [])
    else:
        new["exclude_globs"] = exclude_globs_list

    new["schedule_times"] = schedule_times_list
    new["timezone"] = tz
    new["tolerance_minutes"] = int(tol)

    new["upload_enabled"] = bool(upload_enabled)
    new["rclone_remote"] = rclone_remote.strip()
    new["remote_path"] = remote_path.strip()

    new_db = dict(db_cfg)
    new_db["enabled"] = bool(db_enabled)
    new_db["policy"] = policy
    new_db["dump_times"] = dump_times_list

    if rep:
        new.setdefault("system_db_defaults", {})
        new["system_db_defaults"] = {
            "mysql": [x.strip() for x in sys_mysql.split(",") if x.strip()],
            "postgres": [x.strip() for x in sys_pg.split(",") if x.strip()],
        }
        new_db.setdefault("mysql", {})
        new_db.setdefault("postgres", {})
        new_db["mysql"]["include_dbs"] = mysql_selected
        new_db["postgres"]["include_dbs"] = pg_selected
        new_db["mysql"]["exclude_system_dbs"] = new["system_db_defaults"]["mysql"]
        new_db["postgres"]["exclude_system_dbs"] = new["system_db_defaults"]["postgres"]

    new["db"] = new_db

    rc2, out2, err2 = run_root(["set-config"], input_text=json.dumps(new))
    if rc2 == 0:
        badge("Saved ✅", "ok")
    else:
        badge("Save FAILED ❌", "bad")
        st.code(out2 + "\n" + err2, language="text")
