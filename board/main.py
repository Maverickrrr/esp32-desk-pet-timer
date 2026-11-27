from machine import Pin
import asyncio
import binascii
import gc
import json
import socket
import struct
import network
import neopixel
import os
import time

# Pin mapping for DFRobot FireBeetle 2 ESP32-E (DFR0654 / DFR0654-F).
AP_NAME = "Furniture-ESP32"
from wifi_settings import AP_PASSWORD
LED_PIN = 2
RGB_PIN = 5
BUTTON_PIN = 27

from controller import Controller

led = Pin(LED_PIN, Pin.OUT, value=0)
rgb = neopixel.NeoPixel(Pin(RGB_PIN), 1)

def output(i, active):
    if i == 0:
        led.value(active)
    else:
        rgb[0] = (0, 24, 0) if active else (0, 0, 0)
        rgb.write()

output(1, False)
device = Controller(".", output, "ESP32 实板")
elapsed_ms = 0
clients = 0
events = []
def trace(message):
    stamp = elapsed_ms // 1000
    if events and events[-1][1] == message and stamp - events[-1][0] < 5:
        return
    events.append((stamp, message))
    if len(events) > 80:
        events.pop(0)
    print("portal", stamp, message)

token = binascii.hexlify(os.urandom(12))

async def reply(writer, code, kind, body):
    writer.write(("HTTP/1.1 %s\r\nContent-Type: %s\r\nContent-Length: %d\r\n"
                  "Cache-Control: no-store\r\nConnection: close\r\n"
                  "X-Content-Type-Options: nosniff\r\n\r\n"
                  % (code, kind, len(body))).encode())
    writer.write(body)
    await asyncio.wait_for_ms(writer.drain(), 1500)


async def request(reader):
    packet = b""
    while b"\r\n\r\n" not in packet:
        block = await reader.read(256)
        if not block:
            raise ValueError("incomplete request")
        packet += block
        if len(packet) > 4096:
            raise ValueError("headers too large")
    headers, body = packet.split(b"\r\n\r\n", 1)
    lines = headers.split(b"\r\n")
    method, path, version = lines[0].split(b" ")
    fields = {}
    for line in lines[1:]:
        key, value = line.split(b":", 1)
        fields[key.lower()] = value.strip()
    if b"transfer-encoding" in fields:
        raise ValueError("invalid host or encoding")
    length = int(fields.get(b"content-length", b"0"))
    if not 0 <= length <= 1024:
        raise ValueError("invalid content length")
    while len(body) < length:
        block = await reader.read(length - len(body))
        if not block:
            raise ValueError("incomplete body")
        body += block
    return method, path, fields, body[:length]


