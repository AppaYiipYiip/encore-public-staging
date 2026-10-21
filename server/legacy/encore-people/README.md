# encore-people

The small service behind **invites** and **friend activity** (docs/35, ADR-087). Python 3.11+, standard library only, no network
needed to test.

```
cd server/encore-people
python -m unittest discover -s tests
```

Built so far (54 tests): `invites.py` (the invite state machine: hashed codes, one use, seven days, revoke, atomic claim, a failure
gives the code back), `activity.py` (opt-in, last song only, expiry, memory only), `navidrome.py` (who is asking, is that person an
administrator: the music server is the judge), `server.py` (the HTTP surface with the invitation page, rate limits, admin-only routes).
Next (docs/35 section 8): the Navidrome provisioner (reusing `server/reference/encore_user.py`), `config.py`/`__main__.py`, the Dockerfile,
the `people` compose profile and its checks.
