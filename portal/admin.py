"""Admin: who has signed up, approvals, roles, and the activity log. Broker keys are never shown here."""
from __future__ import annotations

import pandas as pd
import streamlit as st

from scalpbot.accounts import AccountError

from portal import ui
from portal.auth import accounts, require_admin

acc = accounts()
admin = require_admin()

ui.eyebrow("Admin")
st.title("Users")

msg = st.session_state.pop("admin_msg", None)
if msg:
    (st.success if msg[0] == "success" else st.error)(msg[1])


def act(fn, *args, done: str) -> None:
    try:
        fn(admin, *args)
        st.session_state["admin_msg"] = ("success", done)
    except AccountError as e:
        st.session_state["admin_msg"] = ("error", str(e))
    st.rerun()


people = acc.list_users()
by_status = {s: [u for u in people if u.status == s] for s in ("pending", "active", "disabled")}
c = st.columns(4)
c[0].metric("Signed up", len(people))
c[1].metric("Pending approval", len(by_status["pending"]))
c[2].metric("Active", len(by_status["active"]))
c[3].metric("Admins", sum(1 for u in people if u.is_admin and u.status == "active"))

# --------------------------------------------------------------------------- pending approvals
if by_status["pending"]:
    st.subheader("Waiting for approval")
    for u in by_status["pending"]:
        row = st.container(border=True).columns([4, 3, 1, 1], vertical_alignment="center")
        row[0].markdown(f"<b>{ui.esc(u.name or '(no name)')}</b><br><small style='opacity:.7'>{ui.esc(u.email)}</small>",
                        unsafe_allow_html=True)
        row[1].markdown(ui.pill("Pending", "warn") + f"<small style='opacity:.7;margin-left:8px'>since "
                        f"{u.created_at:%d %b %Y %H:%M} UTC</small>", unsafe_allow_html=True)
        if row[2].button("Approve", key=f"ap_{u.id}", type="primary"):
            act(acc.approve, u.id, done=f"Approved {u.email}.")
        if row[3].button("Reject", key=f"rj_{u.id}"):
            act(acc.delete_user, u.id, done=f"Rejected and removed {u.email}.")

# --------------------------------------------------------------------------- everyone
st.subheader("Everyone")
table = pd.DataFrame([{
    "Name": u.name, "Email": u.email, "Role": u.role, "Status": u.status,
    "Signed up (UTC)": u.created_at.strftime("%Y-%m-%d %H:%M"),
    "Last sign-in (UTC)": u.last_login_at.strftime("%Y-%m-%d %H:%M") if u.last_login_at else "never",
} for u in people])
st.dataframe(table, hide_index=True)

st.subheader("Manage a user")
others = {f"{u.email} ({u.role}, {u.status})": u for u in people}
pick = st.selectbox("User", list(others), key="adm_pick")
if pick:
    u = others[pick]
    if u.id == admin.id:
        st.caption("This is you. Another admin has to change your role or status.")
    else:
        b = st.columns(4)
        if u.status == "active":
            if b[0].button("Disable", key="adm_disable"):
                act(acc.disable, u.id, done=f"Disabled {u.email}. They are signed out within a minute.")
        elif b[0].button("Enable" if u.status == "disabled" else "Approve", key="adm_enable", type="primary"):
            act(acc.enable, u.id, done=f"{u.email} can sign in now.")
        if u.role == "user":
            if b[1].button("Make admin", key="adm_promote"):
                act(acc.set_role, u.id, "admin", done=f"{u.email} is now an admin.")
        elif b[1].button("Make regular user", key="adm_demote"):
            act(acc.set_role, u.id, "user", done=f"{u.email} is now a regular user.")
        with b[3].popover("Delete"):
            st.write(f"Delete **{u.email}** and their saved keys? This can't be undone.")
            if st.button("Yes, delete", key="adm_delete", type="primary"):
                act(acc.delete_user, u.id, done=f"Deleted {u.email}.")

# --------------------------------------------------------------------------- activity
st.subheader("Activity log")
log = pd.DataFrame(acc.audit_log(1000))
if log.empty:
    st.caption("Nothing yet.")
else:
    actions = sorted(log["action"].unique())
    show = st.multiselect("Actions", actions, default=actions, key="adm_actions")
    who = st.text_input("Filter by email", key="adm_who").strip().lower()
    view = log[log["action"].isin(show)]
    if who:
        view = view[view["who"].str.contains(who, regex=False) | view["target"].str.contains(who, regex=False)]
    view = view.assign(time=view["time"].map(lambda t: t.strftime("%Y-%m-%d %H:%M:%S")))
    st.dataframe(view.rename(columns={"time": "Time (UTC)", "who": "By", "action": "Action", "target": "Target",
                                      "detail": "Detail"}), hide_index=True)
    st.download_button("Download log as CSV", view.to_csv(index=False), "scalp5_activity.csv", "text/csv")
