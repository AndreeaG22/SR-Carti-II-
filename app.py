import sys
import os
from recombee_api_client.api_client import RecombeeClient, Region
from recombee_api_client.exceptions import ResponseException
from recombee_api_client.api_requests import AddUser
from recombee_api_client.api_requests import (
    SearchItems,
    RecommendItemsToItem,
    RecommendItemsToUser,
    AddRating,
    SetUserValues,
    GetItemValues,
    GetUserValues,
    AddDetailView
)

# ================= CONFIG =================

client = RecombeeClient(
        os.environ["RECOMBEE_DB_ID"],
        os.environ["RECOMBEE_API_TOKEN"],
        region=Region[os.environ.get("RECOMBEE_REGION", "EU_WEST")],
)

# ============= HELPERI GENERALI ==============
def ensure_user(user_id: str):
    """
    Se asigură că userul există în Recombee.
    Dacă există deja, ignorăm eroarea de tip 'already exists'.
    """
    try:
        client.send(AddUser(user_id))
    except ResponseException as e:
        # 409 = already exists, alte coduri pot fi ignorable în contextul nostru
        if e.status_code in (409, ):
            return
        return

def user_has_profile(user_id: str) -> bool:
    """
    Verifică dacă userul are deja un profil inițial (fav_genres/fav_authors).
    Dacă userul nu există în Recombee -> return False (cold start).
    """
    try:
        values = client.send(GetUserValues(user_id))
    except ResponseException as e:
        # 404 = userul nu există deloc
        if e.status_code == 404:
            return False
        # orice altceva propagăm mai departe
        raise

    fav_genres = values.get("fav_genres") or []
    fav_authors = values.get("fav_authors") or []
    return bool(fav_genres or fav_authors)


def init_user_profile(user_id: str):
    """
    Cold start pentru utilizator nou:
    îl rugăm să aleagă cărți care i-au plăcut,
    apoi extragem genurile și autorii din acele item-uri.
    """
    print("\nHai să-ți configurăm rapid profilul inițial.")
    print("Spune-mi până la 3 cărți care ți-au plăcut.\n")

    fav_genres = set()
    fav_authors = set()

    for idx in range(1, 4):
        prompt = f"Cartea #{idx} (caută după titlu sau ENTER pentru a sări): "
        item_id = search_and_choose_book(user_id, prompt)
        if item_id is None:
            # userul a dat direct ENTER sau 0
            break

        try:
            values = client.send(GetItemValues(item_id))
        except Exception as e:
            print(f"Nu am putut citi detaliile pentru {item_id}: {e}")
            continue

        author = values.get("author")
        genres = values.get("genres", [])

        if author:
            fav_authors.add(author)

        if isinstance(genres, list):
            fav_genres.update(genres)

        print(f"Am adăugat în profil cartea: {format_book(values)}\n")

    if not fav_genres and not fav_authors:
        print("Nu ai ales nicio carte, sar peste profilul inițial.\n")
        return

    user_values = {
        "fav_genres": list(fav_genres),
        "fav_authors": list(fav_authors),
    }

    try:
        client.send(SetUserValues(user_id, user_values, cascade_create=True))
        print("Profil inițial salvat (genuri + autori preferați).\n")
    except Exception as e:
        print(f"⚠ Nu am reușit să salvez preferințele de start: {e}\n")


def format_book(values: dict) -> str:
    """Formatare pentru afișare în terminal."""
    title = values.get("title", "<no title>")
    author = values.get("author", "<no author>")
    avg_rating = values.get("avg_rating") or values.get("rating")
    genres = values.get("genres") or []

    if isinstance(genres, list):
        genres_str = ", ".join(genres)
    else:
        genres_str = str(genres) if genres else ""

    if isinstance(avg_rating, (int, float)):
        rating_str = f"{avg_rating:.2f}"
    else:
        rating_str = "N/A"

    return f"{title} — {author} | rating: {rating_str} | {genres_str}"


