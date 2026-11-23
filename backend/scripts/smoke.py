"""Check a deployment end to end, the way a student would use it.

    uv run python -m scripts.smoke --base-url https://shortlist.pages.dev --invite CODE

Health, register (spends the invite), log in, save a profile, load the feed and the status
page, then delete the smoke account. Prints one line per step; exits non-zero on the first
failure. Point it at the Pages domain to test the proxy too. The first request may take a
minute while the free API host wakes.
"""

import argparse
import sys
import uuid
from collections.abc import Callable

import httpx

PASSWORD = "smoke test passphrase, not a secret"
TIMEOUT = httpx.Timeout(90.0)  # the Pages proxy retries a cold start for about 63 s


class SmokeFailure(Exception):
    pass


def expect(response: httpx.Response, status: int, step: str) -> httpx.Response:
    if response.status_code != status:
        raise SmokeFailure(
            f"{step}: expected {status}, got {response.status_code}: {response.text[:300]}"
        )
    return response


def run(client: httpx.Client, base: str, invite: str, say: Callable[[str], None]) -> None:
    api = f"{base.rstrip('/')}/api/v1"
    expect(client.get(f"{api}/health"), 200, "health")
    say("ok   health")

    email = f"smoke-{uuid.uuid4().hex[:10]}@example.com"
    body = {"email": email, "password": PASSWORD, "full_name": "Smoke Test", "invite_code": invite}
    expect(client.post(f"{api}/auth/register", json=body), 201, "register")
    say(f"ok   register {email}")

    login = expect(
        client.post(f"{api}/auth/login", json={"email": email, "password": PASSWORD}), 200, "login"
    )
    headers = {"Authorization": f"Bearer {login.json()['access_token']}"}
    say("ok   login")

    try:
        profile = {"target_roles": ["software"], "skills": [{"name": "Python", "level": 3}]}
        expect(client.put(f"{api}/profile", json=profile, headers=headers), 200, "profile")
        say("ok   profile")

        feed = expect(client.get(f"{api}/feed", headers=headers), 200, "feed").json()
        say(f"ok   feed: {len(feed['items'])} items for {feed['query_used']!r}")

        status = expect(client.get(f"{api}/status"), 200, "status").json()
        say(
            f"ok   status: {status['open_postings']} open, {status['relevant_postings']} relevant,"
            f" {len(status['failing_boards'])} failing boards"
        )
    finally:
        expect(client.delete(f"{api}/users/me", headers=headers), 204, "delete smoke account")
        say("ok   deleted the smoke account")


def main(argv: list[str] | None = None, client: httpx.Client | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--base-url", required=True, help="the Pages domain, or the API origin")
    parser.add_argument("--invite", required=True, help="an unused invite code")
    args = parser.parse_args(argv)

    own_client = client is None
    client = client or httpx.Client(timeout=TIMEOUT, follow_redirects=False)
    try:
        run(client, args.base_url, args.invite, print)
    except (SmokeFailure, httpx.HTTPError) as failure:
        print(f"FAIL {failure}")
        return 1
    finally:
        if own_client:
            client.close()
    print("smoke test passed")
    return 0


if __name__ == "__main__":
    sys.exit(main())
