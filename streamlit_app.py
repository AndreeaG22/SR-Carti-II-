import os
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
)

load_dotenv()

# ================= CONFIG =================
client = RecombeeClient(
    os.environ["RECOMBEE_DB_ID"],
    os.environ["RECOMBEE_API_TOKEN"],
    region=Region[os.environ.get("RECOMBEE_REGION", "EU_WEST")],
)

SCENARIO_ID = "cli_series_boost"


def ensure_user(user_id: str):
    try:
        client.send(AddUser(user_id))
    except ResponseException as e:
        if e.status_code == 409:
            return
        # pentru demo, nu crăpăm UI-ul
        st.warning(f"AddUser warning: {e}")


def user_has_profile(user_id: str) -> bool:
    try:
        values = client.send(GetUserValues(user_id))
    except ResponseException as e:
        if e.status_code == 404:
            return False
        raise

    fav_genres = values.get("fav_genres") or []
    fav_authors = values.get("fav_authors") or []
    return bool(fav_genres or fav_authors)


def format_book(values: dict) -> str:
    title = values.get("title", "<no title>")
    author = values.get("author", "<no author>")
    avg_rating = values.get("avg_rating") or values.get("rating")
    genres = values.get("genres") or []

    rating_str = f"{avg_rating:.2f}" if isinstance(avg_rating, (int, float)) else "N/A"
    genres_str = ", ".join(genres) if isinstance(genres, list) else (str(genres) if genres else "")
    return f"{title} — {author} | rating: {rating_str} | {genres_str}"


def search_items(user_id: str, query: str):
    return client.send(SearchItems(user_id, query, 10, return_properties=True))


def add_detail_view(user_id: str, item_id: str):
    client.send(AddDetailView(user_id, item_id, cascade_create=True))


def rate_item(user_id: str, item_id: str, stars_1_to_5: float):
    r = (stars_1_to_5 - 3) / 2  # -1..1
    client.send(AddRating(user_id, item_id, r, cascade_create=True))


def recommend_for_user(user_id: str, count: int = 10):
    return client.send(
        RecommendItemsToUser(
            user_id,
            count,
            return_properties=True,
            scenario=SCENARIO_ID,
        )
    )


def recommend_similar(user_id: str, item_id: str, count: int = 10):
    return client.send(
        RecommendItemsToItem(
            item_id,
            user_id,
            count,
            return_properties=True,
        )
    )


def init_user_profile_from_3_books(user_id: str, item_ids: list[str]):
    fav_genres = set()
    fav_authors = set()

    for item_id in item_ids:
        values = client.send(GetItemValues(item_id))
        author = values.get("author")
        genres = values.get("genres", [])

        if author:
            fav_authors.add(author)
        if isinstance(genres, list):
            fav_genres.update(genres)

    if not fav_genres and not fav_authors:
        return False

    user_values = {"fav_genres": list(fav_genres), "fav_authors": list(fav_authors)}
    client.send(SetUserValues(user_id, user_values, cascade_create=True))
    return True


# ================= UI =================

st.set_page_config(page_title="Book Recommender (Recombee)", layout="wide")
st.title("📚 Book Recommender (Recombee) — Demo UI")

with st.sidebar:
    st.header("User")
    user_id = st.text_input("User ID", value=st.session_state.get("user_id", ""))
    st.session_state["user_id"] = user_id.strip()

    if st.button("✅ Ensure user exists"):
        if not st.session_state["user_id"]:
            st.error("Introduce un User ID.")
        else:
            ensure_user(st.session_state["user_id"])
            st.success("User ok (created or already exists).")

    st.divider()
    st.caption(f"Scenario folosit la recomandări: `{SCENARIO_ID}`")


if not st.session_state.get("user_id"):
    st.info("Introdu un User ID în sidebar ca să începi.")
    st.stop()


# --- Cold start section ---
st.subheader("🧊 Cold start (profil inițial din 3 cărți)")
try:
    has_profile = user_has_profile(user_id)
except Exception as e:
    st.error(f"Nu pot verifica profilul userului: {e}")
    st.stop()

if has_profile:
    st.success("User are deja profil (fav_genres / fav_authors).")
else:
    st.warning("User nou / fără profil. Alege 3 cărți și salvează profilul.")

