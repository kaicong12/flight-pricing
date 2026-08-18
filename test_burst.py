import time
from datetime import date, timedelta

from fast_flights import FlightQuery, Passengers, create_query, get_flights

origin, dest = "SIN", "BKK"
start = date(2026, 9, 10)

for i in range(6):
    d = start + timedelta(days=i)
    t0 = time.time()
    try:
        query = create_query(
            flights=[FlightQuery(date=d.isoformat(), from_airport=origin, to_airport=dest)],
            trip="one-way",
            passengers=Passengers(adults=1),
            currency="USD",
        )
        result = get_flights(query)
        prices = sorted(f.price for f in result)
        print(f"{d} -> {len(result)} flights, min price {prices[0] if prices else None} ({time.time()-t0:.1f}s)")
    except Exception as e:
        print(f"{d} -> ERROR: {type(e).__name__}: {e} ({time.time()-t0:.1f}s)")
    time.sleep(1)