def search_and_choose_book(user_id: str, context_text: str, personalized: bool = True) -> str | None:
    """
    Folosește SearchItems în Recombee:
      - userul scrie o bucățică de titlu
      - afișăm top 5 rezultate
      - alege un număr (1-5)
    Returnează itemId sau None dacă renunță.
    """
    while True:
        query = input(f"{context_text} (ENTER pentru anulare): ").strip()
        if not query:
            return None

        try:
            resp = client.send(
                SearchItems(
                    user_id,
                    query,
                    5,
                    return_properties=True,
                )
            )
        except Exception as e:
            print(f"Eroare la SearchItems: {e}")
            return None

        recomms = resp.get("recomms", [])
        if not recomms:
            print("Nu am găsit cărți pentru acest titlu. Încearcă altceva.\n")
            continue

        print("\nRezultate:")
        for idx, rec in enumerate(recomms, start=1):
            print(f"{idx}) {format_book(rec.get('values', {}))}")

        print("0) Înapoi")
        choice = input("Alege numărul cărții: ").strip()

        if choice == "0":
            return None

        try:
            idx = int(choice)
        except ValueError:
            print("Te rog alege un număr valid.\n")
            continue

        if 1 <= idx <= len(recomms):
            item_id = recomms[idx - 1]["id"]

            # 🔹 aici marcăm vizita în Recombee
            try:
                client.send(
                    AddDetailView(
                        user_id,
                        item_id,
                        cascade_create=True
                    )
                )
            except Exception as e:
                print(f"Avertisment: nu am putut înregistra vizita: {e}")

            return item_id

        print("Index invalid. Încearcă din nou.\n")


def print_recommendations_list(recomms: list):
    if not recomms:
        print("Nu am primit niciun rezultat.\n")
        return
    for i, rec in enumerate(recomms, start=1):
        values = rec.get("values", {})
        print(f"{i}. {format_book(values)}")
    print("")


# ============= ACȚIUNI DE MENIU ==============

def action_search_book(user_id: str):
    item_id = search_and_choose_book(user_id, "Introdu titlul cărții pe care o cauți")
    if item_id is None:
        return

    print(f"\nAi selectat itemId = {item_id}\n")


def action_rate_book(user_id: str):
    item_id = search_and_choose_book(user_id, "Introdu titlul cărții pe care vrei s-o notezi")
    if item_id is None:
        return

    while True:
        rating_str = input("Introdu rating (1-5): ").strip()
        try:
            rating = float(rating_str)
        except ValueError:
            print("Rating invalid. Introdu un număr între 1 și 5.")
            continue

        if not (1 <= rating <= 5):
            print("Ratingul trebuie să fie între 1 și 5.")
            continue
        break
    r = (rating - 3) / 2  # convertim la -1..1
    client.send(AddRating(user_id, item_id, r, cascade_create=True))
    print(f"\nRating salvat: userul {user_id} a dat {rating} la {item_id}\n")



def action_recommend_for_user(user_id: str):
    try:
        resp = client.send(
            RecommendItemsToUser(
                user_id,
                10,
                return_properties=True,
                scenario="cli_series_boost"
            )
        )
    except Exception as e:
        print(f"Eroare la RecommendItemsToUser: {e}")
        return


    recomms = resp.get("recomms", [])
    print(f"\nRecomandări pentru {user_id}:")
    if not recomms:
        print("Nu există încă destule informații. Dă întâi câteva ratinguri.\n")
        return

    print_recommendations_list(recomms)


def action_similar_books(user_id: str):
    item_id = search_and_choose_book(user_id, "Introdu titlul unei cărți pentru a vedea alte cărți asemănătoare")
    if item_id is None:
        return

    try:
        resp = client.send(
            RecommendItemsToItem(
                item_id,
                user_id,
                10,
                return_properties=True,
            )
        )
    except Exception as e:
        print(f"Eroare la RecommendItemsToItem: {e}")
        return

    recomms = resp.get("recomms", [])
    print("\nCărți similare cu ce ai ales:")
    if not recomms:
        print("Nu am găsit recomandări similare.\n")
        return

    print_recommendations_list(recomms)


# ================ MAIN LOOP =================

def main():
    print("=== Book Recommender CLI (Recombee) ===")
    user_id = input("Introdu ID-ul tău de user: ").strip()
    if not user_id:
        print("Trebuie un ID de user. Ieșire.")
        sys.exit(0)

    print(f"\nBun venit, {user_id}!\n")

    ensure_user(user_id)

    # Cold start doar dacă userul NU are deja profil
    if not user_has_profile(user_id):
        init_user_profile(user_id)
    else:
        print("Ai deja un profil salvat (genuri + autori), sar peste configurarea inițială.\n")


    while True:
        print("=== Meniu principal ===")
        print(f"User curent: {user_id}\n")
        print("1) Caută o carte după titlu")
        print("2) Dă rating unei cărți")
        print("3) Recomandări pentru mine")
        print("4) Cărți similare cu o carte")
        print("0) Ieșire")

        choice = input("Alege opțiunea: ").strip()
        print("")

        if choice == "1":
            action_search_book(user_id)
        elif choice == "2":
            action_rate_book(user_id)
        elif choice == "3":
            action_recommend_for_user(user_id)
        elif choice == "4":
            action_similar_books(user_id)
        elif choice == "0":
            print("La revedere!")
            break
        else:
            print("Opțiune invalidă. Încearcă din nou.\n")


if __name__ == "__main__":
    main()
