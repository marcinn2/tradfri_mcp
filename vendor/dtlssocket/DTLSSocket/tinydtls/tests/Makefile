# Makefile for tinydtls
#
# Copyright (c) 2011, 2012, 2013, 2014, 2015 Olaf Bergmann (TZI) and others.
# All rights reserved. This program and the accompanying materials
# are made available under the terms of the Eclipse Public License v1.0
# and Eclipse Distribution License v. 1.0 which accompanies this distribution.
#
# The Eclipse Public License is available at http://www.eclipse.org/legal/epl-v10.html
# and the Eclipse Distribution License is available at 
# http://www.eclipse.org/org/documents/edl-v10.php.
#
# Contributors:
#    Olaf Bergmann  - initial API and implementation
#

# the library's version
VERSION:=0.8.6

# tools

SHELL = /bin/sh
MKDIR = mkdir
CC=gcc

abs_builddir = /Users/marcin/work/tradfri_mcp/vendor/dtlssocket/DTLSSocket/tinydtls/tests
top_builddir = ..
top_srcdir:= ..

# files and flags
SOURCES:= dtls-server.c ccm-test.c \
  dtls-client.c dtls_ciphers_util.c
  #cbc_aes128-test.c #dsrv-test.c
OBJECTS:= $(patsubst %.c, %.o, $(SOURCES))
PROGRAMS:= dtls-server dtls-client ccm-test
HEADERS:=
CFLAGS:=-Wall -std=c99 -g -O2 -fPIC -pedantic -Wall -Wextra -Wformat-security -Winline -Wmissing-declarations -Wmissing-prototypes -Wnested-externs -Wpointer-arith -Wshadow -Wstrict-prototypes -Wswitch-default -Wswitch-enum -Wunused  $(EXTRA_CFLAGS) -D_POSIX_C_SOURCE=200112L
CPPFLAGS:=-I$(top_srcdir)  -DDTLSv12 -DWITH_SHA256
LDFLAGS:=-L$(top_builddir) 
LDLIBS:=$(top_srcdir)/libtinydtls.a 
DISTDIR=$(top_builddir)/tinydtls-0.8.6
FILES:=Makefile.in $(SOURCES) ccm-testdata.c #cbc_aes128-testdata.c

.PHONY: all dirs clean distclean .gitignore doc install uninstall

.SUFFIXES:
.SUFFIXES:      .c .o

all:	$(PROGRAMS)

dtls-client dtls-server:: dtls_ciphers_util.o

check:	
	echo DISTDIR: $(DISTDIR)
	echo top_builddir: $(top_builddir)

clean:
	@rm -f $(PROGRAMS) main.o $(LIB) $(OBJECTS)
	for dir in $(SUBDIRS); do \
		$(MAKE) -C $$dir clean ; \
	done

doc:	
	$(MAKE) -C doc

distclean:	clean
	@rm -rf $(DISTDIR)
	@rm -f *~ $(DISTDIR).tar.gz

dist:	$(FILES)
	test -d $(DISTDIR)/tests || mkdir $(DISTDIR)/tests
	cp $(FILES) $(DISTDIR)/tests

# this directory contains no installation candidates
install:
	:

uninstall:
	:

.gitignore:
	echo "core\n*~\n*.[oa]\n*.gz\n*.cap\n$(PROGRAM)\n$(DISTDIR)\n.gitignore" >$@