colA, colB = st.columns([2, 1])

with colA:
    cold_query = st.text_input("Caută cărți pentru profil (titlu)", value=st.session_state.get("cold_query", ""))
    st.session_state["cold_query"] = cold_query
    cold_results = []
    if cold_query:
        try:
            # SearchItems cere userId valid; îl avem deja (ensure_user din sidebar)
            resp = search_items(user_id, cold_query)
            cold_results = resp.get("recomms", [])
        except Exception as e:
            st.error(f"SearchItems error: {e}")

    options = {}
    for rec in cold_results:
        options[f'{rec["id"]} — {format_book(rec.get("values", {}))}'] = rec["id"]

    picked = st.multiselect("Selectează până la 3 cărți", list(options.keys()), max_selections=3)

with colB:
    if st.button("💾 Save profile (fav_genres + fav_authors)", disabled=(len(picked) == 0)):
        try:
            item_ids = [options[k] for k in picked]
            ok = init_user_profile_from_3_books(user_id, item_ids)
            if ok:
                st.success("Profil salvat ✅")
            else:
                st.warning("Nu am extras genuri/autori din selecție.")
        except Exception as e:
            st.error(f"SetUserValues error: {e}")


st.divider()

# --- Search + DetailView ---
st.subheader("🔎 Caută o carte (și înregistrează vizită)")
q = st.text_input("Search title", value=st.session_state.get("search_query", ""))
st.session_state["search_query"] = q

if q:
    try:
        resp = search_items(user_id, q)
        results = resp.get("recomms", [])
    except Exception as e:
        st.error(f"SearchItems error: {e}")
        results = []

    if results:
        label_to_id = {f'{r["id"]} — {format_book(r.get("values", {}))}': r["id"] for r in results}
        selected_label = st.selectbox("Rezultate", list(label_to_id.keys()))
        selected_item_id = label_to_id[selected_label]

        if st.button("👁️ Open / View (AddDetailView)"):
            try:
                add_detail_view(user_id, selected_item_id)
                st.success(f"DetailView saved for item: {selected_item_id}")
                st.session_state["last_item_id"] = selected_item_id
            except Exception as e:
                st.error(f"AddDetailView error: {e}")
    else:
        st.info("N-am găsit rezultate.")

st.divider()

# --- Rate ---
st.subheader("⭐ Rate a book")
rate_item_id = st.text_input("Item ID (auto dacă ai dat View mai sus)", value=st.session_state.get("last_item_id", ""))
stars = st.slider("Rating (1-5)", 1.0, 5.0, 5.0, 0.5)

if st.button("✅ Save rating"):
    if not rate_item_id:
        st.error("Nu ai Item ID.")
    else:
        try:
            rate_item(user_id, rate_item_id, stars)
            st.success(f"Rating saved: {stars} for {rate_item_id}")
        except Exception as e:
            st.error(f"AddRating error: {e}")

st.divider()

# --- Recommendations ---
st.subheader("🎯 Recommendations for user")
count = st.number_input("How many?", min_value=1, max_value=50, value=10, step=1)

if st.button("✨ Recommend"):
    try:
        resp = recommend_for_user(user_id, int(count))
        recomms = resp.get("recomms", [])
        if not recomms:
            st.warning("Nu există destule informații încă (mai multe view-uri / rating-uri ajută).")
        else:
            for i, rec in enumerate(recomms, start=1):
                st.write(f"{i}. {format_book(rec.get('values', {}))}  \n`{rec.get('id')}`")
    except Exception as e:
        st.error(f"RecommendItemsToUser error: {e}")

st.divider()

# --- Similar items ---
st.subheader("🧩 Similar books (to an item)")
sim_item_id = st.text_input("Context Item ID", value=st.session_state.get("last_item_id", ""))

if st.button("🔁 Recommend similar"):
    if not sim_item_id:
        st.error("Pune un item id (poți folosi ultimul selectat).")
    else:
        try:
            resp = recommend_similar(user_id, sim_item_id, 10)
            recomms = resp.get("recomms", [])
            for i, rec in enumerate(recomms, start=1):
                st.write(f"{i}. {format_book(rec.get('values', {}))}  \n`{rec.get('id')}`")
        except Exception as e:
            st.error(f"RecommendItemsToItem error: {e}")
