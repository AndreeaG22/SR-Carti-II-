import os
import time
from pathlib import Path
from collections import Counter

import streamlit as st
from dotenv import load_dotenv

from recombee_api_client.api_client import RecombeeClient, Region
from recombee_api_client.exceptions import ResponseException
from recombee_api_client.api_requests import (
    AddUser,
    SearchItems,
    RecommendItemsToUser,
    RecommendItemsToItem,
    AddRating,
    SetUserValues,
    GetItemValues,
    GetUserValues,
    AddDetailView,
    SetItemValues
)

# ---------- env loading ----------
ENV_PATH = Path(__file__).resolve().parent / ".env"
load_dotenv(dotenv_path=ENV_PATH, override=True)


def env_required(name: str) -> str:
    v = os.environ.get(name, "").strip()
    if not v:
        st.error(f"Lipsește env var: {name}. Pune-l în .env (lângă streamlit_app.py).")
        st.stop()
    return v


RECOMBEE_DB_ID = env_required("RECOMBEE_DB_ID")
RECOMBEE_API_TOKEN = env_required("RECOMBEE_API_TOKEN")
RECOMBEE_REGION = os.environ.get("RECOMBEE_REGION", "EU_WEST").strip() or "EU_WEST"
SCENARIO_ID = os.environ.get("SCENARIO_ID", "cli_series_boost").strip() or "cli_series_boost"

# ---------- Recombee client ----------
client = RecombeeClient(
    RECOMBEE_DB_ID,
    RECOMBEE_API_TOKEN,
    region=Region[RECOMBEE_REGION],
)

for attr in ("timeout", "request_timeout", "timeout_ms"):
    if hasattr(client, attr):
        try:
            setattr(client, attr, 10)  # seconds
        except Exception:
            pass


def send_with_retry(req, tries: int = 3, base_sleep: float = 0.35):
    """
    Retry simplu pe timeout-uri/erori transient.
    Recombee python client aruncă uneori ApiTimeout cu mesaj de genul:
      "ApiTimeout: client did not get response within 3000 ms"
    """
    last = None
    for i in range(tries):
        try:
            return client.send(req)
        except Exception as e:
            last = e
            msg = str(e)
            # retry doar pe timeout/transient
            if "ApiTimeout" in msg or "did not get response" in msg or "timed out" in msg:
                time.sleep(base_sleep * (2**i))
                continue
            raise
    raise last


# ---------- helpers ----------
def ensure_user(user_id: str):
    try:
        send_with_retry(AddUser(user_id))
    except ResponseException as e:
        if e.status_code == 409:
            return
        st.warning(f"AddUser warning: {e}")


def normalize_list(x):
    """
    Întoarce mereu o listă de string-uri.
    - suportă: None, string, list[str], list[list[str]] (nested)
    """
    if not x:
        return []

    out = []

    def add_one(v):
        s = str(v).strip()
        if s:
            out.append(s)

    if isinstance(x, list):
        for v in x:
            if isinstance(v, list):
                for vv in v:
                    add_one(vv)
            else:
                add_one(v)
        return out

    # fallback: orice alt tip -> string
    add_one(x)
    return out



def user_values(user_id: str) -> dict:
    return send_with_retry(GetUserValues(user_id))


def user_has_profile(user_id: str) -> bool:
    try:
        values = user_values(user_id)
    except ResponseException as e:
        if e.status_code == 404:
            return False
        raise
    fav_genres = normalize_list(values.get("fav_genres"))
    fav_authors = normalize_list(values.get("fav_authors"))
    return bool(fav_genres or fav_authors)


def format_book(values: dict) -> str:
    title = values.get("title", "<no title>")
    author = values.get("author", "<no author>")
    avg_rating = values.get("avg_rating", values.get("rating"))
    genres = values.get("genres") or []

    rating_str = f"{avg_rating:.2f}" if isinstance(avg_rating, (int, float)) else "N/A"
    if isinstance(genres, list):
        genres_str = ", ".join(genres[:6]) + (" ..." if len(genres) > 6 else "")
    else:
        genres_str = str(genres) if genres else ""

    return f"{title} — {author} | rating: {rating_str} | {genres_str}"


