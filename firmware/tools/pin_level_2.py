from machine import Pin
import time
p = Pin(4, Pin.IN)
for _ in range(5):
    print(p.value())
    time.sleep(0.2)