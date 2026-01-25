import json
import streamlit as st

from _helpers import inject_css, run_root, parse_json_best_effort, badge, hbytes, show_logs

st.set_page_config(page_title="Backup Manager — BackupD", layout="wide")
inject_css()

st.title("Backup Manager")
st.caption("Decide what stays Local / Cloud (OneDrive), preview changes, then apply.")

# Reload inventory on page load + refresh button
top = st.columns([1, 1, 6])
refresh = top[0].button("🔄 Refresh", use_container_width=True)
clear = top[1].button("🧽 Clear decisions", use_container_width=True)

if "bm_actions" not in st.session_state or refresh:
    st.session_state["bm_actions"] = {}
if "bm_pins" not in st.session_state or refresh:
    st.session_state["bm_pins"] = set()

if clear:
    st.session_state["bm_actions"] = {}
    st.session_state["bm_pins"] = set()

rc, out, err = run_root(["inventory"])
inv = parse_json_best_effort(out)
if rc != 0 or not inv:
    badge("Failed to load inventory", "bad")
    st.code(out + "\n" + err, language="text")
    st.stop()

show_logs(err)

local = inv.get("local", [])
remote = inv.get("remote", [])

local_names = {x["name"] for x in local}
remote_names = {x["name"] for x in remote}

# initialize pins from server only once unless user starts editing
if not st.session_state["bm_pins"]:
    for n in inv.get("pinned", []):
        st.session_state["bm_pins"].add(n)

# Helper: pretty date
def pretty_when(item):
    return item.get("stamp") or item.get("mtime") or "—"

def origin_label(item):
    o = (item.get("origin") or "unknown").lower()
    if o == "manual":
        return "Manual"
    if o == "scheduled":
        return "Scheduled"
    return "—"

def options_for(name: str):
    in_l = name in local_names
    in_r = name in remote_names
    opts = [("none", "No change")]
    opts.append(("destroy", "🗑️ Destroy backup"))
    if in_l and in_r:
        opts.append(("keep_local", "⬅️ Keep only Local"))
        opts.append(("keep_cloud", "➡️ Keep only Cloud"))
    elif in_l and not in_r:
        opts.append(("copy_to_cloud", "☁️ Save also to Cloud"))
    elif in_r and not in_l:
        opts.append(("copy_to_local", "💾 Save also to Local"))
    return opts

def set_action(name: str, action: str):
    st.session_state["bm_actions"][name] = {"action": action}

def undo_action(name: str):
    if name in st.session_state["bm_actions"]:
        del st.session_state["bm_actions"][name]

# Build lookup maps
meta = {}
for item in local:
    meta[item["name"]] = item
for item in remote:
    meta.setdefault(item["name"], item)

all_names = sorted(set(local_names) | set(remote_names), reverse=True)

# Compute preview “final state”
def compute_preview():
    final_local = set(local_names)
    final_remote = set(remote_names)

    deletes_local = set()
    deletes_remote = set()
    adds_local = set()
    adds_remote = set()

    for name, spec in st.session_state["bm_actions"].items():
        act = spec.get("action", "none")
        in_l = name in local_names
        in_r = name in remote_names

        if act == "destroy":
            if in_l:
                deletes_local.add(name)
            if in_r:
                deletes_remote.add(name)

        elif act == "keep_local":
            # ensure local exists; delete remote
            if in_r:
                deletes_remote.add(name)
            if not in_l and in_r:
                adds_local.add(name)

        elif act == "keep_cloud":
            if in_l:
                deletes_local.add(name)
            if not in_r and in_l:
                adds_remote.add(name)

        elif act == "copy_to_cloud":
            if in_l and not in_r:
                adds_remote.add(name)

        elif act == "copy_to_local":
            if in_r and not in_l:
                adds_local.add(name)

    # Apply deletes and adds to compute final
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

pv = compute_preview()

st.markdown("---")