def search_items(user_id: str, query: str, count: int = 10):
    return send_with_retry(SearchItems(
        user_id,
        query,
        count,
        return_properties=True,
        cascade_create=True,
    ))



def add_detail_view(user_id: str, item_id: str):
    send_with_retry(AddDetailView(user_id, item_id, cascade_create=True))


def rate_item(user_id: str, item_id: str, stars_1_to_5: float):
    r = (stars_1_to_5 - 3) / 2
    send_with_retry(AddRating(user_id, item_id, r, cascade_create=True))


def recommend_for_user(user_id: str, count: int = 10):
    return send_with_retry(
        RecommendItemsToUser(
            user_id,
            count,
            return_properties=True,
            scenario=SCENARIO_ID,
        )
    )


def recommend_similar(user_id: str, item_id: str, count: int = 10):
    return send_with_retry(
        RecommendItemsToItem(
            item_id,
            user_id,
            count,
            return_properties=True,
        )
    )


def init_user_profile_from_3_books(user_id: str, item_ids: list[str]) -> bool:
    fav_genres = []
    fav_authors = []

    for item_id in item_ids:
        values = send_with_retry(GetItemValues(item_id))
        author = values.get("author")
        genres = values.get("genres") or []

        if author:
            fav_authors.append(str(author).strip())

        if isinstance(genres, list):
            fav_genres.extend([str(g).strip() for g in genres if str(g).strip()])

    fav_genres = [g for g in fav_genres if g]
    fav_authors = [a for a in fav_authors if a]

    fav_genres = normalize_list(fav_genres)
    fav_authors = normalize_list(fav_authors)

    def unique_ci(seq):
        seen = set()
        res = []
        for s in seq:
            key = s.lower()
            if key not in seen:
                seen.add(key)
                res.append(s)
        return res

    fav_genres = unique_ci(fav_genres)
    fav_authors = unique_ci(fav_authors)

    if not fav_genres and not fav_authors:
        return False

    send_with_retry(
        SetUserValues(
            user_id,
            {
                "fav_genres": fav_genres,
                "fav_authors": fav_authors,
            },
        )
    )
    return True

def display_user_profile_summary(user_id: str, top_genres: int = 8):
    vals = user_values(user_id)

    fav_authors = normalize_list(vals.get("fav_authors"))
    fav_genres = normalize_list(vals.get("fav_genres"))

    authors_unique = sorted({a.strip(): a for a in fav_authors}.values(), key=lambda s: s.lower())

    genres_counts = Counter([g for g in fav_genres if g])
    top = genres_counts.most_common(top_genres)

    st.subheader("👤 Profilul tău (salvat în Recombee)")
    c1, c2 = st.columns(2)

    with c1:
        st.caption("Autori preferați (unici)")
        st.write(", ".join(authors_unique) if authors_unique else "—")

    with c2:
        st.caption(f"Genuri esențiale (Top {top_genres})")
        st.write(", ".join([f"{g} (x{cnt})" for g, cnt in top]) if top else "—")

    with st.expander("Vezi toate genurile (raw)"):
        st.write(fav_genres)



# ---------- UI ----------
st.set_page_config(page_title="SR Cărți — Recombee Demo", layout="wide")
st.title("📚 Book Recommender - SR Cărți (II)")

# session state init
st.session_state.setdefault("user_id", "")
st.session_state.setdefault("profile_picks", [])
st.session_state.setdefault("cold_results", [])
st.session_state.setdefault("cold_query", "")
st.session_state.setdefault("search_query", "")
st.session_state.setdefault("search_results", [])
st.session_state.setdefault("last_item_id", "")

with st.sidebar:
    st.header("⚙️ Setări")
    uid = st.text_input("User ID", value=st.session_state["user_id"]).strip()
    st.session_state["user_id"] = uid

    st.caption(f"Scenario: `{SCENARIO_ID}`")

    st.caption(f"Region: `{RECOMBEE_REGION}`")

    if st.button("👤 Creează/Asigură user în Recombee", disabled=(not uid)):
        ensure_user(uid)
        st.success("OK (user există)")

