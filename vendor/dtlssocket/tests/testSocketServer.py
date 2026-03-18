from DTLSSocket import dtls
import time, socket

sock = socket.socket(family=socket.AF_INET6, type=socket.SOCK_DGRAM)
sock.setsockopt(socket.IPPROTO_IPV6, socket.IPV6_RECVPKTINFO, 1)
sock.bind(('', 20220, 0, 0))

def read(x, y):
  print("> read:", x, y)
  return len(y)

def write(x, y):
  #print("< write:", x, y.hex())
  ip, port = x
  return sock.sendto(y, x)

lastEvent = 0
def event(level, code):
  global lastEvent
  lastEvent = code

def pprint(x):
  print("\n---", x, "---")

def querySock(sock, d):
  data, ancdata, flags, src = sock.recvmsg(1200, 100)
  #print("Got:", data, ancdata, flags, src)
  dst = 0
  d.handleMessageAddr(src[0], src[1], data)


#dtls.setLogLevel(dtls.DTLS_LOG_DEBUG)
print("Log Level:", dtls.dtlsGetLogLevel())

d = dtls.DTLS(read=read, write=write, event=event, pskId=b"Client_identity", pskStore={b"Client_identity": b"secretPSK"})

while True:
  querySock(sock, d)
