import json
import subprocess
import streamlit as st

st.set_page_config(page_title="Backup — BackupD", layout="wide")
st.title("Backup")

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

left, right = st.columns([1, 1])

with left:
    st.subheader("Mode & targets")
    mode = st.radio("Backup mode", ["custom", "hestia"], index=0 if cfg.get("mode")=="custom" else 1)
    if mode == "hestia":
        st.write("Include: `/backup` (Hestia backups)")
        include_paths_list = ["/backup"]
    else:
        include_paths = st.text_area("Include paths (one per line)", value="\n".join(cfg.get("include_paths", [])), height=120)
        include_paths_list = [l.strip() for l in include_paths.splitlines() if l.strip()]

    exclude_globs = st.text_area("Exclude patterns (one per line)", value="\n".join(cfg.get("exclude_globs", [])), height=160)
    exclude_globs_list = [l.strip() for l in exclude_globs.splitlines() if l.strip()]

    st.subheader("Schedule")
    schedule_times = st.text_input("Backup times (HH:MM, comma-separated)", value=",".join(cfg.get("schedule_times", ["03:00"])))
    schedule_times_list = [t.strip() for t in schedule_times.split(",") if t.strip()]
    tz = st.text_input("Timezone", value=cfg.get("timezone", "Europe/Athens"))
    tol = st.number_input("Tolerance (minutes)", min_value=1, max_value=10, value=int(cfg.get("tolerance_minutes", 2)))

with right:
    st.subheader("Databases")
    db_cfg = cfg.get("db", {})
    db_enabled = st.toggle("Enable DB discovery/dumps", value=bool(db_cfg.get("enabled", True)))
    policy = st.selectbox("DB dump policy", ["hybrid", "daily", "every_backup"], index=["hybrid","daily","every_backup"].index(db_cfg.get("policy","hybrid")))
    dump_times = st.text_input("DB dump times (HH:MM, comma-separated)", value=",".join(db_cfg.get("dump_times", ["03:05"])))
    dump_times_list = [t.strip() for t in dump_times.split(",") if t.strip()]

    cA, cB = st.columns(2)
    with cA:
        if st.button("Discover live DBs"):
            rc2, out2 = run_root(["discover-dbs"])
            if rc2 == 0:
                st.session_state["db_report"] = json.loads(out2)
            else:
                st.error(out2)
    with cB:
        if st.button("Test DB access"):
            rc2, out2 = run_root(["test-dbs"])
            if rc2 == 0:
                st.json(json.loads(out2))
            else:
                st.error(out2)

    rep = st.session_state.get("db_report")
    mysql_selected = []
    pg_selected = []
    sys_mysql = ",".join(cfg.get("system_db_defaults", {}).get("mysql", ["information_schema","performance_schema","sys"]))
    sys_pg = ",".join(cfg.get("system_db_defaults", {}).get("postgres", ["template0","template1"]))

    if rep:
        st.markdown("### DB Discovery Report")
        st.json(rep.get("raw_report", {}))

        mysql_all = rep.get("mysql_dbs", [])
        pg_all = rep.get("postgres_dbs", [])
        sel = rep.get("selected", {"mysql": [], "postgres": []})

        mysql_selected = st.multiselect("MariaDB/MySQL DBs", options=mysql_all, default=sel.get("mysql", []))
        pg_selected = st.multiselect("PostgreSQL DBs", options=pg_all, default=sel.get("postgres", []))

        st.markdown("### Advanced: system DB defaults")
        sys_mysql = st.text_input("MySQL system DBs (comma-separated)", value=sys_mysql)
        sys_pg = st.text_input("Postgres system DBs (comma-separated)", value=sys_pg)

    st.subheader("Cloud")
    upload_enabled = st.toggle("Upload enabled", value=bool(cfg.get("upload_enabled", True)))
    rclone_remote = st.text_input("rclone remote", value=cfg.get("rclone_remote", "onedrive"))
    remote_path = st.text_input("Remote base path", value=cfg.get("remote_path", "VPS-Backups"))

    b1, b2, b3 = st.columns(3)
    with b1:
        if st.button("Test OneDrive connection"):
            rc2, out2 = run_root(["test-cloud"])
            if rc2 == 0:
                st.success("OK"); st.code(out2)
            else:
                st.error(out2)
    with b2:
        if st.button("Backup now"):
            rc2, out2 = run_root(["backup-now"])
            if rc2 == 0:
                st.success("Backup completed"); st.json(json.loads(out2))
            else:
                st.error(out2)
    with b3:
        if st.button("Save settings"):
            new = dict(cfg)
            new["mode"] = mode
            if mode == "custom":
                new["include_paths"] = include_paths_list
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

            rc2, out2 = run_root(["set-config"], input_text=json.dumps(new))
            if rc2 == 0:
                st.success("Saved.")
            else:
                st.error(out2)
