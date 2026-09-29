"""Historical observation reads.

There is no longer a standalone `market_observations` collection. Historical
evidence used for ML training and for "previously seen comparables" is
reconstructed from the `observations` embedded inside every user's
`search_history` entries in the `users` collection (see user_store.py).
Writes happen through UserStore.add_search_history, which is called once per
request with the full set of observations collected for that search.
"""
from app.services.user_store import UserStore


class ObservationStore:
    def __init__(self, user_store: UserStore | None = None):
        self._users = user_store or UserStore()

    def all(self, property_type: str, bhk: str | None = None, limit: int = 10000) -> list[dict]:
        return self._users.all_observations(property_type, bhk, limit)

    def find(self, location: str, property_type: str, bhk: str | None = None, limit: int = 5000) -> list[dict]:
        return self._users.find_observations(location, property_type, bhk, limit)