# Summary metrics
c1, c2, c3, c4 = st.columns(4)
c1.metric("Local now", len(local_names))
c2.metric("Cloud now", len(remote_names))
c3.metric("Local after", len(pv["final_local"]))
c4.metric("Cloud after", len(pv["final_remote"]))

def render_section(title: str, names: list[str], scope: str):
    st.subheader(title)

    for name in names:
        item = meta.get(name, {"name": name, "size_bytes": 0, "stamp": None, "mtime": None, "origin": "unknown"})
        size = hbytes(item.get("size_bytes") or 0)
        when = pretty_when(item)
        origin = origin_label(item)

        in_l_now = name in local_names
        in_r_now = name in remote_names

        will_del = (scope == "local" and name in pv["deletes_local"]) or (scope == "remote" and name in pv["deletes_remote"])
        will_add = (scope == "local" and name in pv["adds_local"]) or (scope == "remote" and name in pv["adds_remote"])

        # Row card
        row = st.container()
        with row:
            left, mid, right = st.columns([6, 2, 4])

            # left: title + meta (strike if delete)
            meta_line = f"{when} • {size} • {origin}"
            if will_del:
                badge("Will be deleted", "bad")
                st.markdown(f"**{name}**  \n~~{meta_line}~~")
            elif will_add:
                badge("Will be added here", "ok")
                st.markdown(f"**{name}**  \n{meta_line}")
            else:
                st.markdown(f"**{name}**  \n{meta_line}")

            # mid: location info
            with mid:
                st.caption("Locations")
                st.write(("💾" if in_l_now else "—") + "  Local")
                st.write(("☁️" if in_r_now else "—") + "  Cloud")

            # right: actions + pin + undo
            with right:
                opts = options_for(name)
                label_map = {k: v for k, v in opts}
                current = st.session_state["bm_actions"].get(name, {}).get("action", "none")

                picked = st.selectbox(
                    "Action",
                    options=[k for k, _ in opts],
                    format_func=lambda k: label_map.get(k, k),
                    index=[k for k, _ in opts].index(current) if current in [k for k, _ in opts] else 0,
                    key=f"act_{scope}_{name}",
                )
                set_action(name, picked)

                pin_val = (name in st.session_state["bm_pins"])
                new_pin = st.checkbox("📌 Pinned (skip auto-delete)", value=pin_val, key=f"pin_{scope}_{name}")
                if new_pin:
                    st.session_state["bm_pins"].add(name)
                else:
                    st.session_state["bm_pins"].discard(name)

                if picked != "none":
                    if st.button("↩️ Undo", key=f"undo_{scope}_{name}"):
                        undo_action(name)
                        st.rerun()

st.markdown("## Local backups")
local_preview_list = sorted(pv["final_local"], reverse=True)
render_section("Local Backups", local_preview_list, "local")

st.markdown("---")

st.markdown("## Cloud backups")
remote_preview_list = sorted(pv["final_remote"], reverse=True)
render_section("Cloud Backups", remote_preview_list, "remote")

st.markdown("---")

# Bottom controls
b1, b2 = st.columns([1, 1])
if b1.button("🧽 Clear decisions", use_container_width=True):
    st.session_state["bm_actions"] = {}
    st.session_state["bm_pins"] = set(inv.get("pinned", []))
    st.rerun()

apply = b2.button("✅ Apply decisions", use_container_width=True)

if apply:
    plan = {
        "actions": st.session_state["bm_actions"],
        "pinned": sorted(list(st.session_state["bm_pins"])),
    }
    with st.spinner("Applying changes…"):
        rc2, out2, err2 = run_root(["manage-apply"], input_text=json.dumps(plan))
    res = parse_json_best_effort(out2)

    if rc2 == 0 and res and not res.get("errors"):
        badge("Applied ✅", "ok")
    else:
        badge("Apply finished with warnings/errors", "warn")

    if res:
        st.subheader("Result")
        st.json(res)
    else:
        st.code(out2 + "\n" + err2, language="text")

    show_logs(err2)
