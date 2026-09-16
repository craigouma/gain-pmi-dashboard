import os
import time

import requests

SERVER = "realist.surveycto.com"
FORM_IDS = {
    "distribution": "test_form_one_data_specialist_pmi",
    "crop_health": "test_form_two_data_specialist_pmi",
}


class SurveyCTOError(Exception):
    pass


def fetch_form(form_id: str, timeout: float = 30.0, retries: int = 3, backoff: float = 2.0) -> list[dict]:
    user = os.environ.get("SCTO_USER")
    password = os.environ.get("SCTO_PASS")
    if not user or not password:
        raise SurveyCTOError("SCTO_USER and SCTO_PASS must be set in the environment")

    url = f"https://{SERVER}/api/v2/forms/data/wide/json/{form_id}?date=0"

    last_error: Exception | None = None
    for attempt in range(retries):
        try:
            response = requests.get(url, auth=(user, password), timeout=timeout)
        except requests.RequestException as exc:
            last_error = exc
            time.sleep(backoff * (attempt + 1))
            continue

        if response.status_code != 200:
            last_error = SurveyCTOError(f"{form_id}: HTTP {response.status_code}")
            if response.status_code in (429, 500, 502, 503, 504):
                time.sleep(backoff * (attempt + 1))
                continue
            raise last_error

        try:
            return response.json()
        except ValueError:
            raise SurveyCTOError(
                f"{form_id}: response was not JSON (Content-Type {response.headers.get('Content-Type')!r}), "
                "likely an HTML login or error page. Check SCTO_USER and SCTO_PASS."
            ) from None

    raise SurveyCTOError(f"{form_id}: failed after {retries} attempts") from last_error
