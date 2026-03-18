# -*- Mode: Cython -*-

from libc.stdint cimport uint8_t, uint16_t, uint32_t
ctypedef uint8_t uint8

cdef extern from "<sys/socket.h>":
  ctypedef unsigned short int sa_family_t
  ctypedef uint16_t in_port_t
  ctypedef unsigned int in_addr_t
  ctypedef unsigned int socklen_t
  
cdef extern from "<netinet/in.h>":
#  union ip__u6_addr:
#    uint8_t __u6_addr8[16]
  
  struct in6_addr:
#    ip__u6_addr __u6_addr
    uint8_t s6_addr[16]
  
  cdef struct sockaddr:
    pass
  cdef struct sockaddr_storage:
    pass
  cdef struct sockaddr_in:
    pass

  cdef struct sockaddr_in6:
    sa_family_t   sin6_family
    in_port_t     sin6_port
    unsigned int  sin6_flowinfo
    in6_addr      sin6_addr
    unsigned int  sin6_scope_id

cdef extern from "tinydtls/session.h":
  cdef union addr_un:
    sockaddr         sa
    sockaddr_storage st
    sockaddr_in      sin
    sockaddr_in6     sin6
  
  ctypedef struct session_t:
    socklen_t size
    addr_un addr
    uint8_t ifindex

cdef extern from "tinydtls/peer.h":
  ctypedef enum dtls_peer_type:
    DTLS_CLIENT=0
    DTLS_SERVER
  
  ctypedef struct dtls_peer_t:
    pass

cdef extern from "tinydtls/global.h":
  cdef int DTLS_MAX_BUF

cdef extern from "tinydtls/dtls_time.h":
  ctypedef uint32_t clock_time_t

cdef extern from "tinydtls/netq.h":
  ctypedef struct netq_t:
    pass

cdef extern from "tinydtls/dtls.h":
  cdef int DTLS_COOKIE_SECRET_LENGTH = 12
  
  ctypedef enum dtls_credentials_type_t:
    DTLS_PSK_HINT
    DTLS_PSK_IDENTITY
    DTLS_PSK_KEY

  ctypedef enum dtls_alert_level_t:
    DTLS_ALERT_LEVEL_WARNING=1
    DTLS_ALERT_LEVEL_FATAL=2
  
  ctypedef struct dtls_context_t:
    unsigned char cookie_secret[12] #DTLS_COOKIE_SECRET_LENGTH
    clock_time_t cookie_secret_age
    dtls_peer_t *peers
    netq_t *sendqueue
    void *app
    dtls_handler_t *h
    unsigned char readbuf[1400] #DTLS_MAX_BUF
  
  ctypedef struct dtls_handler_t:
    int (*write)(dtls_context_t *ctx, session_t *session, uint8 *buf, size_t len) except -1
    # Actually, the return value is ignored by tinydtls; -1 is used for errors
    # for consistency with write and get_psk_info
    int (*read)(dtls_context_t *ctx, session_t *session, uint8 *buf, size_t len) except -1
    # Actually, the return value is ignored by tinydtls; -1 is used for errors
    # for consistency with write and get_psk_info
    int (*event)(dtls_context_t *ctx, session_t *session, dtls_alert_level_t level, unsigned short code) except -1
    int (*get_psk_info)(dtls_context_t *ctx, const session_t *session, dtls_credentials_type_t type, const unsigned char *desc, size_t desc_len, unsigned char *result, size_t result_length) except -1
  
  void dtls_init()
  void dtls_set_handler(dtls_context_t *ctx, dtls_handler_t *h) #inline...
  
  dtls_context_t *dtls_new_context(void *app_data)
  void dtls_free_context(dtls_context_t *ctx)
  
  int dtls_connect(dtls_context_t *ctx, const session_t *dst)
  
  int dtls_close(dtls_context_t *ctx, const session_t *remote)
  
  dtls_peer_t *dtls_get_peer(const dtls_context_t *context, const session_t *session);
  void dtls_reset_peer(dtls_context_t *ctx, dtls_peer_t *peer)

  
  int dtls_write(dtls_context_t *ctx, session_t *session, uint8 *buf, size_t len)
  
  void dtls_check_retransmit(dtls_context_t *context, clock_time_t *next)
  
  int dtls_handle_message(dtls_context_t *ctx, session_t *session, uint8 *msg, int msglen)

cdef extern from "tinydtls/dtls_debug.h":
  ctypedef enum log_t:
    DTLS_LOG_EMERG=0
    DTLS_LOG_ALERT
    DTLS_LOG_CRIT
    DTLS_LOG_WARN
    DTLS_LOG_NOTICE
    DTLS_LOG_INFO
    DTLS_LOG_DEBUG
  void  dtls_set_log_level(int level)
  int dtls_get_log_level()