if not st.session_state["user_id"]:
    st.info("Introdu un User ID în sidebar ca să începi.")
    st.stop()

user_id = st.session_state["user_id"]

ensure_user(user_id)

try:
    needs_profile = not user_has_profile(user_id)
except Exception:
    needs_profile = True

tab_cold, tab_search, tab_rate, tab_recs, tab_sim = st.tabs(
    ["❄️ Cold start", "🔎 Caută + Vizită", "⭐ Rating", "🎯 Recomandări", "🧩 Similare"]
)

# ---------- Cold start ----------
with tab_cold:
    st.subheader("❄️ Cold start (profil inițial din 3 cărți)")

    has_profile = False
    try:
        has_profile = user_has_profile(user_id)
    except Exception as e:
        st.warning(f"Nu pot citi profilul: {e}")

    if has_profile:
        st.success("User are deja profil (fav_genres / fav_authors).")
        try:
            display_user_profile_summary(user_id, top_genres=8)
        except Exception as e:
            st.warning(f"Nu pot afișa sumar profil: {e}")

    st.divider()

    colA, colB = st.columns([2, 1])

    with colA:
        st.markdown("### 🔎 Caută o carte pentru profil (poți căuta de mai multe ori)")
        cold_q = st.text_input(
            "Titlu (pentru profil)",
            value=st.session_state["cold_query"],
            key="cold_query_input",
        ).strip()
        st.session_state["cold_query"] = cold_q

        if st.button("🔍 Caută pentru profil", key="cold_search_btn"):
            if not cold_q:
                st.warning("Scrie un titlu.")
                st.session_state["cold_results"] = []
            else:
                try:
                    resp = search_items(user_id, cold_q, count=10)
                    st.session_state["cold_results"] = resp.get("recomms", [])
                except Exception as e:
                    st.error(f"SearchItems error: {e}")
                    st.session_state["cold_results"] = []

        cold_results = st.session_state["cold_results"]

        if cold_results:
            label_to_id = {
                f'{r["id"]} — {format_book(r.get("values", {}))}': r["id"]
                for r in cold_results
            }
            pick_label = st.selectbox(
                "Rezultate (alege una și apoi apasă Adaugă)",
                list(label_to_id.keys()),
                key="cold_pick_select",
            )
            pick_id = label_to_id[pick_label]

            already = pick_id in st.session_state["profile_picks"]
            full = len(st.session_state["profile_picks"]) >= 3
            if st.button("➕ Adaugă la profil (max 3)", disabled=(already or full), key="cold_add_btn"):
                st.session_state["profile_picks"].append(pick_id)
        else:
            st.info("Caută ceva ca să apară rezultate.")

        st.markdown("### ✅ Selectate pentru profil")
        if st.session_state["profile_picks"]:
            for pid in st.session_state["profile_picks"]:
                st.write(f"- `{pid}`")
            if st.button("🧹 Reset selecție", key="cold_reset_btn"):
                st.session_state["profile_picks"] = []
        else:
            st.caption("Nimic selectat încă.")

    with colB:
        st.markdown("### 💾 Salvează profilul")
        st.caption("Salvează fav_authors + fav_genres extrase din cele 1-3 cărți selectate.")

        if st.button("💾 Salvează profilul în Recombee", disabled=(len(st.session_state["profile_picks"]) == 0), key="cold_save_btn"):
            try:
                ok = init_user_profile_from_3_books(user_id, st.session_state["profile_picks"])
                if ok:
                    st.success("Profil salvat ✔")
                    st.session_state["profile_picks"] = []
                    st.session_state["cold_results"] = []
                else:
                    st.warning("Nu am extras genuri/autori din selecție.")
            except Exception as e:
                st.error(f"SetUserValues error: {e}")

