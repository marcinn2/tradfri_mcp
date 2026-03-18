# cython: language_level=2
cimport tdtls
from tdtls cimport dtls_context_t, dtls_handler_t, session_t, dtls_alert_level_t, dtls_credentials_type_t
from libc.stdint cimport uint8_t
from libc.stddef cimport size_t
ctypedef uint8_t uint8
import socket
from libc cimport string

DTLS_CLIENT = tdtls.DTLS_CLIENT
DTLS_SERVER = tdtls.DTLS_SERVER

DTLS_LOG_EMERG  = tdtls.DTLS_LOG_EMERG
DTLS_LOG_ALERT  = tdtls.DTLS_LOG_ALERT
DTLS_LOG_CRIT   = tdtls.DTLS_LOG_CRIT
DTLS_LOG_WARN   = tdtls.DTLS_LOG_WARN
DTLS_LOG_NOTICE = tdtls.DTLS_LOG_NOTICE
DTLS_LOG_INFO   = tdtls.DTLS_LOG_INFO
DTLS_LOG_DEBUG  = tdtls.DTLS_LOG_DEBUG


cdef int _write(dtls_context_t *ctx, session_t *session, uint8 *buf, size_t len) except -1:
  """Send data to socket"""
  self = <object>(ctx.app)
  data = buf[:len]
  assert session.addr.sin6.sin6_family == socket.AF_INET6
  ip   = socket.inet_ntop(socket.AF_INET6, session.addr.sin6.sin6_addr.s6_addr[:16])
  port = socket.ntohs(session.addr.sin6.sin6_port)
  cdef int ret = self.pycb['write']((ip, port), data)
  return ret
  
cdef int _read(dtls_context_t *ctx, session_t *session, uint8 *buf, size_t len) except -1:
  """Send data to application"""
  self = <object>(ctx.app)
  data = buf[:len]
  assert session.addr.sin6.sin6_family == socket.AF_INET6
  ip   = socket.inet_ntop(socket.AF_INET6, session.addr.sin6.sin6_addr.s6_addr[:16])
  port = socket.ntohs(session.addr.sin6.sin6_port)
  cdef int ret = self.pycb['read']((ip, port), data)
  return ret
  
cdef int _event(dtls_context_t *ctx, session_t *session, dtls_alert_level_t level, unsigned short code) except -1:
  """The event handler is called when a message from the alert protocol is received or the state of the DTLS session changes."""
  self = <object>(ctx.app)
  if self.pycb['event'] != None:
    self.pycb['event'](level, code)
  else:
    print "event:", hex(level), hex(code)
  return 0;

cdef int _get_psk_info(dtls_context_t *ctx,
		      const session_t *session,
		      dtls_credentials_type_t req_type,
		      const unsigned char *desc_data,
		      size_t desc_len,
		      unsigned char *result_data,
		      size_t result_length) except -1:
  """Called during handshake to get information related to the psk key exchange. 
   
   The type of information requested is indicated by @p type 
   which will be one of DTLS_PSK_HINT, DTLS_PSK_IDENTITY, or DTLS_PSK_KEY.
   
   The called function must store the requested item in the buffer @p result 
   of size @p result_length. 
   On success, the function must return
   the actual number of bytes written to @p result, or a
   value less than zero on error. The parameter @p desc may
   contain additional request information (e.g. the psk_identity
   for which a key is requested when @p type == @c DTLS_PSK_KEY.
   
   @param ctx     The current dtls context.
   @param session The session where the key will be used.
   @param type    The type of the requested information.
   @param desc    Additional request information
   @param desc_len The actual length of desc.
   @param result  Must be filled with the requested information.
   @param result_length  Maximum size of @p result.
   @return The number of bytes written to @p result or a value
           less than zero on error. """
  self = <DTLS>(ctx.app)
  
  assert session.addr.sin6.sin6_family == socket.AF_INET6
  ip   = socket.inet_ntop(socket.AF_INET6, session.addr.sin6.sin6_addr.s6_addr[:16])
  port = socket.ntohs(session.addr.sin6.sin6_port)
  desc = desc_data[:desc_len]
  #result = result_data[:result_length]
  cdef char *tmp
  
  import sys as _sys
  if   req_type == tdtls.DTLS_PSK_HINT: # ??? TODO
    _sys.stderr.write("PSK HINT desc=%r\n" % (desc,)); _sys.stderr.flush()
    pass
  elif req_type == tdtls.DTLS_PSK_IDENTITY:
    l = len(self.pskId)
    _sys.stderr.write("PSK IDENTITY pskId=%r l=%d\n" % (bytes(self.pskId[:l]), l)); _sys.stderr.flush()
    if result_length >= l:
      string.memcpy(result_data, <char*>(self.pskId), l)
      return l
    else:
      return -1
  elif req_type == tdtls.DTLS_PSK_KEY:
    _sys.stderr.write("PSK KEY desc=%r store=%r\n" % (desc, list(self.pskStore.keys()))); _sys.stderr.flush()
    if desc in self.pskStore.keys():
      l = len(self.pskStore[desc])
      tmp = self.pskStore[desc]
      string.memcpy(result_data, tmp, l)
      _sys.stderr.write("PSK KEY found l=%d\n" % l); _sys.stderr.flush()
      return l
    else:
      _sys.stderr.write("PSK KEY NOT FOUND\n"); _sys.stderr.flush()
      return -1
  else:
    return -1
  return 0

