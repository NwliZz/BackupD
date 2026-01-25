import json
import streamlit as st

from _helpers import inject_css, run_root, parse_json_best_effort, badge, hbytes, show_logs


st.set_page_config(page_title="Backup Manager — BackupD", layout="wide")
inject_css()

st.title("Backup Manager")
st.caption("Decide what stays Local / Cloud (OneDrive), preview changes, then apply.")


# ---------- Session state ----------
if "bm_actions" not in st.session_state:
    st.session_state["bm_actions"] = {}
if "bm_pins" not in st.session_state:
    st.session_state["bm_pins"] = set()
if "bm_loaded_from_server" not in st.session_state:
    st.session_state["bm_loaded_from_server"] = False

# UI flow state
if "bm_view" not in st.session_state:
    st.session_state["bm_view"] = "list"  # "list" | "result"
if "bm_confirm_open" not in st.session_state:
    st.session_state["bm_confirm_open"] = False
if "bm_confirmed" not in st.session_state:
    st.session_state["bm_confirmed"] = False
if "bm_last_result" not in st.session_state:
    st.session_state["bm_last_result"] = None
if "bm_last_logs" not in st.session_state:
    st.session_state["bm_last_logs"] = ""


if "bm_clear_pending" not in st.session_state:
    st.session_state["bm_clear_pending"] = False
if "bm_reset_pins_from_server" not in st.session_state:
    st.session_state["bm_reset_pins_from_server"] = False

def _load_inventory():
    rc, out, err = run_root(["inventory"])
    inv = parse_json_best_effort(out)
    return rc, inv, out, err


def pretty_when(item):
    return item.get("stamp") or item.get("mtime") or "—"


def origin_label(item):
    o = (item.get("origin") or "unknown").lower()
    if o == "manual":
        return "Manual"
    if o == "scheduled":
        return "Scheduled"
    return "—"


def options_for(name: str, local_names: set, remote_names: set):
    in_l = name in local_names
    in_r = name in remote_names
    opts = [("none", "No change"), ("destroy", "🗑️ Destroy backup")]
    if in_l and in_r:
        opts += [("keep_local", "⬅️ Keep only Local"), ("keep_cloud", "➡️ Keep only Cloud")]
    elif in_l and not in_r:
        opts += [("copy_to_cloud", "☁️ Save also to Cloud")]
    elif in_r and not in_l:
        opts += [("copy_to_local", "💾 Save also to Local")]
    return opts


def set_action(name: str, action: str):
    st.session_state["bm_actions"][name] = {"action": action}


def undo_action(name: str):
    st.session_state["bm_actions"].pop(name, None)


def compute_preview(local_names: set, remote_names: set, actions: dict):
    final_local = set(local_names)
    final_remote = set(remote_names)
    deletes_local, deletes_remote = set(), set()
    adds_local, adds_remote = set(), set()

    for name, spec in (actions or {}).items():
        act = (spec or {}).get("action", "none")
        in_l = name in local_names
        in_r = name in remote_names

        if act == "destroy":
            if in_l:
                deletes_local.add(name)
            if in_r:
                deletes_remote.add(name)

        elif act == "keep_local":
            if in_r:
                deletes_remote.add(name)
            if (not in_l) and in_r:
                adds_local.add(name)

        elif act == "keep_cloud":
            if in_l:
                deletes_local.add(name)
            if (not in_r) and in_l:
                adds_remote.add(name)

        elif act == "copy_to_cloud":
            if in_l and not in_r:
                adds_remote.add(name)

        elif act == "copy_to_local":
            if in_r and not in_l:
                adds_local.add(name)

    final_local = (final_local | adds_local) - deletes_local
    final_remote = (final_remote | adds_remote) - deletes_remote

    return {
        "final_local": final_local,
        "final_remote": final_remote,
        "deletes_local": deletes_local,
        "deletes_remote": deletes_remote,
        "adds_local": adds_local,
        "adds_remote": adds_remote,
    }

def actions_snapshot_for(all_names: list[str]) -> dict:
    """Derive actions from widget state (act_<name>) so preview is always current."""
    snap = {}
    for n in all_names:
        v = st.session_state.get(f"act_{n}", st.session_state["bm_actions"].get(n, {}).get("action", "none"))
        if v and v != "none":
            snap[n] = {"action": v}
    return snap

def loc_state(name: str, scope: str) -> str:
    if scope == "local":
        now = name in local_names
        will_del = name in pv["deletes_local"]
        will_add = name in pv["adds_local"]
    else:
        now = name in remote_names
        will_del = name in pv["deletes_remote"]
        will_add = name in pv["adds_remote"]

    if now and will_del:
        return "delete"
    if (not now) and will_add:
        return "add"
    if now:
        return "present"
    return "missing"