# ---------- Search + DetailView ----------
with tab_search:
    st.subheader("🔎 Caută o carte (și înregistrează vizită / DetailView)")

    q = st.text_input("Caută titlu", value=st.session_state["search_query"], key="search_q").strip()
    st.session_state["search_query"] = q

    if st.button("🔍 Caută", key="search_btn"):
        if not q:
            st.warning("Scrie un titlu.")
            st.session_state["search_results"] = []
        else:
            try:
                resp = search_items(user_id, q, count=10)
                st.session_state["search_results"] = resp.get("recomms", [])
            except Exception as e:
                st.error(f"Eroare la cautare: {e}")
                st.session_state["search_results"] = []

    results = st.session_state["search_results"]

    if results:
        label_to_id = {
            f'{r["id"]} — {format_book(r.get("values", {}))}': r["id"]
            for r in results
        }
        selected_label = st.selectbox("Rezultate", list(label_to_id.keys()), key="search_select")
        selected_item_id = label_to_id[selected_label]

        st.markdown("### ✅ Cartea selectată (Item ID)")
        st.code(selected_item_id, language=None)

        if st.button("👁️ Deschide / Vizualizează (AddDetailView)", key="view_btn"):
            try:
                add_detail_view(user_id, selected_item_id)
                st.success(f"DetailView saved ✅ ({selected_item_id})")
                st.session_state["last_item_id"] = selected_item_id
            except Exception as e:
                st.error(f"AddDetailView error: {e}")
    else:
        st.info("N-ai rezultate încă (apasă Caută).")

# ---------- Rate ----------
with tab_rate:
    st.subheader("⭐ Evaluează o carte (Rating)")

    rate_item_id = st.text_input(
        "Item ID (auto dacă ai dat View)",
        value=st.session_state.get("last_item_id", ""),
        key="rate_item_id",
    ).strip()

    stars = st.slider("Rating (1-5)", 1.0, 5.0, 5.0, 0.5, key="rate_slider")

    if st.button("✅ Salvează rating", key="rate_btn"):
        if not rate_item_id:
            st.error("Nu ai Item ID.")
        else:
            try:
                rate_item(user_id, rate_item_id, stars)
                st.success(f"Rating salvat ✅ {stars} pentru `{rate_item_id}`")
            except Exception as e:
                st.error(f"Eroare la salvarea rating-ului: {e}")

# ---------- Recommendations ----------
with tab_recs:
    st.subheader("🎯 Recomandări pentru utilizator")

    count = st.number_input("Câte recomandări?", min_value=1, max_value=50, value=10, step=1, key="rec_count")

    if st.button("✨ Recomandă", key="rec_btn"):
        if needs_profile:
            st.error("Nu ai profil încă (fav_genres / fav_authors gol). "
                 "Mergi la tab-ul ❄️ Cold start și alege 3 cărți, apoi salvează profilul.")
            st.stop()
        try:
            resp = recommend_for_user(user_id, int(count))
            recomms = resp.get("recomms", [])
            if not recomms:
                st.warning("Nu există destule informații încă. (mai multe view-uri / rating-uri ajută)")
            else:
                for i, rec in enumerate(recomms, start=1):
                    st.write(f"{i}. {format_book(rec.get('values', {}))}  \n`{rec.get('id')}`")
        except Exception as e:
            st.error(f"Eroare la recomandări: {e}")

# ---------- Similar items ----------
with tab_sim:
    st.subheader("🧩 Cărți similare (Items-to-Item)")

    sim_item_id = st.text_input(
        "Context Item ID",
        value=st.session_state.get("last_item_id", ""),
        key="sim_item_id",
    ).strip()

    if st.button("🔁 Recomandă similare", key="sim_btn"):
        if not sim_item_id:
            st.error("Pune un item id (poți folosi ultimul selectat).")
        else:
            try:
                resp = recommend_similar(user_id, sim_item_id, 10)
                recomms = resp.get("recomms", [])
                if not recomms:
                    st.warning("N-am primit rezultate.")
                else:
                    for i, rec in enumerate(recomms, start=1):
                        st.write(f"{i}. {format_book(rec.get('values', {}))}  \n`{rec.get('id')}`")
            except Exception as e:
                st.error(f"Eroare la recomandări similare: {e}")
