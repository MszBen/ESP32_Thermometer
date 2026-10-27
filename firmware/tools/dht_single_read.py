import dht, machine, time
s = dht.DHT11(machine.Pin(4))
time.sleep(2)
s.measure()
print(s.temperature(), s.humidity())