def loc_dot(kind: str) -> str:
    # inline “dot” (no extra CSS needed)
    if kind == "present":
        return "<span style='display:inline-block;width:10px;height:10px;border-radius:50%;background:#22c55e;'></span>"
    if kind == "delete":
        return "<span style='display:inline-block;width:10px;height:10px;border-radius:50%;background:#ef4444;'></span> <span style='color:#ef4444'>(delete)</span>"
    if kind == "add":
        return "<span style='display:inline-block;width:10px;height:10px;border-radius:50%;background:#22c55e;'></span> <span style='color:#22c55e'>(add)</span>"
    return "<span style='display:inline-block;width:10px;height:10px;border-radius:50%;background:#94a3b8;'></span>"



def summarize_changes(local_names: set, remote_names: set, actions: dict):
    """Return a structured summary used by the confirm dialog."""
    buckets = {
        "destroy": [],
        "keep_local": [],
        "keep_cloud": [],
        "copy_to_cloud": [],
        "copy_to_local": [],
    }
    for name, spec in (actions or {}).items():
        act = (spec or {}).get("action", "none")
        if act in buckets:
            buckets[act].append(name)

    # sort newest-ish by filename (works with your timestamp naming)
    for k in buckets:
        buckets[k].sort(reverse=True)

    # counts of “will happen” operations (approximation of apply)
    will_delete_local = 0
    will_delete_cloud = 0
    will_copy_to_local = 0
    will_copy_to_cloud = 0

    for name in buckets["destroy"]:
        if name in local_names:
            will_delete_local += 1
        if name in remote_names:
            will_delete_cloud += 1

    for name in buckets["keep_local"]:
        # if exists remote -> delete remote; if missing local -> copy to local first
        if name in remote_names:
            will_delete_cloud += 1
        if name not in local_names and name in remote_names:
            will_copy_to_local += 1

    for name in buckets["keep_cloud"]:
        if name in local_names:
            will_delete_local += 1
        if name not in remote_names and name in local_names:
            will_copy_to_cloud += 1

    for name in buckets["copy_to_cloud"]:
        if name in local_names and name not in remote_names:
            will_copy_to_cloud += 1

    for name in buckets["copy_to_local"]:
        if name in remote_names and name not in local_names:
            will_copy_to_local += 1

    total_changes = sum(len(v) for v in buckets.values())
    return {
        "buckets": buckets,
        "total_changes": total_changes,
        "ops": {
            "delete_local": will_delete_local,
            "delete_cloud": will_delete_cloud,
            "copy_to_local": will_copy_to_local,
            "copy_to_cloud": will_copy_to_cloud,
        },
    }


def render_confirm_dialog(summary: dict, pinned_count: int):
    """Shows a lightbox-style dialog if available; otherwise shows an inline confirm card."""
    title = "Confirm apply"

    def _body():
        st.markdown("### Review changes")
        st.caption("Nothing is applied yet. Confirm to execute these operations.")

        ops = summary["ops"]
        a, b, c, d = st.columns(4)
        a.metric("Copy → Local", ops["copy_to_local"])
        b.metric("Copy → Cloud", ops["copy_to_cloud"])
        c.metric("Delete Local", ops["delete_local"])
        d.metric("Delete Cloud", ops["delete_cloud"])

        st.markdown("---")

        def block(label, items, kind="warn"):
            if not items:
                return
            badge(f"{label} ({len(items)})", kind)
            st.write("\n".join([f"• `{x}`" for x in items[:12]]))
            if len(items) > 12:
                st.caption(f"+ {len(items) - 12} more")

        b = summary["buckets"]
        block("Destroy backups", b["destroy"], "bad")
        block("Keep only Local", b["keep_local"], "warn")
        block("Keep only Cloud", b["keep_cloud"], "warn")
        block("Save also to Cloud", b["copy_to_cloud"], "ok")
        block("Save also to Local", b["copy_to_local"], "ok")

        st.markdown("---")
        st.caption(f"📌 Pinned backups (protected from auto-delete): {pinned_count}")

        c1, c2 = st.columns(2)
        if c1.button("Cancel", use_container_width=True, key="bm_cancel_confirm"):
            st.session_state["bm_confirm_open"] = False
            st.session_state["bm_confirmed"] = False
            st.rerun()

        if c2.button("Confirm", use_container_width=True, key="bm_yes_confirm"):
            st.session_state["bm_confirm_open"] = False
            st.session_state["bm_confirmed"] = True
            st.rerun()

    # Prefer Streamlit dialog (true lightbox)
    if hasattr(st, "dialog"):
        @st.dialog(title)
        def _dlg():
            _body()
        _dlg()
    else:
        # Fallback (still works, but not a real overlay)
        st.markdown("---")
        badge("Confirm apply (dialog not supported in this Streamlit version)", "warn")
        _body()