cdef class Session:
    cdef session_t session
    def __init__(self, addr, int port=0, int flowinfo=0, int scope_id=0):
      assert sizeof(self.session.addr.sin6) == 28
      self.session.size = sizeof(self.session.addr.sin6)
      self.session.addr.sin6.sin6_family   = socket.AF_INET6
      
      tmpaddr = socket.inet_pton(self.session.addr.sin6.sin6_family, addr)
      string.memcpy(self.session.addr.sin6.sin6_addr.s6_addr, <char*>tmpaddr, 16)
      
      self.session.addr.sin6.sin6_port     = socket.htons(port)
      self.session.addr.sin6.sin6_flowinfo = flowinfo
      self.session.addr.sin6.sin6_scope_id = scope_id
      self.session.ifindex = 0
    @property
    def family(self):
      return self.session.addr.sin6.sin6_family
    @property
    def addr(self):
      return socket.inet_ntop(self.session.addr.sin6.sin6_family, self.session.addr.sin6.sin6_addr.s6_addr[:16])
    @property
    def port(self):
      return socket.ntohs(self.session.addr.sin6.sin6_port)
    @property
    def flowinfo(self):
      return self.session.addr.sin6.sin6_flowinfo
    @property
    def scope_id(self):
      return self.session.addr.sin6.sin6_scope_id
    @property
    def ifindex(self):
      return self.session.ifindex
    cdef session_t* getSession(self):
        return &self.session
    cdef p(self):
      print "Sesion dump:", self.session.size, self.family, self.addr, self.port, self.flowinfo, self.scope_id, self.ifindex

cdef class Connection(Session):
  cdef DTLS d
  def __init__(self, DTLS dtls, Session s):
    super().__init__(addr = s.addr, port = s.port, flowinfo=s.flowinfo, scope_id=s.scope_id)
    self.d = dtls
  def __dealloc__(self):
    peer = tdtls.dtls_get_peer(self.d.ctx, &self.session)
    if peer:
      tdtls.dtls_reset_peer(self.d.ctx, peer)

cdef class MCConnection(Session):
  cdef DTLS d
  def __init__(self, DTLS dtls, Session s):
    super().__init__(addr = s.addr, port = s.port, flowinfo=s.flowinfo, scope_id=s.scope_id)
    self.d = dtls
  def __dealloc__(self):
    peer = tdtls.dtls_get_peer(self.d.ctx, &self.session)
    if peer:
      tdtls.dtls_reset_peer(self.d.ctx, peer)

cdef class DTLS:
  cdef dtls_context_t *ctx
  cdef dtls_handler_t cb
  cdef public object pycb
  cdef public char* pskId
  cdef public object pskStore
  
  #@property
  #def pycb(self):
    #return self.pycb
  
  #@property
  #def pskId(self):
    #return self.pskId
  
  #@property
  #def pskStore(self):
    #return self.pskStore
  
  def __cinit__(self):
    tdtls.dtls_init()
    self.ctx = tdtls.dtls_new_context(<void*>self)
    self.cb.write = _write
    self.cb.read  = _read
    self.cb.event = _event
    self.cb.get_psk_info = _get_psk_info
    tdtls.dtls_set_handler(self.ctx, &self.cb)
    
  def __dealloc__(self):
    tdtls.dtls_free_context(self.ctx)
    
  def __init__(self, read=None, write=None, event=None, pskId=b"Id", pskStore={b"Id": b"secret"}):
    self.pycb = dict()
    if read == None:
      read = self.p
    self.pycb['read']  = read
    if write == None:
      write = self.p
    self.pycb['write'] = write
    self.pycb['event'] = event
    
    self.pskId = pskId
    self.pskStore = pskStore
  
  def p(self, x, y):
    print "default cb, addr:", x,"data:", y
    return len(y)
  
  #int dtls_connect(dtls_context_t *ctx, const session_t *dst)
  def connect(self, addr, port=0, flowinfo=0, scope_id=0):
    session = Session(addr=addr, port=port, flowinfo=flowinfo, scope_id=scope_id)
    #session.p()
    ret = tdtls.dtls_connect(self.ctx, session.getSession());
    if(ret == 0):
      print "already connected to", addr
      return Connection(self, session)
    elif ret > 0:
      return Connection(self, session)
    else:
      print "error", ret
      return None


  #int dtls_close(dtls_context_t *ctx, const session_t *remote)
  def close(self, Session session: Session):
    ret = tdtls.dtls_close(self.ctx, session.getSession())
    if ret != 0:
      print "Error in close:", ret
      raise Exception()

  #dtls_peer_t *dtls_get_peer(const dtls_context_t *context, const session_t *session);
  #void dtls_reset_peer(dtls_context_t *ctx, dtls_peer_t *peer)
  def resetPeer(self, Session session: Session):
    peer = tdtls.dtls_get_peer(self.ctx, &session.session)
    if peer:
      tdtls.dtls_reset_peer(self.ctx, peer)

  #int dtls_write(dtls_context_t *ctx, session_t *session, uint8 *buf, size_t len)
  def write(self, Session remote: Session, data: bytes):
    """send data to remote"""
    return tdtls.dtls_write(self.ctx, remote.getSession(), data, len(data))
  
  #void dtls_check_retransmit(dtls_context_t *context, clock_time_t *next)
  def checkRetransmit(self):
    cdef tdtls.clock_time_t t = 0;
    tdtls.dtls_check_retransmit(self.ctx, &t)
    return t
  
  #int dtls_handle_message(dtls_context_t *ctx, session_t *session, uint8 *msg, int msglen)
  def handleMessage(self, session, msg):
    return tdtls.dtls_handle_message(self.ctx, (<Session?>session).getSession(), msg, len(msg))
  
  def handleMessageAddr(self, addr, port, msg):
    session = Session(addr, port)
    return tdtls.dtls_handle_message(self.ctx, (<Session?>session).getSession(), msg, len(msg))
  
def setLogLevel(level):
  tdtls.dtls_set_log_level(level)

def dtlsGetLogLevel():
  return tdtls.dtls_get_log_level()
