import os
from dotenv import load_dotenv
from recombee_api_client.api_client import RecombeeClient, Region
from recombee_api_client.api_requests import AddItemProperty, Batch


load_dotenv()

client = RecombeeClient(
        os.environ["RECOMBEE_DB_ID"],
        os.environ["RECOMBEE_API_TOKEN"],
        region=Region[os.environ.get("RECOMBEE_REGION", "EU_WEST")],
)


def main():
    reqs = [
        AddItemProperty("title", "string"),
        AddItemProperty("author", "string"),
        AddItemProperty("series", "string"),
        AddItemProperty("genres", "set"),
        AddItemProperty("language", "string"),
        AddItemProperty("book_format", "string"),
        AddItemProperty("publisher", "string"),
        AddItemProperty("description", "string"),

        AddItemProperty("pages", "int"),
        AddItemProperty("avg_rating", "double"),
        AddItemProperty("num_ratings", "int"),
        AddItemProperty("liked_percent", "double"),
        AddItemProperty("bbe_score", "double"),
        AddItemProperty("bbe_votes", "int"),
        AddItemProperty("price", "double"),
        AddItemProperty("publish_year", "int"),
        AddItemProperty("description_len", "int"),
        AddItemProperty("popularity", "double"),
        AddItemProperty("has_awards", "boolean"),
    ]

    client.send(Batch(reqs))

if __name__ == "__main__":
    main()
