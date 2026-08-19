from fast_flights import FlightQuery, Passengers, create_query, get_flights

query = create_query(
    flights=[
        FlightQuery(
            date="2026-09-15",
            from_airport="SIN",
            to_airport="NRT",
        ),
    ],
    seat="economy",
    trip="one-way",
    passengers=Passengers(adults=1),
    currency="SGD",
)

result = get_flights(query)

for flight in result:
    print(flight)
