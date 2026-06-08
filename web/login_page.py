"""
login_page.py — 登入 / 註冊頁面 UI

由 web/app.py 在登入 Gate 中呼叫。
成功登入後，將使用者名稱寫入 st.session_state["username"]，
再呼叫 st.rerun() 讓主程式繼續執行。
"""

import sqlite3
import sys
from pathlib import Path

import streamlit as st

sys.path.insert(0, str(Path(__file__).parent.parent))

from models.auth import ensure_users_table, login, register

DB_PATH = Path(__file__).parent.parent / "data" / "news.db"

# ─────────────────────────────────────────────────────────────
# 登入頁 CSS（只在登入頁注入，不影響 Dashboard 樣式）
# ─────────────────────────────────────────────────────────────

_LOGIN_CSS = """
<style>
/* ── 全頁背景 ── */
[data-testid="stAppViewContainer"] { background: #f4f6fb !important; }
[data-testid="stMain"]             { background: #f4f6fb !important; }

/* ── 品牌區 ── */
.lp-brand {
    text-align: center;
    padding: 2.5rem 0 1.6rem;
}
.lp-brand-icon  { font-size: 2.8rem; line-height: 1; }
.lp-brand-title {
    font-size: 1.45rem; font-weight: 800;
    color: #0d0f14; letter-spacing: -.03em;
    margin-top: .5rem;
}
.lp-brand-sub {
    font-size: .78rem; color: #8a8f9e;
    margin-top: .25rem; letter-spacing: .01em;
}

/* ── 卡片框 ── */
.lp-card {
    background: #ffffff;
    border: 1px solid #e2e4e9;
    border-radius: 12px;
    padding: 2rem 2.2rem 1.6rem;
    box-shadow: 0 4px 20px rgba(0,0,0,.07);
    margin-bottom: 1rem;
}

/* ── 頁尾提示 ── */
.lp-footer {
    text-align: center;
    font-size: .72rem;
    color: #b0b5c3;
    margin-top: .8rem;
    padding-bottom: 2rem;
}
.lp-footer code {
    background: #f3f4f6;
    border-radius: 3px;
    padding: 1px 5px;
    font-size: .72rem;
    color: #374151;
}

/* 緊縮 Streamlit 表單間距 */
.block-container { padding-top: 0 !important; }
div[data-testid="stVerticalBlock"] > div { gap: 0 !important; }
</style>
"""


# ─────────────────────────────────────────────────────────────
# DB 工具
# ─────────────────────────────────────────────────────────────

def _get_conn() -> sqlite3.Connection:
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    ensure_users_table(conn)
    return conn


# ─────────────────────────────────────────────────────────────
# 頁面渲染
# ─────────────────────────────────────────────────────────────

def render_login_page() -> None:
    """
    渲染登入/註冊頁面。
    登入成功後設定 session_state["username"] 並呼叫 st.rerun()，
    讓 app.py 的登入 gate 判斷通過、繼續渲染 Dashboard。
    """
    st.markdown(_LOGIN_CSS, unsafe_allow_html=True)

    # 三欄置中，中欄寬度約 380px
    col_l, col_m, col_r = st.columns([1.2, 2, 1.2])

    with col_m:
        # ── 品牌 ──────────────────────────────────────────
        st.markdown("""
<div class="lp-brand">
  <div class="lp-brand-icon">📈</div>
  <div class="lp-brand-title">台股新聞 AI 分析平台</div>
  <div class="lp-brand-sub">Taiwan Stock News AI Sentiment Tracker</div>
</div>""", unsafe_allow_html=True)

        # ── 卡片：登入 / 註冊 Tab ──────────────────────────
        st.markdown('<div class="lp-card">', unsafe_allow_html=True)

        tab_login, tab_reg = st.tabs(["🔑  登入", "✨  建立帳號"])

        # ── 登入 Tab ──────────────────────────────────────
        with tab_login:
            st.markdown("")
            with st.form("form_login", clear_on_submit=False):
                username = st.text_input(
                    "使用者名稱",
                    placeholder="輸入帳號",
                    label_visibility="visible",
                )
                password = st.text_input(
                    "密碼",
                    type="password",
                    placeholder="輸入密碼",
                )
                submitted = st.form_submit_button(
                    "登入",
                    use_container_width=True,
                    type="primary",
                )

            if submitted:
                if not username.strip() or not password:
                    st.error("請填寫帳號和密碼")
                else:
                    try:
                        conn = _get_conn()
                        ok, msg = login(conn, username, password)
                        conn.close()
                    except Exception as e:
                        st.error(f"資料庫錯誤：{e}")
                        ok = False

                    if ok:
                        st.session_state["username"] = username.strip().lower()
                        st.rerun()
                    else:
                        st.error(msg)

        # ── 註冊 Tab ──────────────────────────────────────
        with tab_reg:
            st.markdown("")
            with st.form("form_register", clear_on_submit=True):
                new_user = st.text_input(
                    "使用者名稱",
                    placeholder="設定帳號（32 字元以內）",
                    key="reg_username",
                )
                new_pw = st.text_input(
                    "密碼",
                    type="password",
                    placeholder="至少 4 個字元",
                    key="reg_pw",
                )
                new_pw2 = st.text_input(
                    "確認密碼",
                    type="password",
                    placeholder="再次輸入密碼",
                    key="reg_pw2",
                )
                submitted_r = st.form_submit_button(
                    "建立帳號",
                    use_container_width=True,
                )

            if submitted_r:
                if not new_user.strip() or not new_pw:
                    st.error("請填寫所有欄位")
                elif new_pw != new_pw2:
                    st.error("兩次密碼輸入不一致")
                else:
                    try:
                        conn = _get_conn()
                        ok, msg = register(conn, new_user, new_pw)
                        conn.close()
                    except Exception as e:
                        st.error(f"資料庫錯誤：{e}")
                        ok = False

                    if ok:
                        st.success(f"{msg}　→　請切換至「登入」頁面")
                    else:
                        st.error(msg)

        st.markdown("</div>", unsafe_allow_html=True)

        # ── 頁尾提示 ──────────────────────────────────────
        st.markdown(
            '<div class="lp-footer">'
            "Demo 帳號：<code>demo</code>　密碼：<code>demo1234</code>"
            "</div>",
            unsafe_allow_html=True,
        )