def render_result(res: dict, logs: str):
    ok = bool(res) and not res.get("errors")
    if ok:
        badge("Applied ✅", "ok")
    else:
        badge("Apply finished with warnings/errors", "warn")

    # Big summary cards
    copied_cloud = res.get("copied_to_cloud", []) if isinstance(res, dict) else []
    copied_local = res.get("copied_to_local", []) if isinstance(res, dict) else []
    del_local = res.get("deleted_local", []) if isinstance(res, dict) else []
    del_cloud = res.get("deleted_cloud", []) if isinstance(res, dict) else []
    errors = res.get("errors", []) if isinstance(res, dict) else []
    pins_saved = bool(res.get("pinned_saved")) if isinstance(res, dict) else False

    m1, m2, m3, m4 = st.columns(4)
    m1.metric("Copied → Cloud", len(copied_cloud))
    m2.metric("Copied → Local", len(copied_local))
    m3.metric("Deleted (Local)", len(del_local))
    m4.metric("Deleted (Cloud)", len(del_cloud))

    if pins_saved:
        st.caption("📌 Pinned list saved successfully.")

    if errors:
        st.markdown("### Issues")
        badge(f"Errors ({len(errors)})", "bad")
        for e in errors[:10]:
            name = e.get("name", "—")
            msg = e.get("error", "—")
            st.write(f"• `{name}` — {msg}")
        if len(errors) > 10:
            st.caption(f"+ {len(errors) - 10} more")

    def exp(label, items, kind):
        if not items:
            return
        with st.expander(f"{label} ({len(items)})", expanded=False):
            badge(label, kind)
            for n in items:
                st.write(f"• `{n}`")

    exp("Copied to Cloud", copied_cloud, "ok")
    exp("Copied to Local", copied_local, "ok")
    exp("Deleted Local", del_local, "bad")
    exp("Deleted Cloud", del_cloud, "bad")

    show_logs(logs, title="Details / logs")

    st.markdown("---")
    if st.button("✅ I understand", use_container_width=True, key="bm_ack"):
        # Reset to list view and reload fresh inventory
        st.session_state["bm_view"] = "list"
        st.session_state["bm_actions"] = {}
        st.session_state["bm_confirm_open"] = False
        st.session_state["bm_confirmed"] = False
        st.session_state["bm_last_result"] = None
        st.session_state["bm_last_logs"] = ""
        # Force pinned reload from server on next run
        st.session_state["bm_loaded_from_server"] = False
        st.rerun()


# ---------- RESULT VIEW ----------
if st.session_state["bm_view"] == "result":
    render_result(st.session_state.get("bm_last_result") or {}, st.session_state.get("bm_last_logs") or "")
    st.stop()


# ---------- LIST VIEW ----------
rc, inv, out_raw, err_raw = _load_inventory()
if rc != 0 or not inv:
    badge("Failed to load inventory", "bad")
    st.code((out_raw or "") + "\n" + (err_raw or ""), language="text")
    st.stop()

show_logs(err_raw)

local = inv.get("local", [])
remote = inv.get("remote", [])
local_names = {x["name"] for x in local}
remote_names = {x["name"] for x in remote}

# Clear decisions must happen BEFORE widgets are created
if st.session_state.get("bm_clear_pending"):
    for k in list(st.session_state.keys()):
        if k.startswith("act_"):
            del st.session_state[k]
    st.session_state["bm_actions"] = {}
    st.session_state["bm_clear_pending"] = False

# Load pinned once from server
if not st.session_state["bm_loaded_from_server"]:
    st.session_state["bm_pins"] = set(inv.get("pinned", []))
    st.session_state["bm_loaded_from_server"] = True

if st.session_state.get("bm_reset_pins_from_server"):
    st.session_state["bm_pins"] = set(inv.get("pinned", []))
    st.session_state["bm_reset_pins_from_server"] = False

# Build meta map (prefer local)
meta = {}
for item in remote:
    meta[item["name"]] = item
for item in local:
    meta[item["name"]] = item

all_names = sorted(set(local_names) | set(remote_names))

def sort_key(name: str):
    item = meta.get(name, {})
    return item.get("stamp") or item.get("mtime") or ""

all_names.sort(key=sort_key, reverse=True)

actions_snapshot = actions_snapshot_for(all_names)

