import json
import re
from urllib.parse import urlencode

from primp import Client

ORIGIN, DEST = "SIN", "NRT"
DEP_DATE, RET_DATE = "2026-09-15", "2026-09-23"
GRAPH_START, GRAPH_END = "2026-09-08", "2026-11-06"
TRIP_LEN = 8

TFS = (
    "CBwQAhooEgoyMDI2LTA5LTE1agwIAhIIL20vMDZ0MnRyDAgDEggvbS8wN2RmaxooEgoyMDI2LTA5LTIzagwIAxIIL20vMDdkZmtyDAgCEggvbS8wNnQydEABSAFwAYIBCwj___________8BmAEB"
)

client = Client(
    impersonate="chrome_145",
    impersonate_os="macos",
    referer=True,
    cookie_store=True,
)

search_url = "https://www.google.com/travel/flights/search"
page = client.get(search_url, params={"tfs": TFS, "hl": "en", "curr": "USD"})
html = page.text

f_sid = re.search(r'"FdrFJe":"(-?\d+)"', html).group(1)
bl = re.search(r'"cfb2h":"([^"]+)"', html).group(1)

mids = re.findall(r'\["(/m/[a-z0-9]+)",(\d+)\]\]', html)
origin_mid, origin_type = mids[0]
dest_mid, dest_type = mids[1]
print(f"f.sid={f_sid} bl={bl}")
print(f"origin_mid={origin_mid} ({origin_type}) dest_mid={dest_mid} ({dest_type})")

search_leg = lambda o_mid, o_type, d_mid, d_type, date: [
    [[[[o_mid, int(o_type)]]], [[[d_mid, int(d_type)]]], None, 0, None, None, date, None, None, None, None, None, None, None, 3]
]

inner = [
    None,
    [
        None, None, 1, None, [], 1, [1, 0, 0, 0], None, None, None, None, None, None,
        [
            *search_leg(origin_mid, origin_type, dest_mid, dest_type, DEP_DATE),
            *search_leg(dest_mid, dest_type, origin_mid, origin_type, RET_DATE),
        ],
        None, None, None, 1,
    ],
    [GRAPH_START, GRAPH_END],
    None,
    [TRIP_LEN, TRIP_LEN],
]

f_req = json.dumps([None, json.dumps(inner, separators=(",", ":"))], separators=(",", ":"))

rpc_url = (
    "https://www.google.com/_/FlightsFrontendUi/data/"
    "travel.frontend.flights.FlightsFrontendService/GetCalendarGraph"
)
params = {
    "f.sid": f_sid,
    "bl": bl,
    "hl": "en",
    "soc-app": "162",
    "soc-platform": "1",
    "soc-device": "1",
    "_reqid": "1000001",
    "rt": "c",
}
body = urlencode({"f.req": f_req})

res = client.post(
    rpc_url + "?" + urlencode(params),
    data=body,
    headers={
        "content-type": "application/x-www-form-urlencoded;charset=UTF-8",
        "x-same-domain": "1",
        "origin": "https://www.google.com",
    },
)
print("status", res.status_code)
text = res.text


def parse_batchexecute(text: str):
    stripped = re.sub(r"^\)\]\}'\n?", "", text).strip("\n")
    lines = stripped.split("\n")
    chunks = []
    i = 0
    while i < len(lines):
        if lines[i].strip().isdigit():
            chunks.append(json.loads(lines[i + 1]))
            i += 2
        else:
            i += 1
    return chunks


chunks = parse_batchexecute(text)
if not chunks or not chunks[0]:
    print("EMPTY/ERROR RESPONSE, raw text below:")
    print(text[:2000])
else:
    frame = chunks[0][0]
    inner_payload = json.loads(frame[2])
    entries = inner_payload[1]
    print(f"Got {len(entries)} date/price points")
    for date, ret_date, price_info, *_ in entries[:15]:
        price = price_info[0][1]
        print(f"{date} -> {ret_date}: ${price}")