async def serve(reader, writer):
    global clients
    if clients >= 4:
        writer.close()
        return
    clients += 1
    try:
        method, path, fields, body = await asyncio.wait_for_ms(request(reader), 1500)
        code, kind = "200 OK", "text/plain; charset=utf-8"
        local = fields.get(b"host") in (b"192.168.4.1", b"192.168.4.1:80")
        if local and method == b"GET" and path == b"/portal-log":
            await reply(writer, "200 OK", "application/json", json.dumps(events).encode())
            return
        if method in (b"GET", b"HEAD") and (not local or path not in (b"/", b"/status")):
            writer.write(b"HTTP/1.1 302 Found\r\nLocation: http://192.168.4.1/\r\nCache-Control: no-store\r\nContent-Length: 0\r\nConnection: close\r\n\r\n")
            await asyncio.wait_for_ms(writer.drain(), 1500)
            known_path = path.split(b"?", 1)[0]
            if known_path not in (b"/hotspot-detect.html", b"/library/test/success.html", b"/generate_204", b"/connecttest.txt"):
                known_path = b"other"
            trace("HTTP 302 " + known_path.decode())
            return
        if not local:
            return
        if method == b"GET" and path == b"/":
            kind = "text/html; charset=utf-8"
            with open("index.html", "rb") as page:
                data = page.read().replace(b"__TOKEN__", token)
        elif method == b"GET" and path == b"/status":
            kind = "application/json"
            data = json.dumps(device.dispatch("/status", {}, elapsed_ms // 1000)).encode()
        elif method == b"POST" and path in (b"/clock", b"/config", b"/run", b"/stop") and fields.get(b"x-demo-token") == token:
            kind = "application/json"
            try:
                payload = json.loads(body.decode())
                if not isinstance(payload, dict):
                    raise ValueError("Invalid JSON object")
                data = json.dumps(device.dispatch(path.decode(), payload, elapsed_ms // 1000)).encode()
            except (ValueError, TypeError, OSError):
                code, data = "400 Bad Request", b"Invalid request or storage unavailable"
        else:
            code, data = "404 Not Found", b"Not found"
        await reply(writer, code, kind, data)
        if method == b"GET" and path == b"/":
            trace("HTTP 200 home")
    except (OSError, ValueError, asyncio.TimeoutError):
        pass
    finally:
        clients -= 1
        writer.close()


def dns_reply(packet):
    if len(packet) < 17 or packet[2] & 0xf8 or packet[4:6] != b"\x00\x01":
        return None
    pos = 12
    while pos < len(packet) and packet[pos]:
        size = packet[pos]
        if size > 63 or pos + size + 1 >= len(packet):
            return None
        pos += size + 1
    end = pos + 5
    if end > len(packet):
        return None
    kind, family = struct.unpack("!HH", packet[pos+1:end])
    found = family == 1 and kind in (1, 255)
    header = packet[:2] + struct.pack("!HHHHH", 0x8400 | (packet[2] & 1) * 256, 1, int(found), 0, 0)
    answer = b"\xc0\x0c" + struct.pack("!HHIH", 1, 1, 0, 4) + bytes((192,168,4,1)) if found else b""
    return header + packet[12:end] + answer


async def dns_loop(sock):
    while True:
        try:
            packet, peer = sock.recvfrom(512)
            answer = dns_reply(packet)
            if answer:
                sock.sendto(answer, peer)
                category = "Apple" if b"apple" in packet[12:].lower() else "other"
                trace("DNS " + category + " " + peer[0])
        except OSError:
            pass
        await asyncio.sleep_ms(20)


async def main():
    global elapsed_ms
    if not 8 <= len(AP_PASSWORD) <= 63:
        raise ValueError("AP password must have 8 to 63 ASCII characters")
    network.WLAN(network.WLAN.IF_STA).active(False)
    ap = network.WLAN(network.WLAN.IF_AP)
    ap.active(True)
    ap.config(ssid=AP_NAME, security=network.WLAN.SEC_WPA2, key=AP_PASSWORD)
    ap.ifconfig(("192.168.4.1", "255.255.255.0", "192.168.4.1", "192.168.4.1"))
    server = await asyncio.start_server(serve, "192.168.4.1", 80)
    dns = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    dns.bind(("192.168.4.1", 53))
    dns.setblocking(False)
    worker = asyncio.create_task(dns_loop(dns))
    print("Furniture-ESP32: http://%s/" % ap.ifconfig()[0])
    last_check = -1000
    previous_count = -1
    previous = time.ticks_ms()
    try:
        while True:
            now = time.ticks_ms()
            elapsed_ms += time.ticks_diff(now, previous)
            previous = now
            device.tick(elapsed_ms // 1000)
            if elapsed_ms - last_check >= 1000:
                last_check = elapsed_ms
                try:
                    count = len(ap.status("stations"))
                    if count != previous_count:
                        trace("WiFi clients " + str(count))
                        previous_count = count
                except (OSError, ValueError):
                    pass
            await asyncio.sleep_ms(25)
    finally:
        led.off()
        rgb[0] = (0, 0, 0)
        rgb.write()
        worker.cancel()
        dns.close()
        server.close()


if __name__ == "__main__":
    asyncio.run(main())
