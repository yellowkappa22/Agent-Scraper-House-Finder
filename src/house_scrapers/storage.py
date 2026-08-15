from __future__ import annotations

import json
from collections.abc import Mapping
from datetime import datetime, timezone

STORAGE_ACCOUNT_URL = "https://ykhousingstorage.blob.core.windows.net"
STORAGE_CONTAINER = "scraping-results"

def archived_timestamp() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")

def archived_offer(offer: Mapping[str, object], timestamp: str) -> dict[str, object]:
    item = dict(offer)
    item.setdefault("archived", timestamp)
    return item


class BlobOfferStore:
    def __init__(self, blob_client: object) -> None:
        self.blob_client = blob_client
        self.offers = self._load()

    def _load(self) -> list[dict[str, object]]:
        if not self.blob_client.exists():
            return []
        offers = json.loads(self.blob_client.download_blob().readall())
        if not isinstance(offers, list) or any(not isinstance(offer, dict) for offer in offers):
            raise ValueError("Offer blob must contain a JSON list of objects")
        return offers

    def address_exists(self, address: str) -> bool:
        return any(offer.get("address") == address for offer in self.offers)

    def save(self, offer: Mapping[str, object]) -> None:
        self.save_many([offer])

    def save_many(self, offers: list[Mapping[str, object]]) -> None:
        timestamp = archived_timestamp()
        self.offers.extend(archived_offer(offer, timestamp) for offer in offers)
        self.blob_client.upload_blob(json.dumps(self.offers, indent=2), overwrite=True)

    def upsert_many(self, offers: list[Mapping[str, object]]) -> None:
        positions = {
            str(offer["link"]): index
            for index, offer in enumerate(self.offers)
            if offer.get("link")
        }
        timestamp = archived_timestamp()
        for offer in offers:
            item = archived_offer(offer, timestamp)
            link = str(item.get("link") or "")
            if link and link in positions:
                self.offers[positions[link]] = item
            else:
                positions[link] = len(self.offers)
                self.offers.append(item)
        self.blob_client.upload_blob(json.dumps(self.offers, indent=2), overwrite=True)

    def replace_all(self, offers: list[Mapping[str, object]]) -> None:
        self.offers = [dict(offer) for offer in offers]
        self.blob_client.upload_blob(json.dumps(self.offers, indent=2), overwrite=True)

    def update_activity(self, seen_links: set[str], *, complete: bool) -> None:
        timestamp = archived_timestamp()
        for offer in self.offers:
            link = str(offer.get("link") or "")
            if link in seen_links:
                offer["active"] = True
                offer["last_seen"] = timestamp
                offer.pop("inactive_at", None)
            elif complete and offer.get("active") is not False:
                offer["active"] = False
                offer["inactive_at"] = timestamp
        self.blob_client.upload_blob(json.dumps(self.offers, indent=2), overwrite=True)


def open_offer_store(blob_name: str) -> BlobOfferStore:
    from azure.identity import DefaultAzureCredential
    from azure.storage.blob import BlobServiceClient

    service = BlobServiceClient(STORAGE_ACCOUNT_URL, credential=DefaultAzureCredential())
    blob = service.get_container_client(STORAGE_CONTAINER).get_blob_client(blob_name)
    return BlobOfferStore(blob)
