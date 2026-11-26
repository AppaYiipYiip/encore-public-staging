"""The HTTP routes of the server, one module per area (docs/17 names the module of each group; P3-31).

`api.py` assembles them and nothing else lives there but the application's wiring. The shared pieces (the services of a request, who is asking,
the answer shapes) are in `common.py`; a name that starts with an underscore there is shared inside this package only.
"""