pv = compute_preview(local_names, remote_names, actions_snapshot)
summary = summarize_changes(local_names, remote_names, actions_snapshot)

st.markdown("---")

c1, c2, c3, c4 = st.columns(4)
c1.metric("Local now", len(local_names))
c2.metric("Cloud now", len(remote_names))
c3.metric("Local after", len(pv["final_local"]))
c4.metric("Cloud after", len(pv["final_remote"]))

# Scrollable list container (keeps item visuals, prevents huge page)
st.markdown("## All backups")
with st.container(height=640, border=False):
    for name in all_names:
        item = meta.get(name, {"name": name, "size_bytes": 0, "stamp": None, "mtime": None, "origin": "unknown"})
        size = hbytes(item.get("size_bytes") or 0)
        when = pretty_when(item)
        origin = origin_label(item)

        deleting_everywhere = (name in pv["deletes_local"] or name in pv["deletes_remote"]) and (
            (name not in pv["final_local"]) and (name not in pv["final_remote"])
        )

        with st.container():
            left, mid, right = st.columns([7, 2, 4], vertical_alignment="top")

            with left:
                if deleting_everywhere:
                    badge("Will be destroyed", "bad")
                    st.markdown(f"**{name}**")
                    st.caption(f"~~{when} • {size} • {origin}~~")
                else:
                    st.markdown(f"**{name}**")
                    st.caption(f"{when} • {size} • {origin}")

            with mid:
                st.caption("Locations")
                st.markdown(f"💾 Local: {loc_dot(loc_state(name, 'local'))}", unsafe_allow_html=True)
                st.markdown(f"☁️ Cloud: {loc_dot(loc_state(name, 'remote'))}", unsafe_allow_html=True)

            with right:
                opts = options_for(name, local_names, remote_names)
                label_map = {k: v for k, v in opts}
                current = st.session_state.get(
                    f"act_{name}",
                    st.session_state["bm_actions"].get(name, {}).get("action", "none"),
                )

                picked = st.selectbox(
                    "Action",
                    options=[k for k, _ in opts],
                    format_func=lambda k: label_map.get(k, k),
                    index=[k for k, _ in opts].index(current) if current in [k for k, _ in opts] else 0,
                    key=f"act_{name}",
                )
                # IMPORTANT: do NOT call set_action() here

                pin_val = (name in st.session_state["bm_pins"])
                new_pin = st.checkbox("📌 Pinned (skip auto-delete)", value=pin_val, key=f"pin_{name}")
                if new_pin:
                    st.session_state["bm_pins"].add(name)
                else:
                    st.session_state["bm_pins"].discard(name)

                if picked != "none":
                    if st.button("↩️ Undo", key=f"undo_{name}"):
                        st.session_state[f"act_{name}"] = "none"
                        undo_action(name)
                        st.rerun()

        st.divider()

# Bottom controls ONLY
st.markdown("---")
b1, b2 = st.columns([1, 1])

if b1.button("🧽 Clear decisions", use_container_width=True, key="bm_clear_bottom"):
    st.session_state["bm_clear_pending"] = True
    st.session_state["bm_reset_pins_from_server"] = True
    st.rerun()
    # reset all action widgets
    for k in list(st.session_state.keys()):
        if k.startswith("act_"):
            st.session_state[k] = "none"

    st.session_state["bm_actions"] = {}
    st.session_state["bm_pins"] = set(inv.get("pinned", []))
    st.rerun()

apply_clicked = b2.button(
    "✅ Apply decisions",
    use_container_width=True,
    key="bm_apply",
    disabled=(summary["total_changes"] == 0),
)

if apply_clicked:
    st.session_state["bm_confirm_open"] = True
    st.session_state["bm_confirmed"] = False
    st.rerun()

# Confirm lightbox (dialog)
if st.session_state["bm_confirm_open"]:
    render_confirm_dialog(summary, pinned_count=len(st.session_state["bm_pins"]))

# After confirm -> apply and switch to Result view
if st.session_state["bm_confirmed"]:
    actions_snapshot = actions_snapshot_for(all_names)
    plan = {
        "actions": actions_snapshot,
        "pinned": sorted(list(st.session_state["bm_pins"])),
    }
    with st.spinner("Applying changes…"):
        rc2, out2, err2 = run_root(["manage-apply"], input_text=json.dumps(plan))
    res = parse_json_best_effort(out2) or {}

    st.session_state["bm_last_result"] = res
    st.session_state["bm_last_logs"] = (err2 or "").strip()
    st.session_state["bm_confirmed"] = False
    st.session_state["bm_confirm_open"] = False
    st.session_state["bm_view"] = "result"
    st.rerun()
