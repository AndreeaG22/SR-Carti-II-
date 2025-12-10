import os
import pandas as pd
from dotenv import load_dotenv
from recombee_api_client.api_client import RecombeeClient, Region
from recombee_api_client.api_requests import AddItem, SetItemValues, Batch


load_dotenv()

client = RecombeeClient(
        os.environ["RECOMBEE_DB_ID"],
        os.environ["RECOMBEE_API_TOKEN"],
        region=Region[os.environ.get("RECOMBEE_REGION", "EU_WEST")],
)


def safe_float(x):
    try:
        return float(x)
    except (TypeError, ValueError):
        return None


def safe_int(x):
    try:
        if pd.isna(x):
            return None
        return int(x)
    except (TypeError, ValueError):
        return None


def main():
    df = pd.read_csv("books_1.Best_Books_Ever.csv")

    # derivam anul publicarii din firstPublishDate / publishDate
    for col in ["firstPublishDate", "publishDate"]:
        if col in df.columns:
            df[col] = pd.to_datetime(df[col], errors="coerce")

    df["publish_year"] = df["firstPublishDate"].dt.year.fillna(
        df["publishDate"].dt.year
    )

    # lungimea descrierii
    df["description_len"] = df["description"].fillna("").astype(str).str.len()

    # popularitate simpla = numRatings
    df["popularity"] = df["numRatings"].fillna(0)

    BATCH_SIZE = 500
    batch_requests = []

    for _, row in df.iterrows():
        item_id = str(row["bookId"])

        # genuri ca set (lista) – daca sunt separate prin '|'
        if pd.notna(row.get("genres")):
            genres = str(row["genres"]).split("|")
        else:
            genres = []

        # premii – flag simplu
        has_awards = (
            pd.notna(row.get("awards"))
            and str(row["awards"]).strip() != ""
        )

        props = {
            "title": row["title"],
            "author": row["author"],
            "series": (
                row["series"] if pd.notna(row.get("series")) else None
            ),
            "genres": genres,
            "language": (
                row["language"] if pd.notna(row.get("language")) else None
            ),
            "book_format": (
                row["bookFormat"]
                if pd.notna(row.get("bookFormat"))
                else None
            ),
            "publisher": (
                row["publisher"]
                if pd.notna(row.get("publisher"))
                else None
            ),
            "description": (
                row["description"]
                if pd.notna(row.get("description"))
                else ""
            ),

            # numerice
            "pages": safe_int(row.get("pages")),
            "avg_rating": safe_float(row.get("rating")),
            "num_ratings": safe_int(row.get("numRatings")),
            "liked_percent": safe_float(row.get("likedPercent")),
            "bbe_score": safe_float(row.get("bbeScore")),
            "bbe_votes": safe_int(row.get("bbeVotes")),
            "price": safe_float(row.get("price")),
            "publish_year": safe_int(row.get("publish_year")),
            "description_len": safe_int(row.get("description_len")),
            "popularity": safe_float(row.get("popularity")),
            "has_awards": bool(has_awards),
        }

        # 1) adaugam itemul (daca nu exista)
        batch_requests.append(AddItem(item_id))

        # 2) setam proprietatile
        batch_requests.append(
            SetItemValues(
                item_id,
                props,
                cascade_create=True,  # in caz ca exista item nou
            )
        )

        # trimitem in batch-uri
        if len(batch_requests) >= BATCH_SIZE:
            client.send(Batch(batch_requests))
            batch_requests = []

    # ce a mai ramas
    if batch_requests:
        client.send(Batch(batch_requests))


if __name__ == "__main__":
    main()
