from machine import Pin
import time
p = Pin(4, Pin.IN, Pin.PULL_DOWN)
time.sleep(0.5)
for _ in range(5):
    print(p.value())
    time.sleep(0.2)