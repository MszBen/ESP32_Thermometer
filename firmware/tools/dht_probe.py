import dht, machine, time

pin = machine.Pin(4, machine.Pin.IN, machine.Pin.PULL_UP)
time.sleep(3)

for name, cls in (("DHT11", dht.DHT11), ("DHT22", dht.DHT22)):
    s = cls(pin)
    for attempt in range(5):
        try:
            s.measure()
            print(name, "OK:", s.temperature(), "C", s.humidity(), "%")
            raise SystemExit
        except OSError as e:
            print(name, "attempt", attempt + 1, "failed:", e)
            time.sleep(2)